"""ACP server implementation for pydantic-deep.

Bridges pydantic-deep agents with the Agent Client Protocol (ACP),
enabling integration with editors like Zed.

Usage:
    ```python
    from apps.acp.server import DeepAgentACP, AgentSessionContext
    from pydantic_deep import create_deep_agent

    def build_agent(ctx: AgentSessionContext):
        return create_deep_agent(model=ctx.model)

    server = DeepAgentACP(
        agent=build_agent,
        models=[
            {"value": "anthropic:claude-opus-4-6", "name": "Claude Opus 4.6"},
            {"value": "anthropic:claude-sonnet-4-6", "name": "Claude Sonnet 4.6"},
        ],
    )
    ```

    Run via: ``python -m apps.acp``
"""

import logging
from acp import (
    Agent as ACPAgent,
    InitializeResponse,
    NewSessionResponse,
    PromptResponse,
    SetSessionConfigOptionResponse,
    SetSessionModeResponse,
    start_tool_call,
    text_block,
    tool_content,
    update_agent_message,
    update_agent_message_text,
    update_tool_call,
)
from acp.interfaces import Client
from acp.schema import (
    AgentCapabilities,
    ClientCapabilities,
    Implementation,
    PromptCapabilities,
    SessionConfigOptionSelect,
    SessionConfigSelectOption,
    TextContentBlock,
)
from collections.abc import Callable
from dataclasses import dataclass
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ToolCallPart,
)
from pydantic_ai_backends import LocalBackend
from typing import Any
from uuid import uuid4

from pydantic_deep import DeepAgentDeps

logger = logging.getLogger(__name__)

# Tool name → ACP tool kind string mapping
_TOOL_KIND_MAP: dict[str, str] = {
    "read_file": "read",
    "edit_file": "edit",
    "write_file": "edit",
    "ls": "search",
    "glob": "search",
    "grep": "search",
    "execute": "execute",
    "web_search": "search",
    "web_fetch": "fetch",
}


@dataclass(frozen=True, slots=True)
class AgentSessionContext:
    """Context for an agent session."""

    cwd: str
    mode: str = "manual"
    model: str | None = None


class DeepAgentACP(ACPAgent):
    """ACP server that bridges pydantic-deep agents with the Agent Client Protocol.

    Supports both static agents and agent factories (for model switching).
    """

    _conn: Client

    def __init__(
            self,
            agent: Agent[DeepAgentDeps, str]
                   | Callable[[AgentSessionContext], Agent[DeepAgentDeps, str]],
            *,
            models: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__()
        self._agent_factory = agent
        self._agent: Agent[DeepAgentDeps, str] | None = (
            agent if isinstance(agent, Agent) else None
        )
        self._models = models

        # Per-session state
        self._session_cwds: dict[str, str] = {}
        self._session_models: dict[str, str] = {}
        self._session_histories: dict[str, list[ModelMessage]] = {}
        self._session_deps: dict[str, DeepAgentDeps] = {}
        self._cancelled = False

    def on_connect(self, conn: Client) -> None:
        """Store the client connection."""
        self._conn = conn

    def _get_or_create_agent(
            self, session_id: str
    ) -> Agent[DeepAgentDeps, str]:
        """Get or create agent for a session."""
        if self._agent is not None:
            return self._agent

        assert callable(self._agent_factory)
        cwd = self._session_cwds.get(session_id, ".")
        model = self._session_models.get(session_id)
        ctx = AgentSessionContext(cwd=cwd, model=model)
        agent = self._agent_factory(ctx)
        return agent

    def _get_or_create_deps(self, session_id: str) -> DeepAgentDeps:
        """Get or create deps for a session."""
        if session_id not in self._session_deps:
            cwd = self._session_cwds.get(session_id, ".")
            backend = LocalBackend(root_dir=cwd)
            self._session_deps[session_id] = DeepAgentDeps(backend=backend)
        return self._session_deps[session_id]

    def _build_config_options(self, session_id: str) -> list[SessionConfigOptionSelect]:
        """Build config options (model selector)."""
        config_options: list[SessionConfigOptionSelect] = []

        if self._models:
            current_model = self._session_models.get(
                session_id, self._models[0]["value"]
            )
            model_options = [
                SessionConfigSelectOption(
                    value=m["value"],
                    name=m["name"],
                    description=m.get("description", ""),
                )
                for m in self._models
            ]
            config_options.append(
                SessionConfigOptionSelect(
                    id="model",
                    name="Model",
                    description="Select the AI model",
                    category="model",
                    type="select",
                    current_value=current_model,
                    options=model_options,
                )
            )

        return config_options

    # ── ACP Protocol Methods ─────────────────────────────────────────

    async def initialize(
            self,
            protocol_version: int,
            client_capabilities: ClientCapabilities,
            client_info: Implementation | None = None,
    ) -> InitializeResponse:
        """Handle ACP initialize request."""
        return InitializeResponse(
            protocolVersion=protocol_version,
            agentInfo=Implementation(
                name="pydantic-deep",
                version="0.3.3",
            ),
            agentCapabilities=AgentCapabilities(
                prompt_capabilities=PromptCapabilities(
                    image=True,
                ),
            ),
        )

    async def new_session(
            self,
            cwd: str,
            mcp_servers: list[Any] | None = None,
            **kwargs: Any,
    ) -> NewSessionResponse:
        """Create a new ACP session."""
        session_id = uuid4().hex[:12]
        self._session_cwds[session_id] = cwd or "."
        if self._models:
            self._session_models[session_id] = self._models[0]["value"]
        self._session_histories[session_id] = []

        return NewSessionResponse(
            sessionId=session_id,
            configOptions=self._build_config_options(session_id),
        )

    async def set_session_mode(
            self,
            mode_id: str,
            session_id: str,
            **kwargs: Any,
    ) -> SetSessionModeResponse:
        """Handle mode change."""
        return SetSessionModeResponse()

    async def set_config_option(
            self,
            config_id: str,
            session_id: str,
            value: str | bool,
            **kwargs: Any,
    ) -> SetSessionConfigOptionResponse:
        """Handle config option change (model switch)."""
        if config_id == "model" and isinstance(value, str):
            self._session_models[session_id] = value
            # Reset agent for factory pattern
            if callable(self._agent_factory):
                self._agent = None

        return SetSessionConfigOptionResponse(
            configOptions=self._build_config_options(session_id),
        )

    async def set_session_model(
            self,
            model_id: str,
            session_id: str,
            **kwargs: Any,
    ) -> Any:
        """Handle model switch."""
        self._session_models[session_id] = model_id
        if callable(self._agent_factory):
            self._agent = None
        return None

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        """Cancel current operation."""
        self._cancelled = True

    async def prompt(
            self,
            prompt: list[Any],
            session_id: str,
            message_id: str | None = None,
            **kwargs: Any,
    ) -> PromptResponse:
        """Handle a user prompt — run the agent and stream results."""
        self._cancelled = False
        session_id = session_id or "default"

        # Extract text from prompt blocks
        user_text = ""
        for block in prompt:
            if isinstance(block, TextContentBlock):
                user_text += block.text
            elif hasattr(block, "text"):
                user_text += str(block.text)

        if not user_text:
            return PromptResponse(stopReason="end_turn")

        agent = self._get_or_create_agent(session_id)
        deps = self._get_or_create_deps(session_id)
        history = self._session_histories.get(session_id, [])

        # Helper to send updates to the editor
        async def send(update: Any) -> None:
            await self._conn.session_update(
                session_id=session_id, update=update, source="pydantic-deep"
            )

        # Run agent with streaming
        from pydantic_ai._agent_graph import ModelRequestNode, CallToolsNode

        try:
            active_tool_calls: set[str] = set()

            async with agent.iter(
                    user_text,
                    deps=deps,
                    message_history=history,
            ) as run:
                async for node in run:
                    if self._cancelled:
                        break

                    # Only stream ModelRequestNode (text + tool call starts)
                    if isinstance(node, ModelRequestNode):
                        async with node.stream(run.ctx) as request_stream:
                            # Phase 1: wait for FinalResultEvent, capture tool calls
                            final_result_found = False
                            async for event in request_stream:
                                if hasattr(event, "part") and isinstance(
                                        getattr(event, "part", None), ToolCallPart
                                ):
                                    tc = event.part
                                    if tc.tool_call_id not in active_tool_calls:
                                        active_tool_calls.add(tc.tool_call_id)
                                        kind = _TOOL_KIND_MAP.get(tc.tool_name, "other")
                                        title = tc.tool_name
                                        if isinstance(tc.args, dict):
                                            if "path" in tc.args:
                                                title = f"{tc.tool_name}: {tc.args['path']}"
                                            elif "pattern" in tc.args:
                                                title = f"{tc.tool_name}: {tc.args['pattern']}"
                                            elif "command" in tc.args:
                                                cmd = str(tc.args["command"])[:60]
                                                title = f"{tc.tool_name}: {cmd}"
                                            elif "description" in tc.args:
                                                desc = str(tc.args["description"])[:60]
                                                title = f"{tc.tool_name}: {desc}"
                                        await send(
                                            start_tool_call(
                                                tool_call_id=tc.tool_call_id,
                                                title=title,
                                                kind=kind,
                                            )
                                        )
                                # FinalResultEvent means text streaming can begin
                                if type(event).__name__ == "FinalResultEvent":
                                    final_result_found = True
                                    break

                            # Phase 2: stream final text as deltas
                            if final_result_found:
                                prev_len = 0
                                async for cumulative_text in request_stream.stream_text():
                                    delta = cumulative_text[prev_len:]
                                    if delta:
                                        await send(
                                            update_agent_message_text(delta)
                                        )
                                    prev_len = len(cumulative_text)

                    # CallToolsNode: execute tools and send results
                    elif isinstance(node, CallToolsNode):
                        async with node.stream(run.ctx) as tool_stream:
                            async for event in tool_stream:
                                ename = type(event).__name__
                                if ename == "FunctionToolResultEvent":
                                    r = event.result
                                    # Truncate long results for display
                                    content_str = str(r.content) if r.content else ""
                                    if len(content_str) > 500:
                                        content_str = content_str[:500] + "..."
                                    await send(
                                        update_tool_call(
                                            tool_call_id=r.tool_call_id,
                                            status="completed",
                                            content=[
                                                tool_content(text_block(content_str))
                                            ] if content_str else None,
                                        )
                                    )

                # Save history for next turn
                self._session_histories[session_id] = list(run.result.all_messages())

        except Exception as e:
            logger.exception("Agent run failed: %s", e)
            await send(update_agent_message(text_block(f"Error: {e}")))

        return PromptResponse(stopReason="end_turn")
