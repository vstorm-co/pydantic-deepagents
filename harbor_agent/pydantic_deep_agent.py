"""Harbor agent adapter for pydantic-deep CLI.

Implements ``BaseInstalledAgent`` so that pydantic-deep can be evaluated on
Terminal-Bench via Harbor:

    harbor run -d terminal-bench@2.0 \\
        --agent-import-path harbor_agent.pydantic_deep_agent:PydanticDeep \\
        -m openai/gpt-4.1
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

    # ------------------------------------------------------------------
    # Required interface
    # ------------------------------------------------------------------

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

        env = self._build_env()

        model_flag = ""
        if self.model_name:
            pai_model = self._convert_model_name(self.model_name, env)
            model_flag = f"--model {pai_model}"

        return [
            ExecInput(
                command=(
                    'export PATH="/opt/pydantic-deep-venv/bin:$HOME/.local/bin:$PATH"; '
                    f"pydantic-deep run {escaped_instruction} "
                    f"{model_flag} "
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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_env(self) -> dict[str, str]:
        """Collect API keys and configuration from environment."""
        env: dict[str, str] = {}

        for var in (
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "OPENROUTER_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "GROQ_API_KEY",
            "MISTRAL_API_KEY",
            "AZURE_OPENAI_API_KEY",
            "AZURE_OPENAI_ENDPOINT",
        ):
            val = os.environ.get(var, "")
            if val:
                env[var] = val

        return env

    @staticmethod
    def _convert_model_name(harbor_name: str, env: dict[str, str] | None = None) -> str:
        """Convert Harbor model name to pydantic-ai format.

        Harbor:      ``openai/gpt-4.1``  or ``anthropic/claude-sonnet-4-20250514``
        pydantic-ai: ``openai:gpt-4.1``  or ``anthropic:claude-sonnet-4-20250514``

        When OPENROUTER_API_KEY is set, uses ``openrouter:`` prefix with the
        full model name (e.g. ``openrouter:openai/gpt-5.2-codex``).
        """
        env = env or {}
        if env.get("OPENROUTER_API_KEY"):
            return f"openrouter:{harbor_name}"
        if "/" in harbor_name:
            provider, model = harbor_name.split("/", 1)
            return f"{provider}:{model}"
        return harbor_name


def _parse_cost(text: str) -> float | None:
    """Try to extract USD cost from agent output."""
    # pydantic-deep prints "Cost: $0.1234" to stderr (captured in tee)
    match = re.search(r"Cost:\s*\$([0-9]+\.?[0-9]*)", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None
