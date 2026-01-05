"""Recording infrastructure for deterministic testing."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic_deep.testing.types import (
    FixtureFile,
    RecordedInteraction,
    RecordedRequest,
    RecordedResponse,
)


class Recorder:
    """Records LLM interactions to fixture files."""

    def __init__(self, fixture_file: str | Path, model: str = "") -> None:
        """Initialize recorder.

        Args:
            fixture_file: Path to fixture file (will be created if doesn't exist).
            model: Model name for metadata.
        """
        self.fixture_file = Path(fixture_file)
        self.model = model
        self.interactions: list[RecordedInteraction] = []
        self.interaction_counter = 0

        # Create parent directory if needed
        self.fixture_file.parent.mkdir(parents=True, exist_ok=True)

    def _hash_request(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> str:
        """Generate hash of request for matching during replay.

        Args:
            messages: Request messages.
            tools: Request tools.

        Returns:
            SHA256 hash of request.
        """
        # Create canonical representation
        canonical = {
            "messages": messages,
            "tools": tools or [],
        }

        # Hash it
        content = json.dumps(canonical, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def record_request(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> RecordedRequest:
        """Record an LLM request.

        Args:
            messages: Request messages.
            tools: Request tools.
            tool_choice: Tool choice setting.
            temperature: Temperature setting.
            max_tokens: Max tokens setting.

        Returns:
            Recorded request.
        """
        request = RecordedRequest(
            timestamp=datetime.now().isoformat(),
            model=self.model,
            messages_count=len(messages),
            tools_count=len(tools) if tools else 0,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
            request_hash=self._hash_request(messages, tools),
        )

        return request

    def record_response(
        self,
        content: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        finish_reason: str = "stop",
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        raw_response: dict[str, Any] | None = None,
    ) -> RecordedResponse:
        """Record an LLM response.

        Args:
            content: Response content.
            tool_calls: Tool calls made.
            finish_reason: Finish reason.
            input_tokens: Input tokens used.
            output_tokens: Output tokens used.
            total_tokens: Total tokens used.
            raw_response: Raw response data.

        Returns:
            Recorded response.
        """
        response = RecordedResponse(
            timestamp=datetime.now().isoformat(),
            model=self.model,
            finish_reason=finish_reason,
            content=content,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            raw_response=raw_response or {},
        )

        return response

    def record_interaction(
        self,
        request: RecordedRequest,
        response: RecordedResponse,
        duration_seconds: float,
    ) -> None:
        """Record a complete request-response interaction.

        Args:
            request: Recorded request.
            response: Recorded response.
            duration_seconds: Duration of interaction.
        """
        interaction = RecordedInteraction(
            request=request,
            response=response,
            interaction_id=self.interaction_counter,
            duration_seconds=duration_seconds,
        )

        self.interactions.append(interaction)
        self.interaction_counter += 1

    def save(self, description: str = "") -> None:
        """Save recorded interactions to fixture file.

        Args:
            description: Optional description of the fixture.
        """
        # Calculate statistics
        total_tokens = sum(i.response.total_tokens or 0 for i in self.interactions)

        # Create fixture
        fixture = FixtureFile(
            version="1.0",
            created_at=datetime.now().isoformat(),
            model=self.model,
            description=description,
            interactions=self.interactions,
            total_interactions=len(self.interactions),
            total_tokens=total_tokens,
            total_cost_usd=0.0,  # Could calculate based on model pricing
        )

        # Convert to dict for JSON serialization
        fixture_dict = {
            "version": fixture.version,
            "created_at": fixture.created_at,
            "model": fixture.model,
            "description": fixture.description,
            "total_interactions": fixture.total_interactions,
            "total_tokens": fixture.total_tokens,
            "total_cost_usd": fixture.total_cost_usd,
            "interactions": [
                {
                    "interaction_id": i.interaction_id,
                    "duration_seconds": i.duration_seconds,
                    "request": {
                        "timestamp": i.request.timestamp,
                        "model": i.request.model,
                        "messages_count": i.request.messages_count,
                        "tools_count": i.request.tools_count,
                        "messages": i.request.messages,
                        "tools": i.request.tools,
                        "tool_choice": i.request.tool_choice,
                        "temperature": i.request.temperature,
                        "max_tokens": i.request.max_tokens,
                        "request_hash": i.request.request_hash,
                    },
                    "response": {
                        "timestamp": i.response.timestamp,
                        "model": i.response.model,
                        "finish_reason": i.response.finish_reason,
                        "content": i.response.content,
                        "tool_calls": i.response.tool_calls,
                        "input_tokens": i.response.input_tokens,
                        "output_tokens": i.response.output_tokens,
                        "total_tokens": i.response.total_tokens,
                        "raw_response": i.response.raw_response,
                    },
                }
                for i in self.interactions
            ],
        }

        # Write to file
        with open(self.fixture_file, "w") as f:
            json.dump(fixture_dict, f, indent=2)

        print(f"✓ Saved {len(self.interactions)} interactions to {self.fixture_file}")
