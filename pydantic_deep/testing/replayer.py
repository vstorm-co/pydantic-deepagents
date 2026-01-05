"""Replay infrastructure for deterministic testing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic_deep.testing.types import (
    FixtureValidationError,
    RecordedInteraction,
    RecordedRequest,
    RecordedResponse,
    ReplayMismatchError,
)


class Replayer:
    """Replays LLM interactions from fixture files."""

    def __init__(self, fixture_file: str | Path, strict: bool = True) -> None:
        """Initialize replayer.

        Args:
            fixture_file: Path to fixture file.
            strict: If True, raise on request mismatch. If False, warn and use best match.
        """
        self.fixture_file = Path(fixture_file)
        self.strict = strict
        self.interactions: list[RecordedInteraction] = []
        self.current_index = 0

        # Load fixture
        self._load_fixture()

    def _load_fixture(self) -> None:
        """Load fixture file."""
        if not self.fixture_file.exists():  # pragma: no branch
            raise FixtureValidationError(f"Fixture file not found: {self.fixture_file}")

        with open(self.fixture_file) as f:
            fixture_dict = json.load(f)

        # Validate version
        version = fixture_dict.get("version", "unknown")
        if version != "1.0":
            raise FixtureValidationError(f"Unsupported fixture version: {version} (expected 1.0)")

        # Load interactions
        for interaction_dict in fixture_dict["interactions"]:
            request = RecordedRequest(
                timestamp=interaction_dict["request"]["timestamp"],
                model=interaction_dict["request"]["model"],
                messages_count=interaction_dict["request"]["messages_count"],
                tools_count=interaction_dict["request"]["tools_count"],
                messages=interaction_dict["request"]["messages"],
                tools=interaction_dict["request"].get("tools"),
                tool_choice=interaction_dict["request"].get("tool_choice"),
                temperature=interaction_dict["request"].get("temperature"),
                max_tokens=interaction_dict["request"].get("max_tokens"),
                request_hash=interaction_dict["request"]["request_hash"],
            )

            response = RecordedResponse(
                timestamp=interaction_dict["response"]["timestamp"],
                model=interaction_dict["response"]["model"],
                finish_reason=interaction_dict["response"]["finish_reason"],
                content=interaction_dict["response"].get("content"),
                tool_calls=interaction_dict["response"].get("tool_calls"),
                input_tokens=interaction_dict["response"].get("input_tokens"),
                output_tokens=interaction_dict["response"].get("output_tokens"),
                total_tokens=interaction_dict["response"].get("total_tokens"),
                raw_response=interaction_dict["response"].get("raw_response", {}),
            )

            interaction = RecordedInteraction(
                request=request,
                response=response,
                interaction_id=interaction_dict["interaction_id"],
                duration_seconds=interaction_dict["duration_seconds"],
            )

            self.interactions.append(interaction)

        print(f"✓ Loaded {len(self.interactions)} interactions from {self.fixture_file}")

    def _hash_request(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> str:
        """Generate hash of request for matching.

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

    def replay(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> RecordedResponse:
        """Replay response for a given request.

        Args:
            messages: Request messages.
            tools: Request tools.

        Returns:
            Recorded response.

        Raises:
            ReplayMismatchError: If request doesn't match recorded request.
        """
        if self.current_index >= len(self.interactions):
            count = len(self.interactions)
            msg = f"No more interactions available (exhausted {count} recorded interactions)"
            raise ReplayMismatchError(msg)

        # Get current interaction
        interaction = self.interactions[self.current_index]

        # Compute request hash
        request_hash = self._hash_request(messages, tools)

        # Check if request matches
        if request_hash != interaction.request.request_hash:
            if self.strict:
                raise ReplayMismatchError(
                    f"Request mismatch at interaction {self.current_index}:\n"
                    f"  Expected hash: {interaction.request.request_hash}\n"
                    f"  Actual hash: {request_hash}\n"
                    f"  Expected {interaction.request.messages_count} messages, "
                    f"{interaction.request.tools_count} tools\n"
                    f"  Got {len(messages)} messages, {len(tools) if tools else 0} tools"
                )
            else:
                idx = self.current_index
                msg = f"Request mismatch at interaction {idx}, using recorded response anyway"
                print(f"⚠️  Warning: {msg}")

        # Advance index
        self.current_index += 1

        # Return recorded response
        return interaction.response

    def reset(self) -> None:
        """Reset replay index to beginning."""
        self.current_index = 0

    def get_stats(self) -> dict[str, Any]:
        """Get replay statistics.

        Returns:
            Dictionary with replay stats.
        """
        return {
            "total_interactions": len(self.interactions),
            "replayed": self.current_index,
            "remaining": len(self.interactions) - self.current_index,
        }
