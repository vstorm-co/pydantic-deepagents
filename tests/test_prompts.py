"""Tests for the consolidated system-prompt package."""

from __future__ import annotations

from pydantic_deep.prompts import BASE_PROMPT, build_system_prompt, fragments


class TestBuildSystemPrompt:
    def test_interactive_default_equals_base_prompt(self) -> None:
        assert build_system_prompt() == BASE_PROMPT

    def test_interactive_has_core_sections(self) -> None:
        p = build_system_prompt()
        for header in (
            "You are a Deep Agent",
            "# Harness",
            "# Communicating",
            "# Proactiveness",
            "# Doing tasks",
            "# Code style",
            "# Tool usage",
            "# Task management",
            "# Acting with care",
            "# Security",
            "# Verifying your work",
            "# Forking",
        ):
            assert header in p

    def test_interactive_omits_non_interactive_sections(self) -> None:
        p = build_system_prompt()
        assert "# Autonomous mode" not in p
        assert "# Exactness" not in p
        assert "# Paths" not in p

    def test_non_interactive_adds_sections_and_is_longer(self) -> None:
        interactive = build_system_prompt()
        non_interactive = build_system_prompt(non_interactive=True)
        assert "# Autonomous mode" in non_interactive
        assert "# Exactness" in non_interactive
        assert "# Paths" in non_interactive
        assert len(non_interactive) > len(interactive)

    def test_forking_can_be_disabled(self) -> None:
        assert "# Forking" not in build_system_prompt(forking=False)
        assert "# Forking" in build_system_prompt(forking=True)

    def test_working_dir_section_appended(self) -> None:
        p = build_system_prompt(working_dir="/app")
        assert "# Working directory" in p
        assert "`/app`" in p

    def test_lean_non_interactive_is_minimal(self) -> None:
        p = build_system_prompt(non_interactive=True, lean=True)
        assert p.startswith("You are an autonomous coding agent")
        assert "# Acting with care" not in p
        assert "# Harness" not in p

    def test_lean_still_appends_working_dir(self) -> None:
        p = build_system_prompt(non_interactive=True, lean=True, working_dir="/app")
        assert "# Working directory" in p
        assert "`/app`" in p


class TestFragments:
    def test_working_directory_helper(self) -> None:
        section = fragments.working_directory("/home/user/proj")
        assert section.startswith("# Working directory")
        assert "`/home/user/proj`" in section

    def test_all_exported_fragments_are_nonempty_strings(self) -> None:
        for name in fragments.__all__:
            obj = getattr(fragments, name)
            if callable(obj):
                continue
            assert isinstance(obj, str) and obj.strip()
