"""Harbor agent adapter for pydantic-deep CLI.

Implements ``BaseInstalledAgent`` so that pydantic-deep can be evaluated on
Terminal-Bench via Harbor:

    harbor run -d terminal-bench@2.0 \\
        --agent-import-path harbor_agent.pydantic_deep_agent:PydanticDeep \\
        -m openai/gpt-4.1

Supported model formats (maps to pydantic-ai provider:model):

    -m openai/gpt-4.1                → openai:gpt-4.1
    -m anthropic/claude-sonnet-4      → anthropic:claude-sonnet-4
    -m openrouter/openai/gpt-5.2     → openrouter:openai/gpt-5.2
    -m groq/llama-3.3-70b            → groq:llama-3.3-70b
    -m google-gla/gemini-2.0-flash   → google-gla:gemini-2.0-flash
    -m bedrock/anthropic.claude-v2    → bedrock:anthropic.claude-v2
    -m ollama/llama3                  → ollama:llama3
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import Any

from harbor.agents.installed.base import BaseInstalledAgent, ExecInput
from harbor.models.agent.context import AgentContext


class PydanticDeep(BaseInstalledAgent):
    """pydantic-deep CLI agent for Harbor / Terminal-Bench evaluation."""

    SUPPORTS_ATIF: bool = False

    def __init__(
        self,
        max_turns: int | None = None,
        *args: Any,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        self._max_turns = max_turns

    @staticmethod
    def name() -> str:
        return "pydantic-deep"

    def version(self) -> str | None:
        return self._version

    @property
    def _install_agent_template_path(self) -> Path:
        return Path(__file__).parent / "install-pydantic-deep.sh.j2"

    def create_run_agent_commands(self, instruction: str) -> list[ExecInput]:
        escaped_instruction = shlex.quote(instruction)

        pai_model = self._convert_model_name(self.model_name) if self.model_name else None
        provider = pai_model.split(":")[0] if pai_model else "openai"
        env = self._build_env(provider)
        model_flag = f"--model {pai_model}" if pai_model else ""

        return [
            ExecInput(
                command=(
                    'export PATH="/opt/pydantic-deep-venv/bin:$HOME/.local/bin:$PATH"; '
                    f"pydantic-deep run {escaped_instruction} "
                    f"{model_flag} "
                    f"--temperature 0 "
                    f"2>&1 | tee /logs/agent/pydantic-deep.txt"
                ),
                env={k: v for k, v in env.items() if v},
                cwd="/app",
            ),
        ]

    def populate_context_post_run(self, context: AgentContext) -> None:
        """Parse cost/token info from agent output."""
        log_path = self.logs_dir / "command-0" / "stdout.txt"
        if not log_path.exists():
            return

        text = log_path.read_text()
        cost = _parse_cost(text)
        if cost is not None:
            context.cost_usd = cost

    @staticmethod
    def _build_env(provider: str) -> dict[str, str]:
        """Collect env vars needed for the given provider.

        Uses the provider registry from cli/providers.py at runtime (inside
        the Docker container). Falls back to a minimal set when the CLI
        package isn't importable (e.g. in the Harbor host process).
        """
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass

        try:
            from cli.providers import PROVIDERS

            info = PROVIDERS.get(provider)
            var_names: list[str] = []
            if info:
                var_names.extend(info.env_vars)
                if info.optional_env_vars:
                    var_names.extend(info.optional_env_vars)
        except ImportError:
            var_names = [
                "OPENAI_API_KEY",
                "OPENAI_BASE_URL",
                "OPENROUTER_API_KEY",
                "ANTHROPIC_API_KEY",
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
            ]

        env: dict[str, str] = {}
        for var in var_names:
            val = os.environ.get(var, "")
            if val:
                env[var] = val
        return env

    @staticmethod
    def _convert_model_name(harbor_name: str) -> str:
        """Convert Harbor ``provider/model`` to pydantic-ai ``provider:model``.

        If the input already contains a colon it's assumed to be in
        pydantic-ai format and is returned as-is.

        Examples::

            openai/gpt-4.1                     → openai:gpt-4.1
            openrouter/openai/gpt-5.2-codex    → openrouter:openai/gpt-5.2-codex
            openrouter:openai/gpt-5.2-codex    → openrouter:openai/gpt-5.2-codex  (unchanged)
            gpt-4.1                            → gpt-4.1  (no provider prefix)
        """
        if ":" in harbor_name:
            return harbor_name
        if "/" in harbor_name:
            provider, model = harbor_name.split("/", 1)
            return f"{provider}:{model}"
        return harbor_name


def _parse_cost(text: str) -> float | None:
    """Try to extract USD cost from agent output."""
    match = re.search(r"Cost:\s*\$([0-9]+\.?[0-9]*)", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None
