"""Agent-facing checkpointing: the auto-checkpoint capability and the tools."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ModelMessage, ModelRequest, ToolCallPart, ToolReturnPart
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import FunctionToolset

from pydantic_deep.features.checkpointing.store import (
    Checkpoint,
    CheckpointStore,
    RewindRequested,
    _make_checkpoint,
    _save_and_prune,
)

CheckpointFrequency = Literal["every_turn", "every_tool", "manual_only"]
"""When `CheckpointMiddleware` auto-saves: per model request, per tool call, or never."""


@dataclass
class CheckpointMiddleware(AbstractCapability[Any]):
    """Capability that auto-saves conversation checkpoints.

    Uses `before_model_request` (for `every_turn` frequency) and
    `after_tool_execute` (for `every_tool` frequency) hooks to
    automatically snapshot the conversation.

    Per-run state isolation via `for_run()` ensures concurrent
    agent runs don't share turn counters.

    Args:
        store: Fallback checkpoint store (used if deps has no store).
        frequency: When to auto-checkpoint:
            `"every_turn"` - before each model request,
            `"every_tool"` - after each tool call,
            `"manual_only"` - no auto-checkpoints.
        max_checkpoints: Maximum number of checkpoints to keep.
    """

    store: CheckpointStore | None = None
    frequency: CheckpointFrequency = "every_tool"
    max_checkpoints: int = 20
    _turn_counter: int = field(default=0, init=False, repr=False)

    async def for_run(self, ctx: RunContext[Any]) -> CheckpointMiddleware:
        """Return a fresh instance with isolated per-run state."""
        return replace(self)

    def _resolve_store(self, deps: Any) -> CheckpointStore | None:
        """Get checkpoint store from deps or fallback."""
        dep_store = getattr(deps, "checkpoint_store", None)
        return dep_store or self.store

    async def before_model_request(
        self,
        ctx: RunContext[Any],
        request_context: Any,
    ) -> Any:
        """Track messages and optionally auto-checkpoint before model calls."""
        messages: list[ModelMessage] = request_context.messages
        self._turn_counter += 1

        if self.frequency == "every_turn":
            store = self._resolve_store(ctx.deps)
            if store is not None:
                cp = _make_checkpoint(
                    label=f"turn-{self._turn_counter}",
                    turn=self._turn_counter,
                    messages=messages,
                )
                await _save_and_prune(store, cp, self.max_checkpoints)

        return request_context

    async def after_tool_execute(
        self,
        ctx: RunContext[Any],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        result: Any,
    ) -> Any:
        """Auto-checkpoint after tool calls (when frequency is every_tool).

        Snapshots `ctx.messages` (the live history, which already contains
        the `ModelResponse` with this tool's `ToolCallPart`) plus a
        `ToolReturnPart` carrying the result, so rewinding to a `tool-*`
        checkpoint restores a state that actually includes the tool call and
        its result.
        """
        if self.frequency == "every_tool":
            store = self._resolve_store(ctx.deps)
            if store is not None:
                messages: list[ModelMessage] = list(ctx.messages)
                messages.append(
                    ModelRequest(
                        parts=[
                            ToolReturnPart(
                                tool_name=call.tool_name,
                                content=result,
                                tool_call_id=call.tool_call_id,
                            )
                        ]
                    )
                )
                cp = _make_checkpoint(
                    label=f"tool-{self._turn_counter}-{call.tool_name}",
                    turn=self._turn_counter,
                    messages=messages,
                    metadata={"last_tool": call.tool_name},
                )
                await _save_and_prune(store, cp, self.max_checkpoints)

        return result


SAVE_CHECKPOINT_DESCRIPTION = """\
Save a named checkpoint of the current conversation state.

Labels the most recent auto-checkpoint with the given name. \
Use this before risky operations (major refactors, destructive changes) \
so you can rewind later if things go wrong."""

LIST_CHECKPOINTS_DESCRIPTION = """\
List all saved checkpoints with their labels and metadata.

Use this to see available restore points before deciding to rewind."""

REWIND_TO_DESCRIPTION = """\
Rewind the conversation to a previously saved checkpoint.

This restores the conversation state to the checkpoint and discards \
all messages after it. Use this when the current approach isn't working \
and you want to try a different strategy from a known good state."""


class CheckpointToolset(FunctionToolset[Any]):
    """Toolset giving the agent manual checkpoint controls.

    Tools:
        - `save_checkpoint`: Label the most recent auto-checkpoint
        - `list_checkpoints`: Show all saved checkpoints
        - `rewind_to`: Rewind conversation to a checkpoint (raises RewindRequested)
    """

    def __init__(
        self,
        *,
        store: CheckpointStore | None = None,
        id: str = "deep-checkpoints",
        descriptions: dict[str, str] | None = None,
    ) -> None:
        """Initialize the checkpoint toolset.

        Args:
            store: Fallback checkpoint store (used if deps has no store).
            id: Toolset identifier.
            descriptions: Optional mapping of tool name to custom description.
                Supported keys: `save_checkpoint`, `list_checkpoints`,
                `rewind_to`. Any key not present falls back to the built-in
                description constant.
        """
        super().__init__(id=id)
        self._fallback_store = store
        self._descs = descriptions or {}

        @self.tool(description=self._descs.get("save_checkpoint", SAVE_CHECKPOINT_DESCRIPTION))
        async def save_checkpoint(ctx: RunContext[Any], label: str) -> str:
            """Save a named checkpoint.

            Args:
                label: A descriptive name for the checkpoint (e.g. "before-refactor").
            """
            s = _resolve_toolset_store(ctx, self._fallback_store)
            if s is None:
                return "Checkpointing is not enabled."

            all_cps = await s.list_all()
            if not all_cps:
                return "No checkpoint available to label yet. Try again after a tool call."

            latest = all_cps[-1]
            # Create a new checkpoint with the user's label but same data
            labeled = Checkpoint(
                id=latest.id,
                label=label,
                turn=latest.turn,
                messages=latest.messages,
                message_count=latest.message_count,
                created_at=latest.created_at,
                metadata=latest.metadata,
            )
            await s.save(labeled)
            return (
                f"Checkpoint saved: '{label}'"
                f" (turn {labeled.turn},"
                f" {labeled.message_count} messages)"
            )

        @self.tool(description=self._descs.get("list_checkpoints", LIST_CHECKPOINTS_DESCRIPTION))
        async def list_checkpoints(ctx: RunContext[Any]) -> str:
            """List all saved checkpoints."""
            s = _resolve_toolset_store(ctx, self._fallback_store)
            if s is None:
                return "Checkpointing is not enabled."

            all_cps = await s.list_all()
            if not all_cps:
                return "No checkpoints saved."

            lines = ["Saved checkpoints:"]
            for cp in all_cps:
                tool_info = ""
                if cp.metadata.get("last_tool"):
                    tool_info = f", last tool: {cp.metadata['last_tool']}"
                lines.append(
                    f"- **{cp.label}** (id: `{cp.id}`, turn {cp.turn}, "
                    f"{cp.message_count} messages{tool_info})"
                )
            return "\n".join(lines)

        @self.tool(description=self._descs.get("rewind_to", REWIND_TO_DESCRIPTION))
        async def rewind_to(ctx: RunContext[Any], checkpoint_id: str) -> str:
            """Rewind to a previously saved checkpoint.

            Args:
                checkpoint_id: The ID of the checkpoint to rewind to.
            """
            s = _resolve_toolset_store(ctx, self._fallback_store)
            if s is None:
                return "Checkpointing is not enabled."

            checkpoint = await s.get(checkpoint_id)
            if checkpoint is None:
                return (
                    f"Checkpoint '{checkpoint_id}' not found."
                    " Use list_checkpoints to see available."
                )

            raise RewindRequested(
                checkpoint_id=checkpoint.id,
                label=checkpoint.label,
                messages=checkpoint.messages,
            )


def _resolve_toolset_store(
    ctx: RunContext[Any],
    fallback: CheckpointStore | None,
) -> CheckpointStore | None:
    """Resolve checkpoint store from ctx.deps or fallback."""
    store = getattr(ctx.deps, "checkpoint_store", None)
    return store or fallback
