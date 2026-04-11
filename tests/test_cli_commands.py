"""Tests for CLI sub-commands (skills, threads, config)."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from apps.cli.main import app
from apps.cli.update import UpdateInfo

runner = CliRunner()


class TestConfigShow:
    """Tests for 'config show' command."""

    def test_shows_defaults(self) -> None:
        with patch("apps.cli.config.DEFAULT_CONFIG_PATH", Path("/tmp/nonexistent/config.toml")):
            result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        assert "model" in result.output

    def test_shows_config_values(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text('model = "test-model"\n')

        with patch("apps.cli.config.DEFAULT_CONFIG_PATH", config_file):
            result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        assert "test-model" in result.output


class TestConfigSet:
    """Tests for 'config set' command."""

    def test_sets_value(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        with patch("apps.cli.config.get_config_path", return_value=config_file):
            result = runner.invoke(app, ["config", "set", "model", "new-model"])
        assert result.exit_code == 0
        assert "Set model = new-model" in result.output

    def test_invalid_key(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        with patch("apps.cli.config.get_config_path", return_value=config_file):
            result = runner.invoke(app, ["config", "set", "bad_key", "value"])
        assert result.exit_code == 1

    def test_config_help(self) -> None:
        result = runner.invoke(app, ["config", "--help"])
        assert result.exit_code == 0
        assert "configuration" in result.output.lower()


class TestSkillsList:
    """Tests for 'skills list' command."""

    def test_lists_builtin_skills(self) -> None:
        result = runner.invoke(app, ["skills", "list"])
        assert result.exit_code == 0
        # Skills may appear as "built-in" or "project" if .pydantic-deep/skills exists
        assert "skill-creator" in result.output
        assert "code-review" in result.output
        assert "test-writer" in result.output
        assert "refactor" in result.output
        assert "git-workflow" in result.output

    def test_with_user_directory(self, tmp_path: Path) -> None:
        # Create a user skill
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            '---\nname: my-skill\ndescription: "A custom skill"\n---\n# My Skill'
        )

        result = runner.invoke(app, ["skills", "list", "--dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "my-skill" in result.output

    def test_with_empty_user_directory(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["skills", "list", "--dir", str(tmp_path)])
        assert result.exit_code == 0
        # Should still show built-in skills
        assert "skill-creator" in result.output

    def test_skills_help(self) -> None:
        result = runner.invoke(app, ["skills", "--help"])
        assert result.exit_code == 0


class TestSkillsInfo:
    """Tests for 'skills info' command."""

    def test_shows_builtin_skill(self) -> None:
        result = runner.invoke(app, ["skills", "info", "code-review"])
        assert result.exit_code == 0
        assert "code-review" in result.output
        assert "Description:" in result.output

    def test_shows_skill_content(self) -> None:
        result = runner.invoke(app, ["skills", "info", "skill-creator"])
        assert result.exit_code == 0
        assert "Skill Creator" in result.output

    def test_not_found(self) -> None:
        result = runner.invoke(app, ["skills", "info", "nonexistent-skill"])
        assert result.exit_code == 1


class TestSkillsCreate:
    """Tests for 'skills create' command."""

    def test_creates_scaffold(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["skills", "create", "my-skill", "--dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "Created skill scaffold" in result.output

        skill_file = tmp_path / "my-skill" / "SKILL.md"
        assert skill_file.exists()
        content = skill_file.read_text()
        assert "name: my-skill" in content

    def test_already_exists(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "existing"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("existing")

        result = runner.invoke(app, ["skills", "create", "existing", "--dir", str(tmp_path)])
        assert result.exit_code == 1
        assert "already exists" in result.output


class TestThreadsList:
    """Tests for 'threads list' command."""

    def test_no_threads_dir(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["threads", "list", "--dir", str(tmp_path / "nope")])
        assert result.exit_code == 0
        assert "No threads found" in result.output

    def test_empty_threads(self, tmp_path: Path) -> None:
        threads_dir = tmp_path / "threads"
        threads_dir.mkdir()

        result = runner.invoke(app, ["threads", "list", "--dir", str(threads_dir)])
        assert result.exit_code == 0
        assert "No threads found" in result.output

    def test_lists_threads(self, tmp_path: Path) -> None:
        threads_dir = tmp_path / "threads"
        threads_dir.mkdir()

        # Create a session subdirectory with a messages.json
        session_dir = threads_dir / "abc12345abcd"
        session_dir.mkdir()
        messages_file = session_dir / "messages.json"
        # Minimal valid ModelMessages list (empty)
        messages_file.write_text("[]")

        result = runner.invoke(app, ["threads", "list", "--dir", str(threads_dir)])
        assert result.exit_code == 0
        assert "abc12345" in result.output

    def test_threads_help(self) -> None:
        result = runner.invoke(app, ["threads", "--help"])
        assert result.exit_code == 0


class TestThreadsDelete:
    """Tests for 'threads delete' command."""

    def test_no_threads_dir(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["threads", "delete", "abc123", "--dir", str(tmp_path / "nope")]
        )
        assert result.exit_code == 1
        assert "No threads found" in result.output

    def test_not_found(self, tmp_path: Path) -> None:
        threads_dir = tmp_path / "threads"
        threads_dir.mkdir()

        result = runner.invoke(app, ["threads", "delete", "nonexistent", "--dir", str(threads_dir)])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_deletes_by_prefix(self, tmp_path: Path) -> None:
        threads_dir = tmp_path / "threads"
        threads_dir.mkdir()

        from pydantic_deep.toolsets.checkpointing import Checkpoint, FileCheckpointStore

        # Create a session subdirectory with a checkpoint
        session_dir = threads_dir / "abc12345abcd"
        session_dir.mkdir()
        store = FileCheckpointStore(session_dir)
        cp = Checkpoint(
            id="cp-001",
            label="turn-1",
            turn=1,
            messages=[],
            message_count=3,
            created_at=datetime(2026, 1, 1),
        )
        asyncio.run(store.save(cp))

        result = runner.invoke(app, ["threads", "delete", "abc12345", "--dir", str(threads_dir)])
        assert result.exit_code == 0
        assert "Deleted" in result.output

        # Session directory should be removed
        assert not session_dir.exists()


class TestUpdateCommand:
    """Tests for 'update' command."""

    def test_update_succeeds(self) -> None:
        with patch("apps.cli.update.run_update", return_value=0):
            result = runner.invoke(app, ["update"])
        assert result.exit_code == 0
        assert "Updating" in result.output

    def test_update_propagates_nonzero_exit_code(self) -> None:
        with patch("apps.cli.update.run_update", return_value=1):
            result = runner.invoke(app, ["update"])
        assert result.exit_code == 1

    def test_update_help(self) -> None:
        result = runner.invoke(app, ["update", "--help"])
        assert result.exit_code == 0
        assert "latest" in result.output.lower()


class TestVersionNotification:
    """Tests for the update notification shown at startup."""

    def test_shows_notification_when_update_available(self) -> None:
        upd = UpdateInfo(current="0.1.0", latest="1.0.0")
        with (
            patch("apps.cli.update.check_for_update", return_value=upd),
            patch("apps.cli.config.DEFAULT_CONFIG_PATH", Path("/tmp/nonexistent/config.toml")),
        ):
            result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        assert "Update available" in result.output
        assert "1.0.0" in result.output

    def test_no_output_when_up_to_date(self) -> None:
        with (
            patch("apps.cli.update.check_for_update", return_value=None),
            patch("apps.cli.config.DEFAULT_CONFIG_PATH", Path("/tmp/nonexistent/config.toml")),
        ):
            result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        assert "Update available" not in result.output
