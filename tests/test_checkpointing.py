"""Tests for checkpointing functionality."""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel
from pydantic_ai_backends import StateBackend

from pydantic_deep import DeepAgentDeps, create_deep_agent
from pydantic_deep.checkpointing import (
    Checkpoint,
    CheckpointManager,
    CheckpointNotFoundError,
    CheckpointValidationError,
    CheckpointVersionError,
    FileCheckpointBackend,
    StateCheckpointBackend,
    create_manual_checkpoint,
    generate_checkpoint_id,
    run_with_checkpointing,
    validate_checkpoint,
)


class TestCheckpointTypes:
    """Test Checkpoint dataclass and helper functions."""

    def test_checkpoint_creation_with_defaults(self):
        """Test checkpoint with default metadata."""
        checkpoint = Checkpoint(
            checkpoint_id="test-123",
            agent_name="test-agent",
            run_id="run-456",
            timestamp=datetime.now(),
            messages=[],
            iteration_count=0,
            total_tokens=0,
            total_cost_usd=0.0,
        )

        assert checkpoint.metadata == {}
        assert checkpoint.version == "1.0"

    def test_checkpoint_creation(self):
        """Test creating a checkpoint."""
        checkpoint = Checkpoint(
            checkpoint_id="test-123",
            agent_name="test-agent",
            run_id="run-456",
            timestamp=datetime.now(),
            messages=[],
            iteration_count=5,
            total_tokens=100,
            total_cost_usd=0.01,
        )

        assert checkpoint.checkpoint_id == "test-123"
        assert checkpoint.agent_name == "test-agent"
        assert checkpoint.run_id == "run-456"
        assert checkpoint.iteration_count == 5
        assert checkpoint.total_tokens == 100
        assert checkpoint.total_cost_usd == 0.01
        assert checkpoint.version == "1.0"

    def test_checkpoint_serialization(self):
        """Test checkpoint to_dict and from_dict."""
        original = Checkpoint(
            checkpoint_id="test-123",
            agent_name="test-agent",
            run_id="run-456",
            timestamp=datetime.now(),
            messages=[{"role": "user", "content": "Hello"}],
            iteration_count=5,
            total_tokens=100,
            total_cost_usd=0.01,
            metadata={"key": "value"},
        )

        # Serialize
        data = original.to_dict()
        assert data["checkpoint_id"] == "test-123"
        assert data["agent_name"] == "test-agent"
        assert data["iteration_count"] == 5
        assert data["metadata"]["key"] == "value"

        # Deserialize
        restored = Checkpoint.from_dict(data)
        assert restored.checkpoint_id == original.checkpoint_id
        assert restored.agent_name == original.agent_name
        assert restored.run_id == original.run_id
        assert restored.iteration_count == original.iteration_count
        assert restored.total_tokens == original.total_tokens
        assert restored.total_cost_usd == original.total_cost_usd
        assert restored.metadata == original.metadata

    def test_generate_checkpoint_id(self):
        """Test checkpoint ID generation."""
        checkpoint_id = generate_checkpoint_id("agent", "run-123", 5)

        assert "agent" in checkpoint_id
        assert "run-123" in checkpoint_id
        assert "5" in checkpoint_id
        # Should contain timestamp
        assert len(checkpoint_id) > 20

    def test_validate_checkpoint_success(self):
        """Test successful checkpoint validation."""
        checkpoint = Checkpoint(
            checkpoint_id="test-123",
            agent_name="test-agent",
            run_id="run-456",
            timestamp=datetime.now(),
            messages=[],
            iteration_count=5,
            total_tokens=100,
            total_cost_usd=0.01,
        )

        # Should not raise
        validate_checkpoint(checkpoint)

    def test_validate_checkpoint_version_mismatch(self):
        """Test validation fails on version mismatch."""
        checkpoint = Checkpoint(
            checkpoint_id="test-123",
            agent_name="test-agent",
            run_id="run-456",
            timestamp=datetime.now(),
            messages=[],
            iteration_count=5,
            total_tokens=100,
            total_cost_usd=0.01,
            version="2.0",
        )

        with pytest.raises(CheckpointVersionError):
            validate_checkpoint(checkpoint, expected_version="1.0")

    def test_validate_checkpoint_missing_id(self):
        """Test validation fails on missing checkpoint ID."""
        checkpoint = Checkpoint(
            checkpoint_id="",
            agent_name="test-agent",
            run_id="run-456",
            timestamp=datetime.now(),
            messages=[],
            iteration_count=5,
            total_tokens=100,
            total_cost_usd=0.01,
        )

        with pytest.raises(CheckpointValidationError, match="Checkpoint ID is required"):
            validate_checkpoint(checkpoint)

    def test_validate_checkpoint_negative_values(self):
        """Test validation fails on negative values."""
        # Negative iteration count
        checkpoint = Checkpoint(
            checkpoint_id="test-123",
            agent_name="test-agent",
            run_id="run-456",
            timestamp=datetime.now(),
            messages=[],
            iteration_count=-1,
            total_tokens=100,
            total_cost_usd=0.01,
        )

        with pytest.raises(CheckpointValidationError, match="Iteration count must be non-negative"):
            validate_checkpoint(checkpoint)

    def test_validate_checkpoint_negative_tokens(self):
        """Test validation fails on negative tokens."""
        checkpoint = Checkpoint(
            checkpoint_id="test-123",
            agent_name="test-agent",
            run_id="run-456",
            timestamp=datetime.now(),
            messages=[],
            iteration_count=0,
            total_tokens=-1,
            total_cost_usd=0.01,
        )

        with pytest.raises(CheckpointValidationError, match="Total tokens must be non-negative"):
            validate_checkpoint(checkpoint)

    def test_validate_checkpoint_negative_cost(self):
        """Test validation fails on negative cost."""
        checkpoint = Checkpoint(
            checkpoint_id="test-123",
            agent_name="test-agent",
            run_id="run-456",
            timestamp=datetime.now(),
            messages=[],
            iteration_count=0,
            total_tokens=100,
            total_cost_usd=-0.01,
        )

        with pytest.raises(CheckpointValidationError, match="Total cost must be non-negative"):
            validate_checkpoint(checkpoint)

    def test_validate_checkpoint_missing_agent_name(self):
        """Test validation fails on missing agent name."""
        checkpoint = Checkpoint(
            checkpoint_id="test-123",
            agent_name="",
            run_id="run-456",
            timestamp=datetime.now(),
            messages=[],
            iteration_count=0,
            total_tokens=100,
            total_cost_usd=0.01,
        )

        with pytest.raises(CheckpointValidationError, match="Agent name is required"):
            validate_checkpoint(checkpoint)

    def test_validate_checkpoint_missing_run_id(self):
        """Test validation fails on missing run ID."""
        checkpoint = Checkpoint(
            checkpoint_id="test-123",
            agent_name="test-agent",
            run_id="",
            timestamp=datetime.now(),
            messages=[],
            iteration_count=0,
            total_tokens=100,
            total_cost_usd=0.01,
        )

        with pytest.raises(CheckpointValidationError, match="Run ID is required"):
            validate_checkpoint(checkpoint)


class TestStateCheckpointBackend:
    """Test in-memory checkpoint backend."""

    async def test_save_and_load(self):
        """Test saving and loading checkpoints."""
        backend = StateCheckpointBackend()

        checkpoint = Checkpoint(
            checkpoint_id="test-123",
            agent_name="test-agent",
            run_id="run-456",
            timestamp=datetime.now(),
            messages=[],
            iteration_count=5,
            total_tokens=100,
            total_cost_usd=0.01,
        )

        # Save
        saved_id = await backend.save_checkpoint(checkpoint)
        assert saved_id == "test-123"

        # Load
        loaded = await backend.load_checkpoint("test-123")
        assert loaded.checkpoint_id == checkpoint.checkpoint_id
        assert loaded.agent_name == checkpoint.agent_name
        assert loaded.iteration_count == checkpoint.iteration_count

    async def test_load_nonexistent(self):
        """Test loading nonexistent checkpoint raises error."""
        backend = StateCheckpointBackend()

        with pytest.raises(CheckpointNotFoundError):
            await backend.load_checkpoint("nonexistent")

    async def test_list_checkpoints(self):
        """Test listing checkpoints."""
        backend = StateCheckpointBackend()

        # Create multiple checkpoints
        for i in range(5):
            checkpoint = Checkpoint(
                checkpoint_id=f"test-{i}",
                agent_name="test-agent",
                run_id="run-456",
                timestamp=datetime.now(),
                messages=[],
                iteration_count=i,
                total_tokens=100,
                total_cost_usd=0.01,
            )
            await backend.save_checkpoint(checkpoint)

        # List all
        checkpoints = await backend.list_checkpoints()
        assert len(checkpoints) == 5

    async def test_list_checkpoints_with_filters(self):
        """Test listing checkpoints with filters."""
        backend = StateCheckpointBackend()

        # Create checkpoints for different agents and runs
        for agent_num in range(2):
            for run_num in range(2):
                checkpoint = Checkpoint(
                    checkpoint_id=f"test-{agent_num}-{run_num}",
                    agent_name=f"agent-{agent_num}",
                    run_id=f"run-{run_num}",
                    timestamp=datetime.now(),
                    messages=[],
                    iteration_count=0,
                    total_tokens=100,
                    total_cost_usd=0.01,
                )
                await backend.save_checkpoint(checkpoint)

        # Filter by agent name
        checkpoints = await backend.list_checkpoints(agent_name="agent-0")
        assert len(checkpoints) == 2
        assert all(cp.agent_name == "agent-0" for cp in checkpoints)

        # Filter by run ID
        checkpoints = await backend.list_checkpoints(run_id="run-0")
        assert len(checkpoints) == 2
        assert all(cp.run_id == "run-0" for cp in checkpoints)

        # Filter by both
        checkpoints = await backend.list_checkpoints(agent_name="agent-0", run_id="run-0")
        assert len(checkpoints) == 1

    async def test_list_checkpoints_with_limit(self):
        """Test listing checkpoints with limit."""
        backend = StateCheckpointBackend()

        # Create 10 checkpoints
        for i in range(10):
            checkpoint = Checkpoint(
                checkpoint_id=f"test-{i}",
                agent_name="test-agent",
                run_id="run-456",
                timestamp=datetime.now(),
                messages=[],
                iteration_count=i,
                total_tokens=100,
                total_cost_usd=0.01,
            )
            await backend.save_checkpoint(checkpoint)

        # List with limit
        checkpoints = await backend.list_checkpoints(limit=5)
        assert len(checkpoints) == 5

    async def test_delete_checkpoint(self):
        """Test deleting checkpoints."""
        backend = StateCheckpointBackend()

        checkpoint = Checkpoint(
            checkpoint_id="test-123",
            agent_name="test-agent",
            run_id="run-456",
            timestamp=datetime.now(),
            messages=[],
            iteration_count=5,
            total_tokens=100,
            total_cost_usd=0.01,
        )

        # Save and delete
        await backend.save_checkpoint(checkpoint)
        await backend.delete_checkpoint("test-123")

        # Should not exist
        with pytest.raises(CheckpointNotFoundError):
            await backend.load_checkpoint("test-123")

    async def test_delete_nonexistent(self):
        """Test deleting nonexistent checkpoint raises error."""
        backend = StateCheckpointBackend()

        with pytest.raises(CheckpointNotFoundError):
            await backend.delete_checkpoint("nonexistent")

    async def test_cleanup_old_checkpoints(self):
        """Test cleanup of old checkpoints."""
        backend = StateCheckpointBackend()

        # Create 10 checkpoints for same run
        for i in range(10):
            checkpoint = Checkpoint(
                checkpoint_id=f"test-{i}",
                agent_name="test-agent",
                run_id="run-456",
                timestamp=datetime.now(),
                messages=[],
                iteration_count=i,
                total_tokens=100,
                total_cost_usd=0.01,
            )
            await backend.save_checkpoint(checkpoint)

        # Cleanup, keeping last 3
        deleted = await backend.cleanup_old_checkpoints("run-456", keep_last=3)
        assert deleted == 7

        # Should have 3 left
        checkpoints = await backend.list_checkpoints(run_id="run-456")
        assert len(checkpoints) == 3


class TestFileCheckpointBackend:
    """Test filesystem checkpoint backend."""

    async def test_save_and_load(self):
        """Test saving and loading checkpoints to filesystem."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = FileCheckpointBackend(tmpdir)

            checkpoint = Checkpoint(
                checkpoint_id="test-123",
                agent_name="test-agent",
                run_id="run-456",
                timestamp=datetime.now(),
                messages=[{"role": "user", "content": "Hello"}],
                iteration_count=5,
                total_tokens=100,
                total_cost_usd=0.01,
            )

            # Save
            saved_id = await backend.save_checkpoint(checkpoint)
            assert saved_id == "test-123"

            # Verify file exists
            checkpoint_file = Path(tmpdir) / "test-123.json"
            assert checkpoint_file.exists()

            # Load
            loaded = await backend.load_checkpoint("test-123")
            assert loaded.checkpoint_id == checkpoint.checkpoint_id
            assert loaded.messages == checkpoint.messages

    async def test_load_nonexistent(self):
        """Test loading nonexistent checkpoint from filesystem."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = FileCheckpointBackend(tmpdir)

            with pytest.raises(CheckpointNotFoundError):
                await backend.load_checkpoint("nonexistent")

    async def test_list_checkpoints(self):
        """Test listing checkpoints from filesystem."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = FileCheckpointBackend(tmpdir)

            # Create multiple checkpoints
            for i in range(5):
                checkpoint = Checkpoint(
                    checkpoint_id=f"test-{i}",
                    agent_name="test-agent",
                    run_id="run-456",
                    timestamp=datetime.now(),
                    messages=[],
                    iteration_count=i,
                    total_tokens=100,
                    total_cost_usd=0.01,
                )
                await backend.save_checkpoint(checkpoint)

            # List all
            checkpoints = await backend.list_checkpoints()
            assert len(checkpoints) == 5

    async def test_delete_checkpoint(self):
        """Test deleting checkpoints from filesystem."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = FileCheckpointBackend(tmpdir)

            checkpoint = Checkpoint(
                checkpoint_id="test-123",
                agent_name="test-agent",
                run_id="run-456",
                timestamp=datetime.now(),
                messages=[],
                iteration_count=5,
                total_tokens=100,
                total_cost_usd=0.01,
            )

            # Save and delete
            await backend.save_checkpoint(checkpoint)
            await backend.delete_checkpoint("test-123")

            # File should not exist
            checkpoint_file = Path(tmpdir) / "test-123.json"
            assert not checkpoint_file.exists()

    async def test_cleanup_old_checkpoints(self):
        """Test cleanup of old checkpoints from filesystem."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = FileCheckpointBackend(tmpdir)

            # Create 10 checkpoints
            for i in range(10):
                checkpoint = Checkpoint(
                    checkpoint_id=f"test-{i}",
                    agent_name="test-agent",
                    run_id="run-456",
                    timestamp=datetime.now(),
                    messages=[],
                    iteration_count=i,
                    total_tokens=100,
                    total_cost_usd=0.01,
                )
                await backend.save_checkpoint(checkpoint)

            # Cleanup, keeping last 3
            deleted = await backend.cleanup_old_checkpoints("run-456", keep_last=3)
            assert deleted == 7

            # Should have 3 files left
            json_files = list(Path(tmpdir).glob("*.json"))
            assert len(json_files) == 3


class TestCheckpointManager:
    """Test checkpoint manager."""

    async def test_create_checkpoint(self):
        """Test creating a checkpoint through manager."""
        backend = StateCheckpointBackend()
        manager = CheckpointManager(backend=backend)

        checkpoint_id = await manager.create_checkpoint(
            agent_name="test-agent",
            run_id="run-123",
            messages=[],
            iteration_count=5,
            total_tokens=100,
            total_cost_usd=0.01,
        )

        assert checkpoint_id is not None
        assert manager.last_checkpoint_id == checkpoint_id

    async def test_restore_checkpoint(self):
        """Test restoring a checkpoint."""
        backend = StateCheckpointBackend()
        manager = CheckpointManager(backend=backend)

        # Create checkpoint
        checkpoint_id = await manager.create_checkpoint(
            agent_name="test-agent",
            run_id="run-123",
            messages=[{"role": "user", "content": "Test"}],
            iteration_count=5,
        )

        # Restore
        restored = await manager.restore_checkpoint(checkpoint_id)
        assert restored.checkpoint_id == checkpoint_id
        assert restored.iteration_count == 5
        assert len(restored.messages) == 1

    async def test_get_latest_checkpoint(self):
        """Test getting the latest checkpoint."""
        backend = StateCheckpointBackend()
        manager = CheckpointManager(backend=backend)

        # No checkpoints yet
        latest = await manager.get_latest_checkpoint()
        assert latest is None

        # Create checkpoints
        await manager.create_checkpoint(
            agent_name="test-agent",
            run_id="run-123",
            messages=[],
            iteration_count=1,
        )

        await manager.create_checkpoint(
            agent_name="test-agent",
            run_id="run-123",
            messages=[],
            iteration_count=2,
        )

        # Get latest
        latest = await manager.get_latest_checkpoint(run_id="run-123")
        assert latest is not None
        assert latest.iteration_count == 2

    async def test_should_checkpoint_iteration(self):
        """Test should_checkpoint for iteration frequency."""
        backend = StateCheckpointBackend()
        manager = CheckpointManager(backend=backend, frequency="iteration")

        # Should checkpoint every iteration
        assert manager.should_checkpoint(iteration=1, elapsed_seconds=0)
        assert manager.should_checkpoint(iteration=2, elapsed_seconds=0)

    async def test_should_checkpoint_time(self):
        """Test should_checkpoint for time frequency."""
        backend = StateCheckpointBackend()
        manager = CheckpointManager(
            backend=backend,
            frequency="time",
            save_interval_seconds=60.0,
        )

        # First checkpoint should trigger
        assert manager.should_checkpoint(iteration=1, elapsed_seconds=0)

        # Create first checkpoint
        await manager.create_checkpoint(
            agent_name="test-agent",
            run_id="run-123",
            messages=[],
            iteration_count=1,
        )

        # Not enough time passed
        assert not manager.should_checkpoint(iteration=2, elapsed_seconds=30)

        # Enough time passed
        assert manager.should_checkpoint(iteration=3, elapsed_seconds=61)

    async def test_should_checkpoint_manual(self):
        """Test should_checkpoint for manual frequency."""
        backend = StateCheckpointBackend()
        manager = CheckpointManager(backend=backend, frequency="manual")

        # Should never auto-checkpoint
        assert not manager.should_checkpoint(iteration=1, elapsed_seconds=0)
        assert not manager.should_checkpoint(iteration=2, elapsed_seconds=1000)

    async def test_auto_cleanup(self):
        """Test automatic cleanup of old checkpoints."""
        backend = StateCheckpointBackend()
        manager = CheckpointManager(
            backend=backend,
            auto_cleanup=True,
            keep_last=3,
        )

        # Create 10 checkpoints
        for i in range(10):
            await manager.create_checkpoint(
                agent_name="test-agent",
                run_id="run-123",
                messages=[],
                iteration_count=i,
            )

        # Should only have 3 left
        checkpoints = await manager.list_checkpoints(run_id="run-123")
        assert len(checkpoints) == 3

    async def test_list_checkpoints(self):
        """Test listing checkpoints through manager."""
        backend = StateCheckpointBackend()
        manager = CheckpointManager(backend=backend)

        # Create checkpoints
        await manager.create_checkpoint(
            agent_name="agent-1",
            run_id="run-123",
            messages=[],
            iteration_count=1,
        )

        await manager.create_checkpoint(
            agent_name="agent-2",
            run_id="run-123",
            messages=[],
            iteration_count=1,
        )

        # List all
        checkpoints = await manager.list_checkpoints()
        assert len(checkpoints) == 2

        # Filter by agent
        checkpoints = await manager.list_checkpoints(agent_name="agent-1")
        assert len(checkpoints) == 1


class TestHelperFunctions:
    """Test helper functions."""

    async def test_run_with_checkpointing(self):
        """Test run_with_checkpointing helper."""
        backend = StateCheckpointBackend()
        manager = CheckpointManager(backend=backend)

        agent = create_deep_agent(
            model=TestModel(),
            instructions="You are a test agent",
        )
        deps = DeepAgentDeps(backend=StateBackend())

        await run_with_checkpointing(
            agent=agent,
            prompt="Hello",
            deps=deps,
            checkpoint_manager=manager,
            run_id="test-run-123",
        )

        # Should have created a checkpoint
        assert manager.last_checkpoint_id is not None

        # Should have checkpoints for this run
        checkpoints = await manager.list_checkpoints(run_id="test-run-123")
        assert len(checkpoints) >= 1

    async def test_create_manual_checkpoint(self):
        """Test create_manual_checkpoint helper."""
        backend = StateCheckpointBackend()
        manager = CheckpointManager(backend=backend, frequency="manual")

        checkpoint_id = await create_manual_checkpoint(
            agent_name="test-agent",
            run_id="run-123",
            messages=[{"role": "user", "content": "Test"}],
            checkpoint_manager=manager,
            iteration_count=5,
            total_tokens=100,
        )

        assert checkpoint_id is not None

        # Load and verify
        checkpoint = await manager.restore_checkpoint(checkpoint_id)
        assert checkpoint.iteration_count == 5
        assert checkpoint.total_tokens == 100
