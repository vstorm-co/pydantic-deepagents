"""Harbor installed agent adapter for pydantic-deep.

Implements `BaseInstalledAgent` so that pydantic-deep can be evaluated
on Terminal Bench via Harbor.

Usage::

    # Gemini 3.1 Pro on Vertex AI, with Logfire tracing enabled in-container.
    export GOOGLE_GENAI_USE_VERTEXAI=true
    export GOOGLE_CLOUD_PROJECT=vstorm-495409
    export GOOGLE_CLOUD_LOCATION=us-central1
    export LOGFIRE_TOKEN=...
    harbor run -d terminal-bench/terminal-bench-2 \\
        -m google-vertex/gemini-3.1-pro-preview \\
        --agent-import-path apps.harbor.agent:PydanticDeepAgent \\
        -k 5

See ``apps/harbor/README.md`` for the full setup, the two Google auth paths,
and the analyse-traces → improve loop.
"""

from __future__ import annotations

import json
import os
import re
import shlex
from typing import Any

from harbor.agents.installed.base import BaseInstalledAgent, with_prompt_template
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

# Git ref to install from — overridable via PYDANTIC_DEEP_GIT_REF env var.
_DEFAULT_GIT_REF = "main"
_GIT_REPO = "https://github.com/vstorm-co/pydantic-deep.git"
_VENV_PATH = "/opt/pydantic-deep-venv"

# Extras installed into the container. `logfire` is required for tracing (the
# CLI's `--logfire` flag hard-errors if the package is missing); `google` pulls
# in google-genai so `google-gla:` / `google-vertex:` (Gemini) models resolve.
_INSTALL_EXTRAS = "cli,logfire,google"

# API key env vars to forward into the container.
_API_KEY_VARS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENROUTER_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "DEEPSEEK_API_KEY",
    "XAI_API_KEY",
    "CO_API_KEY",
    "CEREBRAS_API_KEY",
    "TOGETHER_API_KEY",
    "FIREWORKS_API_KEY",
    "HF_TOKEN",
    "SAMBANOVA_API_KEY",
    "GITHUB_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_DEFAULT_REGION",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "OPENAI_API_VERSION",
    "LOGFIRE_TOKEN",
    # Vertex AI (Gemini) configuration. The credentials *file* is injected
    # separately (see _build_gcp_credentials_env); these just point the SDK at
    # the right project/region and flip it into Vertex mode.
    "GOOGLE_GENAI_USE_VERTEXAI",
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
)

# Container path where the host GCP credentials JSON (user ADC or a service
# account key) is materialised before the run.
_GCP_CREDS_CONTAINER_PATH = "/tmp/gcp-credentials.json"

# Default location of user Application Default Credentials on the host.
_DEFAULT_ADC_PATH = "~/.config/gcloud/application_default_credentials.json"

# OTEL identity for benchmark traces in Logfire.
_OTEL_SERVICE_NAME = "pydantic-deep-tb"
_OTEL_ENVIRONMENT = "terminal-bench"

# Single source of truth for the agent features the harness controls. Each entry
# mirrors a `pydantic-deep run` option (apps/cli/main.py); keeping the full CLI
# surface here is what guarantees we forward every feature the agent exposes.
#
# Boolean features map to a --flag/--no-flag pair; value features to --flag VALUE.
_BOOL_FLAGS: dict[str, tuple[str, str]] = {
    "web_search": ("--web-search", "--no-web-search"),
    "web_fetch": ("--web-fetch", "--no-web-fetch"),
    "todo": ("--todo", "--no-todo"),
    "subagents": ("--subagents", "--no-subagents"),
    "skills": ("--skills", "--no-skills"),
    "plan": ("--plan", "--no-plan"),
    "memory": ("--memory", "--no-memory"),
    "teams": ("--teams", "--no-teams"),
    "context": ("--context", "--no-context"),
    "browser": ("--browser", "--no-browser"),
    "browser_headless": ("--browser-headless", "--browser-headed"),
    "liteparse": ("--liteparse", "--no-liteparse"),
}
_VALUE_FLAGS: dict[str, str] = {
    "thinking": "--thinking",
    "temperature": "--temperature",
    "sandbox": "--sandbox",
    "workspace": "--workspace",
}

# Strings that count as boolean-true when a flag arrives as text (e.g. `--ak
# subagents=true`).
_TRUTHY = frozenset({"true", "1", "yes", "on"})


class PydanticDeepAgent(BaseInstalledAgent):
    """pydantic-deep CLI agent for Harbor / Terminal Bench evaluation."""

    def __init__(
        self,
        max_turns: int | None = None,
        timeout: int | None = None,
        # Agent feature flags, forwarded to `pydantic-deep run`. `None` keeps the
        # agent's own default; explicit values (incl. "true"/"false" strings from
        # Harbor's `--ak key=value`) override it. One param per CLI feature.
        web_search: str | bool | None = None,
        web_fetch: str | bool | None = None,
        thinking: str | None = None,
        todo: str | bool | None = None,
        subagents: str | bool | None = None,
        skills: str | bool | None = None,
        plan: str | bool | None = None,
        memory: str | bool | None = None,
        teams: str | bool | None = None,
        context: str | bool | None = None,
        browser: str | bool | None = None,
        browser_headless: str | bool | None = None,
        liteparse: str | bool | None = None,
        temperature: str | float | None = None,
        sandbox: str | None = None,
        workspace: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._max_turns = max_turns
        self._timeout = timeout
        self._feature_flags: dict[str, str | bool | float | None] = {
            "web_search": web_search,
            "web_fetch": web_fetch,
            "todo": todo,
            "subagents": subagents,
            "skills": skills,
            "plan": plan,
            "memory": memory,
            "teams": teams,
            "context": context,
            "browser": browser,
            "browser_headless": browser_headless,
            "liteparse": liteparse,
            "thinking": thinking,
            "temperature": temperature,
            "sandbox": sandbox,
            "workspace": workspace,
        }

    @staticmethod
    def name() -> str:  # pragma: no cover
        return "pydantic-deep"

    def version(self) -> str | None:  # pragma: no cover
        return self._version

    async def install(self, environment: BaseEnvironment) -> None:
        """Install pydantic-deep and dependencies in the container."""
        git_ref = os.environ.get("PYDANTIC_DEEP_GIT_REF", _DEFAULT_GIT_REF)
        install_script = _build_install_script(git_ref)
        await self.exec_as_root(environment, command=install_script)

    @with_prompt_template
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        """Run pydantic-deep in headless mode on the given task."""
        pai_model = convert_model_name(self.model_name) if self.model_name else None

        # Assemble the container env: API keys + Vertex config, GCP credentials
        # (base64), and OTEL tags so each task's Logfire trace is identifiable.
        env = collect_env_vars()
        env.update(_build_gcp_credentials_env())
        env.update(self._build_otel_env())

        command = build_run_command(
            instruction=instruction,
            model=pai_model,
            max_turns=self._max_turns,
            timeout=self._timeout,
            feature_flags=self._feature_flags,
        )

        await self.exec_as_agent(
            environment,
            command=command,
            env=env,
        )

    def _build_otel_env(self) -> dict[str, str]:
        """OTEL resource attributes that tag this run's Logfire trace.

        Logfire honours the standard ``OTEL_SERVICE_NAME`` and
        ``OTEL_RESOURCE_ATTRIBUTES`` env vars, so these land on every span of the
        run. ``tb.task`` groups all trials of one benchmark task (the key you
        query in the analyse → improve loop); ``tb.trial`` is unique per attempt.
        """
        logs_dir = getattr(self, "logs_dir", None)
        trial, task = _trial_and_task(getattr(self, "session_id", None), logs_dir)
        attrs = [f"deployment.environment={_OTEL_ENVIRONMENT}"]
        if task:
            attrs.append(f"tb.task={task}")
        if trial:
            attrs.append(f"tb.trial={trial}")
        if logs_dir is not None:
            attrs.append(f"tb.logs_path={logs_dir}")
        return {
            "OTEL_SERVICE_NAME": _OTEL_SERVICE_NAME,
            "OTEL_RESOURCE_ATTRIBUTES": ",".join(attrs),
        }

    def populate_context_post_run(self, context: AgentContext) -> None:
        """Populate token/cost fields on the context from the agent's output.

        Maps our `--json` usage block onto the real `AgentContext` fields
        (`n_input_tokens` / `n_output_tokens` / `cost_usd`).
        """
        text = self._read_run_log()
        if text is None:
            return

        json_result = parse_json_output(text)
        if json_result is not None:
            usage = json_result.get("usage", {})
            if (value := usage.get("request_tokens")) is not None:
                context.n_input_tokens = value
            if (value := usage.get("response_tokens")) is not None:
                context.n_output_tokens = value

        cost = parse_cost(text)
        if cost is not None:
            context.cost_usd = cost

    def _read_run_log(self) -> str | None:
        """Read the agent's captured stdout, if present.

        Prefers our own tee'd file (`<logs_dir>/pydantic-deep.txt`) and falls
        back to Harbor's per-command capture.
        """
        for candidate in (
            self.logs_dir / "pydantic-deep.txt",
            self.logs_dir / "command-0" / "stdout.txt",
        ):
            if candidate.exists():
                return candidate.read_text()
        return None


def convert_model_name(harbor_name: str, *, vertex: bool | None = None) -> str:
    """Convert Harbor `provider/model` to a pydantic-ai `provider:model` string.

    Google needs special handling: pydantic-ai has no bare ``google:`` provider,
    only ``google-gla:`` (Gemini Developer API) and ``google-vertex:`` (Vertex
    AI). A ``google/``, ``gemini/`` or ``vertex/`` prefix is routed to whichever
    Google provider matches the credentials in play — ``vertex`` when explicitly
    requested or when Vertex env vars are present, otherwise the Developer API.

    Args:
        harbor_name: Harbor model id (``provider/model``), a full pydantic-ai
            id (``provider:model``), or a bare model name.
        vertex: Force Vertex (True) or Developer API (False) for Google models.
            ``None`` auto-detects from the environment.

    Examples:
        >>> convert_model_name("anthropic/claude-opus-4-6")
        'anthropic:claude-opus-4-6'
        >>> convert_model_name("google/gemini-3.1-pro-preview", vertex=True)
        'google-vertex:gemini-3.1-pro-preview'
        >>> convert_model_name("gemini/gemini-3.1-pro-preview", vertex=False)
        'google-gla:gemini-3.1-pro-preview'
        >>> convert_model_name("vertex/gemini-3.5-flash")
        'google-vertex:gemini-3.5-flash'
        >>> convert_model_name("openai:gpt-5.4")
        'openai:gpt-5.4'
        >>> convert_model_name("gpt-5.4")
        'gpt-5.4'
    """
    if ":" in harbor_name:
        return harbor_name
    if "/" not in harbor_name:
        return harbor_name

    provider, model = harbor_name.split("/", 1)
    provider_lc = provider.lower()

    if provider_lc in ("google", "gemini", "vertex", "google-vertex", "google-gla"):
        if provider_lc == "google-gla":
            return f"google-gla:{model}"
        if provider_lc in ("vertex", "google-vertex"):
            return f"google-vertex:{model}"
        use_vertex = vertex if vertex is not None else _vertex_enabled()
        prefix = "google-vertex" if use_vertex else "google-gla"
        return f"{prefix}:{model}"

    return f"{provider}:{model}"


def _vertex_enabled() -> bool:
    """Detect whether Vertex AI should be used for Google models.

    True when the SDK is explicitly flipped into Vertex mode, or when a Cloud
    project is configured (the usual signal that ADC / a service account is set
    up rather than a bare Developer API key).
    """
    flag = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower()
    if flag in ("true", "1", "yes"):
        return True
    if flag in ("false", "0", "no"):
        return False
    return bool(os.environ.get("GOOGLE_CLOUD_PROJECT"))


def collect_env_vars() -> dict[str, str]:
    """Collect API key env vars from the host environment."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    return {var: val for var in _API_KEY_VARS if (val := os.environ.get(var, ""))}


def _trial_and_task(session_id: str | None, logs_dir: Any | None) -> tuple[str | None, str | None]:
    """Resolve ``(trial_name, task_name)`` from Harbor's identifiers.

    Harbor names each trial ``f"{task_name[:32]}__{shortuuid}"`` and sets the
    agent's ``session_id`` to ``f"{trial_name}__agent"`` (harbor trial.py /
    models/trial/config.py). We take the trial name from ``session_id``
    (authoritative), falling back to the parent dir of ``logs_dir`` — which is
    ``<trials_dir>/<trial_name>/agent``. The task name is the trial name with its
    trailing ``__<uuid>`` stripped, so retries of one task share it.
    """
    trial: str | None = None
    if session_id:
        trial = session_id[: -len("__agent")] if session_id.endswith("__agent") else session_id
    if trial is None and logs_dir is not None:
        from pathlib import Path

        trial = Path(str(logs_dir)).parent.name or None

    task = trial.rsplit("__", 1)[0] if trial and "__" in trial else trial
    return trial, task


def _build_gcp_credentials_env() -> dict[str, str]:
    """Base64-encode host GCP credentials for injection into the container.

    Reads the JSON pointed to by ``GOOGLE_APPLICATION_CREDENTIALS`` (a service
    account key or user ADC), falling back to the default ADC path. Returns
    ``{"GCP_CREDS_B64": ...}`` when a file is found, else ``{}`` — so it is a
    no-op unless Vertex credentials are actually present on the host.
    """
    import base64
    from pathlib import Path

    candidates = [
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", ""),
        _DEFAULT_ADC_PATH,
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.is_file():
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            return {"GCP_CREDS_B64": encoded}
    return {}


def build_run_command(
    *,
    instruction: str,
    model: str | None = None,
    max_turns: int | None = None,
    timeout: int | None = None,
    feature_flags: dict[str, str | bool | float | None] | None = None,
    logfire: bool = True,
) -> str:
    """Build the `pydantic-deep run` shell command.

    Args:
        logfire: When True, enable Logfire tracing via the top-level
            ``--logfire`` flag (it is off by default and must appear *before*
            the ``run`` subcommand).
    """
    parts = [
        f'export PATH="{_VENV_PATH}/bin:$HOME/.local/bin:$PATH";',
        # Materialise GCP credentials (user ADC or a service-account key) passed
        # in as base64 via the GCP_CREDS_B64 env var. No-op when unset.
        'if [ -n "${GCP_CREDS_B64:-}" ]; then'
        f' echo "$GCP_CREDS_B64" | base64 -d > {_GCP_CREDS_CONTAINER_PATH};'
        f" export GOOGLE_APPLICATION_CREDENTIALS={_GCP_CREDS_CONTAINER_PATH}; fi;",
        "pydantic-deep",
    ]

    # `--logfire` is a top-level option and must precede the `run` subcommand.
    if logfire:
        parts.append("--logfire")

    parts += [
        "run",
        shlex.quote(instruction),
        "--json",
        "--verbose",
    ]

    if model:
        parts.append(f"--model {shlex.quote(model)}")
    if max_turns is not None:
        parts.append(f"--max-turns {max_turns}")
    if timeout is not None:
        parts.append(f"--timeout {timeout}")

    for key, value in (feature_flags or {}).items():
        if value is not None:
            parts.append(_format_feature_flag(key, value))

    parts.append("2>&1 | tee /logs/agent/pydantic-deep.txt")
    return " ".join(part for part in parts if part)


def _format_feature_flag(key: str, value: str | bool | float) -> str:
    """Render one feature flag as its `pydantic-deep run` CLI fragment.

    Booleans become the on/off flag from ``_BOOL_FLAGS``; everything else becomes
    ``--flag VALUE`` from ``_VALUE_FLAGS``. Unknown keys render to an empty string
    and are dropped by the caller.
    """
    if key in _BOOL_FLAGS:
        on_flag, off_flag = _BOOL_FLAGS[key]
        is_true = value is True or str(value).strip().lower() in _TRUTHY
        return on_flag if is_true else off_flag
    if key in _VALUE_FLAGS:
        return f"{_VALUE_FLAGS[key]} {shlex.quote(str(value))}"
    return ""  # pragma: no cover


def parse_json_output(text: str) -> dict[str, Any] | None:
    """Try to extract JSON output from agent stdout.

    The agent prints JSON when run with `--json`. The JSON block
    may be preceded or followed by other output (logs, warnings).
    """
    # Try the whole text first
    try:
        return json.loads(text)  # type: ignore[no-any-return]
    except (json.JSONDecodeError, ValueError):
        pass

    # Try to find a JSON block in the output
    match = re.search(r"\{[^{}]*\"output\"[^{}]*\"usage\"[^{}]*\{[^{}]*\}[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())  # type: ignore[no-any-return]
        except (json.JSONDecodeError, ValueError):
            pass

    # Try line-by-line from the end (JSON is usually the last thing printed)
    lines = text.strip().splitlines()
    for i in range(len(lines) - 1, -1, -1):
        candidate = "\n".join(lines[i:])
        try:
            return json.loads(candidate)  # type: ignore[no-any-return]
        except (json.JSONDecodeError, ValueError):
            continue

    return None


def parse_cost(text: str) -> float | None:
    """Try to extract USD cost from agent output."""
    match = re.search(r"Cost:\s*\$([0-9]+\.?[0-9]*)", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:  # pragma: no cover
            pass
    return None


def _build_install_script(git_ref: str) -> str:
    """Build the shell script that installs pydantic-deep in the container."""
    return f"""\
set -euo pipefail

# System dependencies
if command -v apk &> /dev/null; then
    apk add --no-cache curl bash git procps python3
elif command -v apt-get &> /dev/null; then
    apt-get update -qq
    apt-get install -y -qq curl git procps python3 python3-venv
fi

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# Ensure Python is available
if ! command -v python3 &> /dev/null; then
    uv python install 3.12
fi

# Create venv and install pydantic-deep
uv venv {_VENV_PATH}
export PATH="{_VENV_PATH}/bin:$PATH"
export VIRTUAL_ENV="{_VENV_PATH}"

uv pip install "pydantic-deep[{_INSTALL_EXTRAS}] @ git+{_GIT_REPO}@{git_ref}"

# Verify installation
pydantic-deep --version
mkdir -p /logs/agent
"""
