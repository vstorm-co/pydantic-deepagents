"""Tests for output styles module."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from pydantic_deep import create_deep_agent
from pydantic_deep.styles import (
    BUILTIN_STYLES,
    CONCISE_STYLE,
    CONVERSATIONAL_STYLE,
    EXPLANATORY_STYLE,
    FORMAL_STYLE,
    OutputStyle,
    discover_styles,
    format_style_prompt,
    load_style_from_file,
    resolve_style,
)

TEST_MODEL = TestModel()


def _minimal_agent(**kwargs: Any) -> Any:
    """Create agent with minimal toolsets for fast tests."""
    defaults = {
        "model": TEST_MODEL,
        "include_subagents": False,
        "include_skills": False,
        "cost_tracking": False,
        "context_manager": False,
    }
    defaults.update(kwargs)
    return create_deep_agent(**defaults)


# --- OutputStyle dataclass ---


class TestOutputStyle:
    """Tests for OutputStyle dataclass."""

    def test_create(self):
        """OutputStyle can be created with all fields."""
        style = OutputStyle(name="test", description="A test style", content="Be brief.")
        assert style.name == "test"
        assert style.description == "A test style"
        assert style.content == "Be brief."

    def test_equality(self):
        """Two OutputStyles with same fields are equal."""
        a = OutputStyle(name="x", description="y", content="z")
        b = OutputStyle(name="x", description="y", content="z")
        assert a == b

    def test_empty_description(self):
        """OutputStyle works with empty description."""
        style = OutputStyle(name="test", description="", content="content")
        assert style.description == ""


# --- Built-in styles ---


class TestBuiltinStyles:
    """Tests for built-in output styles."""

    def test_all_builtins_exist(self):
        """All 4 built-in styles are registered."""
        assert len(BUILTIN_STYLES) == 4
        assert set(BUILTIN_STYLES.keys()) == {"concise", "explanatory", "formal", "conversational"}

    def test_concise_style(self):
        """Concise style has correct fields."""
        assert CONCISE_STYLE.name == "concise"
        assert CONCISE_STYLE.description
        assert "concise" in CONCISE_STYLE.content.lower()

    def test_explanatory_style(self):
        """Explanatory style has correct fields."""
        assert EXPLANATORY_STYLE.name == "explanatory"
        assert EXPLANATORY_STYLE.description
        assert "explain" in EXPLANATORY_STYLE.content.lower()

    def test_formal_style(self):
        """Formal style has correct fields."""
        assert FORMAL_STYLE.name == "formal"
        assert FORMAL_STYLE.description
        assert "professional" in FORMAL_STYLE.content.lower()

    def test_conversational_style(self):
        """Conversational style has correct fields."""
        assert CONVERSATIONAL_STYLE.name == "conversational"
        assert CONVERSATIONAL_STYLE.description
        assert "friendly" in CONVERSATIONAL_STYLE.content.lower()

    def test_registry_values_match_constants(self):
        """Registry values are the same objects as module constants."""
        assert BUILTIN_STYLES["concise"] is CONCISE_STYLE
        assert BUILTIN_STYLES["explanatory"] is EXPLANATORY_STYLE
        assert BUILTIN_STYLES["formal"] is FORMAL_STYLE
        assert BUILTIN_STYLES["conversational"] is CONVERSATIONAL_STYLE


# --- Resolve style ---


class TestResolveStyle:
    """Tests for resolve_style function."""

    def test_resolve_builtin_by_name(self):
        """Resolves a built-in style by name."""
        style = resolve_style("concise")
        assert style is CONCISE_STYLE

    def test_resolve_all_builtins(self):
        """All built-in names resolve correctly."""
        for name, expected in BUILTIN_STYLES.items():
            assert resolve_style(name) is expected

    def test_passthrough_output_style(self):
        """OutputStyle instance is passed through unchanged."""
        custom = OutputStyle(name="custom", description="Custom", content="Do X")
        assert resolve_style(custom) is custom

    def test_unknown_name_raises(self):
        """Unknown style name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown output style 'nonexistent'"):
            resolve_style("nonexistent")

    def test_unknown_name_lists_available(self):
        """Error message lists available built-in styles."""
        with pytest.raises(ValueError, match="concise"):
            resolve_style("nope")

    def test_resolve_from_styles_dir(self, tmp_path: Path):
        """Resolves a custom style from styles_dir."""
        style_file = tmp_path / "my-style.md"
        style_file.write_text(
            "---\nname: my-style\ndescription: Custom\n---\n\nBe custom.",
            encoding="utf-8",
        )
        style = resolve_style("my-style", styles_dir=str(tmp_path))
        assert style.name == "my-style"
        assert style.content == "Be custom."

    def test_resolve_from_styles_dir_list(self, tmp_path: Path):
        """Resolves from a list of directories."""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()
        style_file = dir2 / "special.md"
        style_file.write_text(
            "---\nname: special\ndescription: Special\n---\n\nBe special.",
            encoding="utf-8",
        )
        style = resolve_style("special", styles_dir=[str(dir1), str(dir2)])
        assert style.name == "special"

    def test_resolve_builtin_takes_precedence(self, tmp_path: Path):
        """Built-in style takes precedence over directory style with same name."""
        style_file = tmp_path / "concise.md"
        style_file.write_text(
            "---\nname: concise\ndescription: Override\n---\n\nOverridden.",
            encoding="utf-8",
        )
        style = resolve_style("concise", styles_dir=str(tmp_path))
        assert style is CONCISE_STYLE

    def test_resolve_not_found_in_dir(self, tmp_path: Path):
        """Raises ValueError when not found in built-ins or directories."""
        with pytest.raises(ValueError, match="Unknown output style"):
            resolve_style("missing", styles_dir=str(tmp_path))


# --- Load from file ---


class TestLoadStyleFromFile:
    """Tests for load_style_from_file function."""

    def test_valid_file(self, tmp_path: Path):
        """Loads style from valid markdown file."""
        f = tmp_path / "test.md"
        f.write_text(
            "---\nname: test-style\ndescription: A test\n---\n\nDo things.",
            encoding="utf-8",
        )
        style = load_style_from_file(f)
        assert style.name == "test-style"
        assert style.description == "A test"
        assert style.content == "Do things."

    def test_missing_name_raises(self, tmp_path: Path):
        """Raises ValueError when frontmatter has no name."""
        f = tmp_path / "no-name.md"
        f.write_text("---\ndescription: No name\n---\n\nContent.", encoding="utf-8")
        with pytest.raises(ValueError, match="must have a 'name'"):
            load_style_from_file(f)

    def test_missing_file_raises(self, tmp_path: Path):
        """Raises FileNotFoundError for non-existent file."""
        with pytest.raises(FileNotFoundError):
            load_style_from_file(tmp_path / "nope.md")

    def test_no_frontmatter(self, tmp_path: Path):
        """File without frontmatter raises ValueError (no name)."""
        f = tmp_path / "plain.md"
        f.write_text("Just plain content.\n", encoding="utf-8")
        with pytest.raises(ValueError, match="must have a 'name'"):
            load_style_from_file(f)

    def test_missing_description(self, tmp_path: Path):
        """Missing description defaults to empty string."""
        f = tmp_path / "no-desc.md"
        f.write_text("---\nname: minimal\n---\n\nMinimal style.", encoding="utf-8")
        style = load_style_from_file(f)
        assert style.name == "minimal"
        assert style.description == ""

    def test_string_path(self, tmp_path: Path):
        """Accepts string path."""
        f = tmp_path / "str-path.md"
        f.write_text("---\nname: strpath\n---\n\nContent.", encoding="utf-8")
        style = load_style_from_file(str(f))
        assert style.name == "strpath"


# --- Discover styles ---


class TestDiscoverStyles:
    """Tests for discover_styles function."""

    def test_discover_multiple(self, tmp_path: Path):
        """Discovers multiple style files."""
        for name in ["alpha", "beta"]:
            f = tmp_path / f"{name}.md"
            f.write_text(
                f"---\nname: {name}\ndescription: {name.title()}\n---\n\n{name} content.",
                encoding="utf-8",
            )
        styles = discover_styles(tmp_path)
        assert len(styles) == 2
        assert "alpha" in styles
        assert "beta" in styles

    def test_discover_skips_invalid(self, tmp_path: Path):
        """Skips files without valid frontmatter."""
        good = tmp_path / "good.md"
        good.write_text("---\nname: good\n---\n\nGood content.", encoding="utf-8")
        bad = tmp_path / "bad.md"
        bad.write_text("No frontmatter here.\n", encoding="utf-8")
        styles = discover_styles(tmp_path)
        assert len(styles) == 1
        assert "good" in styles

    def test_discover_empty_dir(self, tmp_path: Path):
        """Returns empty dict for empty directory."""
        styles = discover_styles(tmp_path)
        assert styles == {}

    def test_discover_nonexistent_dir(self, tmp_path: Path):
        """Returns empty dict for non-existent directory."""
        styles = discover_styles(tmp_path / "nope")
        assert styles == {}

    def test_discover_ignores_non_md(self, tmp_path: Path):
        """Ignores non-markdown files."""
        txt = tmp_path / "style.txt"
        txt.write_text("---\nname: txt\n---\n\nContent.", encoding="utf-8")
        md = tmp_path / "style.md"
        md.write_text("---\nname: md\n---\n\nContent.", encoding="utf-8")
        styles = discover_styles(tmp_path)
        assert len(styles) == 1
        assert "md" in styles

    def test_discover_string_path(self, tmp_path: Path):
        """Accepts string path."""
        f = tmp_path / "s.md"
        f.write_text("---\nname: s\n---\n\nContent.", encoding="utf-8")
        styles = discover_styles(str(tmp_path))
        assert "s" in styles


# --- Format style prompt ---


class TestFormatStylePrompt:
    """Tests for format_style_prompt function."""

    def test_format_builtin(self):
        """Formats a built-in style correctly."""
        result = format_style_prompt(CONCISE_STYLE)
        assert result.startswith("## Output Style: concise")
        assert "concise" in result.lower()

    def test_format_custom(self):
        """Formats a custom style correctly."""
        style = OutputStyle(name="custom", description="Custom", content="Do X\nDo Y")
        result = format_style_prompt(style)
        assert result == "## Output Style: custom\n\nDo X\nDo Y"

    def test_format_includes_content(self):
        """Content is included verbatim."""
        style = OutputStyle(name="t", description="", content="Line 1\nLine 2")
        result = format_style_prompt(style)
        assert "Line 1\nLine 2" in result


# --- Integration with create_deep_agent ---


class TestCreateDeepAgentWithStyle:
    """Tests for output_style parameter in create_deep_agent."""

    def _get_static_instructions(self, agent: Any) -> str:
        """Extract the static instructions string from an agent."""
        instructions = agent._instructions
        if isinstance(instructions, list):
            return instructions[0]
        return instructions  # pragma: no cover

    def test_no_style_by_default(self):
        """Default agent has no style in instructions."""
        agent = _minimal_agent()
        assert isinstance(agent, Agent)
        static = self._get_static_instructions(agent)
        assert "Output Style" not in static

    def test_builtin_style_injected(self):
        """Built-in style is injected into instructions."""
        agent = _minimal_agent(output_style="concise")
        static = self._get_static_instructions(agent)
        assert "## Output Style: concise" in static

    def test_all_builtin_styles(self):
        """All built-in style names work."""
        for name in BUILTIN_STYLES:
            agent = _minimal_agent(output_style=name)
            static = self._get_static_instructions(agent)
            assert f"## Output Style: {name}" in static

    def test_custom_output_style_instance(self):
        """Custom OutputStyle instance is injected."""
        custom = OutputStyle(name="my-style", description="Mine", content="Be awesome.")
        agent = _minimal_agent(output_style=custom)
        static = self._get_static_instructions(agent)
        assert "## Output Style: my-style" in static
        assert "Be awesome." in static

    def test_style_appended_to_instructions(self):
        """Style is appended after base instructions."""
        agent = _minimal_agent(instructions="Base prompt.", output_style="formal")
        static = self._get_static_instructions(agent)
        assert static.startswith("Base prompt.")
        assert "## Output Style: formal" in static

    def test_style_with_custom_instructions(self):
        """Custom instructions + style both present."""
        agent = _minimal_agent(instructions="You are helpful.", output_style="explanatory")
        static = self._get_static_instructions(agent)
        assert "You are helpful." in static
        assert "## Output Style: explanatory" in static

    def test_style_from_directory(self, tmp_path: Path):
        """Loads style from styles_dir."""
        f = tmp_path / "custom.md"
        f.write_text(
            "---\nname: custom\ndescription: Custom\n---\n\nBe custom.",
            encoding="utf-8",
        )
        agent = _minimal_agent(output_style="custom", styles_dir=str(tmp_path))
        static = self._get_static_instructions(agent)
        assert "## Output Style: custom" in static
        assert "Be custom." in static

    def test_invalid_style_name_raises(self):
        """Unknown style name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown output style"):
            _minimal_agent(output_style="nonexistent")

    def test_none_style_no_change(self):
        """output_style=None leaves instructions unchanged."""
        agent1 = _minimal_agent(instructions="Test")
        agent2 = _minimal_agent(instructions="Test", output_style=None)
        static1 = self._get_static_instructions(agent1)
        static2 = self._get_static_instructions(agent2)
        assert static1 == static2

    def test_style_with_middleware(self):
        """Style works when middleware wrapping is active."""
        agent = _minimal_agent(
            output_style="concise",
            cost_tracking=True,
            context_manager=True,
        )
        # MiddlewareAgent wraps the original agent
        assert hasattr(agent, "wrapped")
        static = self._get_static_instructions(agent.wrapped)
        assert "## Output Style: concise" in static


# --- Exports ---


class TestStyleExports:
    """Tests for style types exported from pydantic_deep."""

    def test_output_style_importable(self):
        """OutputStyle is importable from pydantic_deep."""
        from pydantic_deep import OutputStyle

        assert OutputStyle is not None

    def test_builtin_styles_importable(self):
        """BUILTIN_STYLES is importable from pydantic_deep."""
        from pydantic_deep import BUILTIN_STYLES

        assert BUILTIN_STYLES is not None
        assert len(BUILTIN_STYLES) == 4

    def test_resolve_style_importable(self):
        """resolve_style is importable from pydantic_deep."""
        from pydantic_deep import resolve_style

        assert callable(resolve_style)

    def test_load_style_from_file_importable(self):
        """load_style_from_file is importable from pydantic_deep."""
        from pydantic_deep import load_style_from_file

        assert callable(load_style_from_file)

    def test_discover_styles_importable(self):
        """discover_styles is importable from pydantic_deep."""
        from pydantic_deep import discover_styles

        assert callable(discover_styles)

    def test_format_style_prompt_importable(self):
        """format_style_prompt is importable from pydantic_deep."""
        from pydantic_deep import format_style_prompt

        assert callable(format_style_prompt)
