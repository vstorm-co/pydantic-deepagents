"""Insight synthesizer - merges insights from multiple sessions into proposed changes.

Uses a pydantic-ai Agent with structured output to synthesize session insights
and current context files into minimal, high-confidence proposed changes.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from pydantic_deep.features.improve.prompts import SYNTHESIS_PROMPT
from pydantic_deep.features.improve.types import ProposedChange, SessionInsights
from pydantic_deep.models import DEFAULT_IMPROVE_MODEL

MAX_TOOL_SEQUENCE_CHARS = 8000
"""Per-session cap on raw tool-sequence text in the synthesis prompt."""


class _SynthesisOutput(BaseModel):
    """Structured output for the synthesis agent."""

    proposed_changes: list[ProposedChange] = Field(default_factory=list)


class InsightSynthesizer:
    """Synthesizes insights from multiple sessions into proposed changes.

    Takes extracted insights from individual sessions plus the current context
    files and produces a list of proposed changes to context files.
    """

    def __init__(self, model: str = DEFAULT_IMPROVE_MODEL) -> None:
        """Initialize the synthesizer.

        Args:
            model: Model identifier for the synthesis agent.
        """
        self._model = model

    async def synthesize(
        self,
        insights: list[SessionInsights],
        current_context: dict[str, str],
        tool_sequences: dict[str, str] | None = None,
    ) -> list[ProposedChange]:
        """Merge all insights + current context into proposed changes.

        Args:
            insights: Per-session insights extracted by the extractor.
            current_context: Current context files, e.g.
                `{"SOUL.md": "...", "AGENTS.md": "...", "MEMORY.md": "..."}`.
            tool_sequences: Optional mapping of session_id to raw tool call
                sequence text. Following Meta-Harness (Lee et al., 2026):
                giving the synthesis agent raw traces enables better
                behavioral reasoning than pre-summarized insights alone.

        Returns:
            List of proposed changes with confidence scores.
        """
        if not insights:
            return []

        prompt = SYNTHESIS_PROMPT.format(
            n=len(insights),
            current_context=self._format_current_context(current_context),
            insights_json=self._format_insights_for_prompt(insights),
        )

        # Build user prompt - append raw tool sequences when available
        user_prompt = "Synthesize the insights into proposed changes."
        if tool_sequences:
            traces = self._format_tool_sequences(tool_sequences)
            if traces:
                user_prompt += (
                    "\n\n## Raw Tool Call Sequences\n\n"
                    "Below are the actual tool call sequences from sessions. "
                    "Use these to identify behavioral patterns, effective "
                    "strategies, and recurring approaches:\n\n" + traces
                )

        agent: Agent[None, _SynthesisOutput] = Agent(
            model=self._model,
            output_type=_SynthesisOutput,
            instructions=prompt,
        )

        result = await agent.run(user_prompt)
        return result.output.proposed_changes

    @staticmethod
    def _format_tool_sequences(sequences: dict[str, str]) -> str:
        """Format tool sequences for the synthesis prompt.

        Args:
            sequences: Mapping of session_id to tool sequence text.

        Returns:
            Formatted string with labeled per-session tool sequences.
        """
        parts: list[str] = []
        for session_id, sequence in sequences.items():
            if sequence.strip():
                # Cap per-session to avoid blowing context
                truncated = sequence[:MAX_TOOL_SEQUENCE_CHARS]
                if len(sequence) > MAX_TOOL_SEQUENCE_CHARS:
                    extra = len(sequence) - MAX_TOOL_SEQUENCE_CHARS
                    truncated += f"\n  ... ({extra} chars truncated)"
                parts.append(f"### Session {session_id}\n\n{truncated}")
        return "\n\n".join(parts)

    @staticmethod
    def _format_insights_for_prompt(insights: list[SessionInsights]) -> str:
        """Format insights as JSON for the synthesis prompt.

        Args:
            insights: List of session insights to format.

        Returns:
            JSON string representation of all insights.
        """
        data: list[dict[str, Any]] = [i.model_dump() for i in insights]
        return json.dumps(data, indent=2, ensure_ascii=False)

    @staticmethod
    def _format_current_context(context: dict[str, str]) -> str:
        """Format current context files for the prompt.

        Args:
            context: Mapping of filename to file content.

        Returns:
            Formatted string with each file's content in a labeled block.
        """
        if not context:
            return "(No context files exist yet.)"

        parts: list[str] = []
        for filename, content in sorted(context.items()):
            if content.strip():
                parts.append(f"### {filename}\n\n{content.strip()}")
            else:
                parts.append(f"### {filename}\n\n(empty)")
        return "\n\n".join(parts)
