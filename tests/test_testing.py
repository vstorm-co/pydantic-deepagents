"""Tests for deterministic testing infrastructure."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from pydantic_deep.testing import (
    FixtureValidationError,
    Recorder,
    RecordedRequest,
    RecordedResponse,
    Replayer,
    ReplayMismatchError,
    create_fixture,
    record_mode,
    replay_mode,
    validate_fixture,
)


class TestRecorder:
    """Tests for Recorder class."""

    def test_create_recorder(self) -> None:
        """Test creating a recorder."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_file = Path(tmpdir) / "test.json"
            recorder = Recorder(fixture_file, model="gpt-4o")

            assert recorder.fixture_file == fixture_file
            assert recorder.model == "gpt-4o"
            assert len(recorder.interactions) == 0

    def test_record_request(self) -> None:
        """Test recording a request."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = Recorder(Path(tmpdir) / "test.json", model="gpt-4o")

            messages = [{"role": "user", "content": "Hello"}]
            tools = [{"type": "function", "function": {"name": "test"}}]

            request = recorder.record_request(
                messages=messages,
                tools=tools,
                temperature=0.7,
            )

            assert isinstance(request, RecordedRequest)
            assert request.model == "gpt-4o"
            assert request.messages_count == 1
            assert request.tools_count == 1
            assert request.messages == messages
            assert request.tools == tools
            assert request.temperature == 0.7
            assert len(request.request_hash) == 16  # SHA256 truncated

    def test_record_response(self) -> None:
        """Test recording a response."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = Recorder(Path(tmpdir) / "test.json", model="gpt-4o")

            response = recorder.record_response(
                content="Hello back!",
                finish_reason="stop",
                input_tokens=10,
                output_tokens=5,
                total_tokens=15,
            )

            assert isinstance(response, RecordedResponse)
            assert response.model == "gpt-4o"
            assert response.content == "Hello back!"
            assert response.finish_reason == "stop"
            assert response.input_tokens == 10
            assert response.output_tokens == 5
            assert response.total_tokens == 15

    def test_record_interaction(self) -> None:
        """Test recording a complete interaction."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = Recorder(Path(tmpdir) / "test.json", model="gpt-4o")

            request = recorder.record_request(messages=[{"role": "user", "content": "Hello"}])
            response = recorder.record_response(content="Hello back!")

            recorder.record_interaction(request, response, duration_seconds=1.5)

            assert len(recorder.interactions) == 1
            assert recorder.interactions[0].interaction_id == 0
            assert recorder.interactions[0].duration_seconds == 1.5

    def test_save_fixture(self) -> None:
        """Test saving interactions to fixture file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_file = Path(tmpdir) / "test.json"
            recorder = Recorder(fixture_file, model="gpt-4o")

            # Record two interactions
            for i in range(2):
                request = recorder.record_request(
                    messages=[{"role": "user", "content": f"Message {i}"}]
                )
                response = recorder.record_response(
                    content=f"Response {i}",
                    total_tokens=10,
                )
                recorder.record_interaction(request, response, duration_seconds=1.0)

            # Save
            recorder.save(description="Test fixture")

            # Verify file exists and is valid JSON
            assert fixture_file.exists()

            with open(fixture_file) as f:
                fixture_dict = json.load(f)

            assert fixture_dict["version"] == "1.0"
            assert fixture_dict["model"] == "gpt-4o"
            assert fixture_dict["description"] == "Test fixture"
            assert fixture_dict["total_interactions"] == 2
            assert fixture_dict["total_tokens"] == 20
            assert len(fixture_dict["interactions"]) == 2


class TestReplayer:
    """Tests for Replayer class."""

    def test_load_fixture(self) -> None:
        """Test loading a fixture file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a fixture
            fixture_file = Path(tmpdir) / "test.json"
            recorder = Recorder(fixture_file, model="gpt-4o")

            request = recorder.record_request(messages=[{"role": "user", "content": "Hello"}])
            response = recorder.record_response(content="Hello back!")
            recorder.record_interaction(request, response, duration_seconds=1.0)
            recorder.save()

            # Load with replayer
            replayer = Replayer(fixture_file)

            assert len(replayer.interactions) == 1
            assert replayer.current_index == 0

    def test_replay_matching_request(self) -> None:
        """Test replaying a matching request."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create fixture
            fixture_file = Path(tmpdir) / "test.json"
            recorder = Recorder(fixture_file, model="gpt-4o")

            messages = [{"role": "user", "content": "Hello"}]
            request = recorder.record_request(messages=messages)
            response = recorder.record_response(content="Hello back!")
            recorder.record_interaction(request, response, duration_seconds=1.0)
            recorder.save()

            # Replay
            replayer = Replayer(fixture_file)
            replayed_response = replayer.replay(messages=messages)

            assert replayed_response.content == "Hello back!"
            assert replayer.current_index == 1

    def test_replay_mismatch_strict(self) -> None:
        """Test replay with mismatched request in strict mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create fixture
            fixture_file = Path(tmpdir) / "test.json"
            recorder = Recorder(fixture_file, model="gpt-4o")

            request = recorder.record_request(messages=[{"role": "user", "content": "Hello"}])
            response = recorder.record_response(content="Hello back!")
            recorder.record_interaction(request, response, duration_seconds=1.0)
            recorder.save()

            # Replay with different messages
            replayer = Replayer(fixture_file, strict=True)

            with pytest.raises(ReplayMismatchError) as exc_info:
                replayer.replay(messages=[{"role": "user", "content": "Different"}])

            assert "mismatch" in str(exc_info.value).lower()

    def test_replay_mismatch_permissive(self) -> None:
        """Test replay with mismatched request in permissive mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create fixture
            fixture_file = Path(tmpdir) / "test.json"
            recorder = Recorder(fixture_file, model="gpt-4o")

            request = recorder.record_request(messages=[{"role": "user", "content": "Hello"}])
            response = recorder.record_response(content="Hello back!")
            recorder.record_interaction(request, response, duration_seconds=1.0)
            recorder.save()

            # Replay with different messages in permissive mode
            replayer = Replayer(fixture_file, strict=False)

            # Should not raise, but warn
            replayed_response = replayer.replay(messages=[{"role": "user", "content": "Different"}])

            assert replayed_response.content == "Hello back!"

    def test_replay_exhausted(self) -> None:
        """Test replay when all interactions are exhausted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create fixture with 1 interaction
            fixture_file = Path(tmpdir) / "test.json"
            recorder = Recorder(fixture_file, model="gpt-4o")

            messages = [{"role": "user", "content": "Hello"}]
            request = recorder.record_request(messages=messages)
            response = recorder.record_response(content="Hello back!")
            recorder.record_interaction(request, response, duration_seconds=1.0)
            recorder.save()

            # Replay
            replayer = Replayer(fixture_file)
            replayer.replay(messages=messages)  # First replay OK

            # Try to replay again
            with pytest.raises(ReplayMismatchError) as exc_info:
                replayer.replay(messages=messages)

            assert "exhausted" in str(exc_info.value).lower()

    def test_reset_replayer(self) -> None:
        """Test resetting replayer to beginning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create fixture
            fixture_file = Path(tmpdir) / "test.json"
            recorder = Recorder(fixture_file, model="gpt-4o")

            messages = [{"role": "user", "content": "Hello"}]
            request = recorder.record_request(messages=messages)
            response = recorder.record_response(content="Hello back!")
            recorder.record_interaction(request, response, duration_seconds=1.0)
            recorder.save()

            # Replay and reset
            replayer = Replayer(fixture_file)
            replayer.replay(messages=messages)
            assert replayer.current_index == 1

            replayer.reset()
            assert replayer.current_index == 0

            # Can replay again
            replayed_response = replayer.replay(messages=messages)
            assert replayed_response.content == "Hello back!"

    def test_get_stats(self) -> None:
        """Test getting replay statistics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create fixture with 2 interactions
            fixture_file = Path(tmpdir) / "test.json"
            recorder = Recorder(fixture_file, model="gpt-4o")

            for i in range(2):
                request = recorder.record_request(
                    messages=[{"role": "user", "content": f"Message {i}"}]
                )
                response = recorder.record_response(content=f"Response {i}")
                recorder.record_interaction(request, response, duration_seconds=1.0)
            recorder.save()

            # Replay one
            replayer = Replayer(fixture_file)
            replayer.replay(messages=[{"role": "user", "content": "Message 0"}])

            stats = replayer.get_stats()
            assert stats["total_interactions"] == 2
            assert stats["replayed"] == 1
            assert stats["remaining"] == 1


class TestContextManagers:
    """Tests for context manager convenience functions."""

    def test_record_mode(self) -> None:
        """Test record_mode context manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_file = Path(tmpdir) / "test.json"

            with record_mode(fixture_file, model="gpt-4o") as recorder:
                request = recorder.record_request(messages=[{"role": "user", "content": "Hello"}])
                response = recorder.record_response(content="Hello back!")
                recorder.record_interaction(request, response, duration_seconds=1.0)

            # File should be saved
            assert fixture_file.exists()

    def test_replay_mode(self) -> None:
        """Test replay_mode context manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create fixture first
            fixture_file = Path(tmpdir) / "test.json"
            recorder = Recorder(fixture_file, model="gpt-4o")
            messages = [{"role": "user", "content": "Hello"}]
            request = recorder.record_request(messages=messages)
            response = recorder.record_response(content="Hello back!")
            recorder.record_interaction(request, response, duration_seconds=1.0)
            recorder.save()

            # Replay
            with replay_mode(fixture_file) as replayer:
                replayed_response = replayer.replay(messages=messages)
                assert replayed_response.content == "Hello back!"

    def test_get_current_recorder(self) -> None:
        """Test getting current recorder from context."""
        from pydantic_deep.testing import get_current_recorder

        # No recorder active
        assert get_current_recorder() is None

        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_file = Path(tmpdir) / "test.json"

            with record_mode(fixture_file):
                # Recorder should be active
                assert get_current_recorder() is not None

            # Recorder should be cleared
            assert get_current_recorder() is None

    def test_get_current_replayer(self) -> None:
        """Test getting current replayer from context."""
        from pydantic_deep.testing import get_current_replayer

        # No replayer active
        assert get_current_replayer() is None

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create fixture first
            fixture_file = Path(tmpdir) / "test.json"
            recorder = Recorder(fixture_file, model="gpt-4o")
            request = recorder.record_request(messages=[{"role": "user", "content": "Hello"}])
            response = recorder.record_response(content="Hello back!")
            recorder.record_interaction(request, response, duration_seconds=1.0)
            recorder.save()

            with replay_mode(fixture_file):
                # Replayer should be active
                assert get_current_replayer() is not None

            # Replayer should be cleared
            assert get_current_replayer() is None

    def test_replay_mode_unused_interactions(self) -> None:
        """Test replay_mode when not all interactions are used."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create fixture with 2 interactions
            fixture_file = Path(tmpdir) / "test.json"
            recorder = Recorder(fixture_file, model="gpt-4o")

            for i in range(2):
                request = recorder.record_request(
                    messages=[{"role": "user", "content": f"Message {i}"}]
                )
                response = recorder.record_response(content=f"Response {i}")
                recorder.record_interaction(request, response, duration_seconds=1.0)

            recorder.save()

            # Only replay one
            with replay_mode(fixture_file) as replayer:
                replayer.replay(messages=[{"role": "user", "content": "Message 0"}])
                # Don't replay the second one - should trigger warning


class TestValidation:
    """Tests for fixture validation."""

    def test_validate_fixture_success(self) -> None:
        """Test validating a valid fixture."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create valid fixture
            fixture_file = Path(tmpdir) / "test.json"
            recorder = Recorder(fixture_file, model="gpt-4o")
            request = recorder.record_request(messages=[{"role": "user", "content": "Hello"}])
            response = recorder.record_response(content="Hello back!")
            recorder.record_interaction(request, response, duration_seconds=1.0)
            recorder.save(description="Test fixture")

            # Validate
            info = validate_fixture(fixture_file)

            assert info["version"] == "1.0"
            assert info["model"] == "gpt-4o"
            assert info["total_interactions"] == 1
            assert info["description"] == "Test fixture"

    def test_validate_fixture_not_found(self) -> None:
        """Test validating non-existent fixture."""
        with pytest.raises(FixtureValidationError) as exc_info:
            validate_fixture("nonexistent.json")

        assert "not found" in str(exc_info.value).lower()

    def test_validate_fixture_invalid_version(self) -> None:
        """Test validating fixture with invalid version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create fixture with wrong version
            fixture_file = Path(tmpdir) / "test.json"
            with open(fixture_file, "w") as f:
                json.dump({"version": "2.0"}, f)

            with pytest.raises(FixtureValidationError) as exc_info:
                validate_fixture(fixture_file)

            assert "version" in str(exc_info.value).lower()

    def test_load_invalid_version(self) -> None:
        """Test loading fixture with invalid version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create fixture with wrong version
            fixture_file = Path(tmpdir) / "test.json"
            with open(fixture_file, "w") as f:
                json.dump({"version": "2.0", "interactions": []}, f)

            with pytest.raises(FixtureValidationError) as exc_info:
                Replayer(fixture_file)

            assert "version" in str(exc_info.value).lower()


class TestCreateFixture:
    """Tests for create_fixture helper."""

    def test_create_fixture(self) -> None:
        """Test creating a fixture."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_file = Path(tmpdir) / "test.json"
            recorder = create_fixture(fixture_file, model="gpt-4o", description="Test")

            assert isinstance(recorder, Recorder)
            assert recorder.fixture_file == fixture_file
            assert recorder.model == "gpt-4o"
