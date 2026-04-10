"""Harbor installed agent adapter for pydantic-deep.

Implements ``BaseInstalledAgent`` so that pydantic-deep can be evaluated
on Terminal Bench via Harbor.

Usage::

    harbor run -d "terminal-bench@2.0" \\
        -m anthropic/claude-opus-4-6 \\
        --agent-import-path apps.harbor.agent:PydanticDeepAgent
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
_GIT_REPO = "https://github.com/vstorm-co/pydantic-deepagents.git"
_VENV_PATH = "/opt/pydantic-deep-venv"

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
)


class PydanticDeepAgent(BaseInstalledAgent):
    """pydantic-deep CLI agent for Harbor / Terminal Bench evaluation."""

    def __init__(
        self,
        max_turns: int | None = None,
        timeout: int | None = None,
        # Feature flags — forwarded as --flag/--no-flag to pydantic-deep run.
        # None = use pydantic-deep defaults; "true"/"false" strings from --ak.
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
        temperature: str | float | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._max_turns = max_turns
        self._timeout = timeout
        self._feature_flags: dict[str, str | bool | float | None] = {
            "web_search": web_search,
            "web_fetch": web_fetch,
            "thinking": thinking,
            "todo": todo,
            "subagents": subagents,
            "skills": skills,
            "plan": plan,
            "memory": memory,
            "teams": teams,
            "context": context,
            "temperature": temperature,
        }

    @staticmethod
    def name() -> str:  # pragma: no cover
        return "pydantic-deep"

    def version(self) -> str | None:  # pragma: no cover
        return self._version

    # ── install ────────────────────────────────────────────────────

    async def install(self, environment: BaseEnvironment) -> None:
        """Install pydantic-deep and dependencies in the container."""
        git_ref = os.environ.get("PYDANTIC_DEEP_GIT_REF", _DEFAULT_GIT_REF)
        install_script = _build_install_script(git_ref)
        await self.exec_as_root(environment, command=install_script)

    # ── run ────────────────────────────────────────────────────────

    @with_prompt_template
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        """Run pydantic-deep in headless mode on the given task."""
        pai_model = convert_model_name(self.model_name) if self.model_name else None
        env = collect_env_vars()

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

    # ── post-run ──────────────────────────────────────────────────

    def populate_context_post_run(self, context: AgentContext) -> None:
        """Parse agent output for cost and usage information."""
        log_path = self.logs_dir / "command-0" / "stdout.txt"
        if not log_path.exists():
            return

        text = log_path.read_text()

        # Try JSON output first (--json mode)
        json_result = parse_json_output(text)
        if json_result is not None:
            usage = json_result.get("usage", {})
            total_tokens = usage.get("total_tokens")
            if total_tokens is not None:
                context.total_tokens = total_tokens

        # Try regex fallback for cost
        cost = parse_cost(text)
        if cost is not None:
            context.cost_usd = cost


# ── Helpers (module-level for testability) ────────────────────────


def convert_model_name(harbor_name: str) -> str:
    """Convert Harbor ``provider/model`` to pydantic-ai ``provider:model``.

    Examples:
        >>> convert_model_name("anthropic/claude-opus-4-6")
        'anthropic:claude-opus-4-6'
        >>> convert_model_name("openai:gpt-5.4")
        'openai:gpt-5.4'
        >>> convert_model_name("gpt-5.4")
        'gpt-5.4'
    """
    if ":" in harbor_name:
        return harbor_name
    if "/" in harbor_name:
        provider, model = harbor_name.split("/", 1)
        return f"{provider}:{model}"
    return harbor_name


def collect_env_vars() -> dict[str, str]:
    """Collect API key env vars from the host environment."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    return {var: val for var in _API_KEY_VARS if (val := os.environ.get(var, ""))}


def build_run_command(
    *,
    instruction: str,
    model: str | None = None,
    max_turns: int | None = None,
    timeout: int | None = None,
    feature_flags: dict[str, str | bool | float | None] | None = None,
) -> str:
    """Build the ``pydantic-deep run`` shell command."""
    parts = [
        f'export PATH="{_VENV_PATH}/bin:$HOME/.local/bin:$PATH";',
        "pydantic-deep run",
        shlex.quote(instruction),
        "--json",
    ]

    if model:
        parts.append(f"--model {shlex.quote(model)}")
    if max_turns is not None:
        parts.append(f"--max-turns {max_turns}")
    if timeout is not None:
        parts.append(f"--timeout {timeout}")

    # Append feature flags
    if feature_flags:
        for key, value in feature_flags.items():
            if value is None:
                continue
            parts.append(_format_flag(key, value))

    parts.append("2>&1 | tee /logs/agent/pydantic-deep.txt")
    return " ".join(parts)


def _format_flag(key: str, value: str | bool | float) -> str:
    """Format a feature flag for the CLI command."""
    # Boolean flags: --flag / --no-flag
    bool_flags = {
        "web_search",
        "web_fetch",
        "todo",
        "subagents",
        "skills",
        "plan",
        "memory",
        "teams",
        "context",
    }
    if key in bool_flags:
        is_true = str(value).lower() in ("true", "1", "yes")
        flag_name = key.replace("_", "-")
        return f"--{flag_name}" if is_true else f"--no-{flag_name}"

    # Value flags: --key value
    if key == "thinking":
        return f"--thinking {value}"
    if key == "temperature":
        return f"--temperature {value}"

    return ""  # pragma: no cover


def parse_json_output(text: str) -> dict[str, Any] | None:
    """Try to extract JSON output from agent stdout.

    The agent prints JSON when run with ``--json``. The JSON block
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

uv pip install "pydantic-deep[cli] @ git+{_GIT_REPO}@{git_ref}"

# Verify installation
pydantic-deep --version
mkdir -p /logs/agent
"""
