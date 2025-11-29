"""Summarization history processor for managing conversation context."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

if TYPE_CHECKING:
    pass


TokenCounter = Callable[[Sequence[ModelMessage]], int]

DEFAULT_SUMMARY_PROMPT = (
    "<role>\n"
    "Context Extraction Assistant\n"
    "</role>\n\n"
    "<primary_objective>\n"
    "Extract the most relevant context from the conversation history below.\n"
    "</primary_objective>\n\n"
    "<objective_information>\n"
    "You're nearing the token limit and must extract key information. "
    "This context will overwrite the conversation history, so include only "
    "the most important information.\n"
    "</objective_information>\n\n"
    "<instructions>\n"
    "The conversation history will be replaced with your extracted context. "
    "Extract and record the most important context. Focus on information "
    "relevant to the overall goal. Avoid repeating completed actions.\n"
    "</instructions>\n\n"
    "Read the message history carefully. Think about what is most important "
    "to preserve. Extract only essential context.\n\n"
    "Respond ONLY with the extracted context. No additional information.\n\n"
    "<messages>\n"
    "Messages to summarize:\n"
    "{messages}\n"
    "</messages>"
)

_DEFAULT_MESSAGES_TO_KEEP = 20
_DEFAULT_TRIGGER_TOKENS = 170000
_DEFAULT_TRIM_TOKEN_LIMIT = 4000
_SEARCH_RANGE_FOR_TOOL_PAIRS = 5


ContextFraction = tuple[Literal["fraction"], float]
ContextTokens = tuple[Literal["tokens"], int]
ContextMessages = tuple[Literal["messages"], int]

ContextSize = ContextFraction | ContextTokens | ContextMessages


def _count_tokens_approximately(messages: Sequence[ModelMessage]) -> int:  # pragma: no branch
    """Approximate token count based on character length.

    This is a simple heuristic: ~4 characters per token on average.
    For production use, consider using a proper tokenizer.
    """
    total_chars = 0
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    if isinstance(part.content, str):
                        total_chars += len(part.content)
                    else:
                        # List of content parts
                        for item in part.content:
                            if isinstance(item, dict) and "text" in item:
                                total_chars += len(str(item.get("text", "")))
                elif isinstance(part, SystemPromptPart):
                    total_chars += len(part.content)
                elif isinstance(part, ToolReturnPart):
                    total_chars += len(str(part.content))
        elif isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, TextPart):
                    total_chars += len(part.content)
                elif isinstance(part, ToolCallPart):
                    total_chars += len(part.tool_name)
                    total_chars += len(str(part.args))

    return total_chars // 4


def _format_request_parts(msg: ModelRequest) -> list[str]:  # pragma: no branch
    """Format request message parts."""
    lines: list[str] = []
    for part in msg.parts:
        if isinstance(part, UserPromptPart):
            lines.extend(_format_user_prompt(part))
        elif isinstance(part, SystemPromptPart):
            lines.append(f"System: {part.content}")
        elif isinstance(part, ToolReturnPart):
            content_str = str(part.content)[:500]
            if len(str(part.content)) > 500:
                content_str += "..."
            lines.append(f"Tool [{part.tool_name}]: {content_str}")
    return lines


def _format_user_prompt(part: UserPromptPart) -> list[str]:
    """Format a user prompt part."""
    if isinstance(part.content, str):
        return [f"User: {part.content}"]
    # Handle multi-part content
    text_parts: list[str] = []
    for item in part.content:
        if isinstance(item, dict) and "text" in item:
            text_parts.append(str(item.get("text", "")))
    return [f"User: {' '.join(text_parts)}"] if text_parts else []


def _format_response_parts(msg: ModelResponse) -> list[str]:  # pragma: no branch
    """Format response message parts."""
    lines: list[str] = []
    for part in msg.parts:
        if isinstance(part, TextPart):
            lines.append(f"Assistant: {part.content}")
        elif isinstance(part, ToolCallPart):
            lines.append(f"Tool Call [{part.tool_name}]: {part.args}")
    return lines


def _format_messages_for_summary(messages: Sequence[ModelMessage]) -> str:  # pragma: no branch
    """Format messages into a readable string for summarization."""
    lines: list[str] = []

    for msg in messages:
        if isinstance(msg, ModelRequest):
            lines.extend(_format_request_parts(msg))
        elif isinstance(msg, ModelResponse):
            lines.extend(_format_response_parts(msg))

    return "\n".join(lines)


@dataclass
class SummarizationProcessor:
    """History processor that summarizes conversation when limits are reached.

    This processor monitors message token counts and automatically summarizes
    older messages when a threshold is reached, preserving recent messages
    and maintaining context continuity.

    Example:
        ```python
        from pydantic_deep import create_deep_agent
        from pydantic_deep.processors import SummarizationProcessor

        processor = SummarizationProcessor(
            model="anthropic:claude-sonnet-4-20250514",
            trigger=("tokens", 100000),
            keep=("messages", 10),
        )

        agent = create_deep_agent(
            history_processors=[processor],
        )
        ```
    """

    model: str
    """Model to use for generating summaries."""

    trigger: ContextSize | list[ContextSize] | None = None
    """Threshold(s) that trigger summarization.

    Examples:
        - ("messages", 50) - trigger when 50+ messages
        - ("tokens", 100000) - trigger when 100k+ tokens
        - ("fraction", 0.8) - trigger at 80% of max tokens (requires max_input_tokens)
    """

    keep: ContextSize = ("messages", _DEFAULT_MESSAGES_TO_KEEP)
    """How much context to keep after summarization.

    Examples:
        - ("messages", 20) - keep last 20 messages
        - ("tokens", 10000) - keep last 10k tokens worth
    """

    token_counter: TokenCounter = field(default=_count_tokens_approximately)
    """Function to count tokens in messages."""

    summary_prompt: str = DEFAULT_SUMMARY_PROMPT
    """Prompt template for generating summaries."""

    max_input_tokens: int | None = None
    """Maximum input tokens for the model (required for fraction-based triggers)."""

    trim_tokens_to_summarize: int | None = _DEFAULT_TRIM_TOKEN_LIMIT
    """Maximum tokens to include when generating summary. None to skip trimming."""

    _trigger_conditions: list[ContextSize] = field(default_factory=list, init=False)
    _summarization_agent: Agent[None, str] | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        """Validate configuration and set up trigger conditions."""
        if self.trigger is None:
            self._trigger_conditions = []
        elif isinstance(self.trigger, list):
            self._trigger_conditions = [
                self._validate_context_size(t, "trigger") for t in self.trigger
            ]
        else:
            self._trigger_conditions = [self._validate_context_size(self.trigger, "trigger")]

        self.keep = self._validate_context_size(self.keep, "keep")

        # Validate that fraction-based triggers have max_input_tokens
        requires_max_tokens = any(t[0] == "fraction" for t in self._trigger_conditions)
        if self.keep[0] == "fraction":
            requires_max_tokens = True

        if requires_max_tokens and self.max_input_tokens is None:
            raise ValueError(
                "max_input_tokens is required when using fraction-based triggers or keep. "
                "Please provide the model's maximum input token limit."
            )

    def _validate_context_size(self, context: ContextSize, parameter_name: str) -> ContextSize:
        """Validate context configuration tuples."""
        kind, value = context
        if kind == "fraction":
            if not 0 < value <= 1:
                raise ValueError(
                    f"Fractional {parameter_name} values must be between 0 and 1, got {value}."
                )
        elif kind in {"tokens", "messages"}:
            if value <= 0:
                raise ValueError(
                    f"{parameter_name} thresholds must be greater than 0, got {value}."
                )
        else:
            raise ValueError(f"Unsupported context size type {kind} for {parameter_name}.")
        return context

    def _should_summarize(self, messages: list[ModelMessage], total_tokens: int) -> bool:
        """Determine whether summarization should run."""
        if not self._trigger_conditions:
            return False

        for kind, value in self._trigger_conditions:
            if kind == "messages" and len(messages) >= value:
                return True
            if kind == "tokens" and total_tokens >= value:
                return True
            if kind == "fraction" and self.max_input_tokens:
                threshold = int(self.max_input_tokens * value)
                if total_tokens >= threshold:
                    return True
        return False

    def _determine_cutoff_index(self, messages: list[ModelMessage]) -> int:
        """Choose cutoff index respecting retention configuration."""
        kind, value = self.keep

        if kind == "messages":
            return self._find_safe_cutoff(messages, int(value))
        elif kind == "tokens":
            return self._find_token_based_cutoff(messages, int(value))
        elif kind == "fraction" and self.max_input_tokens:
            target_tokens = int(self.max_input_tokens * value)
            return self._find_token_based_cutoff(messages, target_tokens)

        return self._find_safe_cutoff(messages, _DEFAULT_MESSAGES_TO_KEEP)  # pragma: no cover

    def _find_token_based_cutoff(
        self, messages: list[ModelMessage], target_token_count: int
    ) -> int:
        """Find cutoff index based on target token retention."""
        if not messages or self.token_counter(messages) <= target_token_count:
            return 0

        # Binary search for the cutoff point
        left, right = 0, len(messages)
        cutoff_candidate = len(messages)

        for _ in range(len(messages).bit_length() + 1):
            if left >= right:
                break

            mid = (left + right) // 2
            if self.token_counter(messages[mid:]) <= target_token_count:
                cutoff_candidate = mid
                right = mid
            else:
                left = mid + 1

        if cutoff_candidate >= len(messages):  # pragma: no cover
            cutoff_candidate = max(0, len(messages) - 1)

        # Find a safe cutoff point (not splitting tool call pairs)
        for i in range(cutoff_candidate, -1, -1):  # pragma: no branch
            if self._is_safe_cutoff_point(messages, i):
                return i

        return 0  # pragma: no cover

    def _find_safe_cutoff(self, messages: list[ModelMessage], messages_to_keep: int) -> int:
        """Find safe cutoff point that preserves AI/Tool message pairs."""
        if len(messages) <= messages_to_keep:
            return 0

        target_cutoff = len(messages) - messages_to_keep

        for i in range(target_cutoff, -1, -1):
            if self._is_safe_cutoff_point(messages, i):
                return i

        return 0  # pragma: no cover

    def _is_safe_cutoff_point(self, messages: list[ModelMessage], cutoff_index: int) -> bool:
        """Check if cutting at index would separate AI/Tool message pairs."""
        if cutoff_index >= len(messages):
            return True

        search_start = max(0, cutoff_index - _SEARCH_RANGE_FOR_TOOL_PAIRS)
        search_end = min(len(messages), cutoff_index + _SEARCH_RANGE_FOR_TOOL_PAIRS)

        for i in range(search_start, search_end):
            msg = messages[i]
            if not isinstance(msg, ModelResponse):
                continue

            tool_call_ids: set[str] = set()
            for part in msg.parts:
                if isinstance(part, ToolCallPart) and part.tool_call_id:
                    tool_call_ids.add(part.tool_call_id)

            if not tool_call_ids:
                continue

            # Check if cutoff separates this tool call from its response
            for j in range(i + 1, len(messages)):
                check_msg = messages[j]
                if isinstance(check_msg, ModelRequest):
                    for part in check_msg.parts:
                        if isinstance(part, ToolReturnPart) and part.tool_call_id in tool_call_ids:
                            tool_before_cutoff = i < cutoff_index
                            response_before_cutoff = j < cutoff_index
                            if tool_before_cutoff != response_before_cutoff:
                                return False

        return True

    def _get_summarization_agent(self) -> Agent[None, str]:  # pragma: no cover
        """Get or create the summarization agent."""
        if self._summarization_agent is None:
            self._summarization_agent = Agent(
                self.model,
                instructions=(
                    "You are a context summarization assistant. "
                    "Extract the most important information from conversations."
                ),
            )
        return self._summarization_agent

    async def _create_summary(
        self, messages_to_summarize: list[ModelMessage]
    ) -> str:  # pragma: no cover
        """Generate summary for the given messages."""
        if not messages_to_summarize:
            return "No previous conversation history."

        formatted = _format_messages_for_summary(messages_to_summarize)

        # Trim if needed
        if self.trim_tokens_to_summarize and len(formatted) > self.trim_tokens_to_summarize * 4:
            formatted = formatted[-(self.trim_tokens_to_summarize * 4) :]

        prompt = self.summary_prompt.format(messages=formatted)

        try:
            agent = self._get_summarization_agent()
            result = await agent.run(prompt)
            return result.output.strip()
        except Exception as e:
            return f"Error generating summary: {e!s}"

    async def __call__(self, messages: list[ModelMessage]) -> list[ModelMessage]:
        """Process messages and summarize if needed.

        This is the main entry point called by pydantic-ai's history processor mechanism.
        """
        total_tokens = self.token_counter(messages)

        if not self._should_summarize(messages, total_tokens):
            return messages

        cutoff_index = self._determine_cutoff_index(messages)

        if cutoff_index <= 0:
            return messages

        # The following code path requires an LLM call, so is covered by integration tests
        messages_to_summarize = messages[:cutoff_index]  # pragma: no cover
        preserved_messages = messages[cutoff_index:]  # pragma: no cover

        summary = await self._create_summary(messages_to_summarize)  # pragma: no cover

        # Create a summary message
        summary_message = ModelRequest(  # pragma: no cover
            parts=[
                SystemPromptPart(content=f"Summary of previous conversation:\n\n{summary}"),
            ]
        )

        return [summary_message, *preserved_messages]  # pragma: no cover


def create_summarization_processor(
    model: str = "anthropic:claude-sonnet-4-20250514",
    trigger: ContextSize | list[ContextSize] | None = ("tokens", _DEFAULT_TRIGGER_TOKENS),
    keep: ContextSize = ("messages", _DEFAULT_MESSAGES_TO_KEEP),
    max_input_tokens: int | None = None,
    token_counter: TokenCounter | None = None,
    summary_prompt: str | None = None,
) -> SummarizationProcessor:
    """Create a summarization history processor.

    Args:
        model: Model to use for generating summaries.
        trigger: When to trigger summarization. Can be:
            - ("messages", N) - trigger when N+ messages
            - ("tokens", N) - trigger when N+ tokens
            - ("fraction", F) - trigger at F fraction of max_input_tokens
            - List of tuples to trigger on any condition
        keep: How much context to keep after summarization.
        max_input_tokens: Maximum input tokens (required for fraction-based triggers).
        token_counter: Custom token counting function.
        summary_prompt: Custom prompt for summarization.

    Returns:
        Configured SummarizationProcessor.

    Example:
        ```python
        from pydantic_deep import create_deep_agent
        from pydantic_deep.processors import create_summarization_processor

        processor = create_summarization_processor(
            trigger=("messages", 50),
            keep=("messages", 10),
        )

        agent = create_deep_agent(
            history_processors=[processor],
        )
        ```
    """
    kwargs: dict = {
        "model": model,
        "trigger": trigger,
        "keep": keep,
    }

    if max_input_tokens is not None:
        kwargs["max_input_tokens"] = max_input_tokens

    if token_counter is not None:
        kwargs["token_counter"] = token_counter

    if summary_prompt is not None:
        kwargs["summary_prompt"] = summary_prompt

    return SummarizationProcessor(**kwargs)
