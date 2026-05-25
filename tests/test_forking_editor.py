""":class:`EditorDetector` tests (issue #106)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from pydantic_deep.toolsets.forking.editor import EditorDetector

# ---------------------------------------------------------------------------
# Test 6 — PYDANTIC_DEEP_DIFFTOOL env var takes precedence.
# ---------------------------------------------------------------------------


def test_env_override_takes_precedence_over_path_detection() -> None:
    with patch(
        "shutil.which", side_effect=lambda x: "/usr/bin/pycharm" if x == "pycharm" else None
    ):
        # Even with pycharm on PATH, env var wins.
        kind = EditorDetector.detect({"PYDANTIC_DEEP_DIFFTOOL": "meld {parent} {branches}"})
    assert kind == "custom"


def test_env_override_works_without_path_tools() -> None:
    with patch("shutil.which", return_value=None):
        kind = EditorDetector.detect({"PYDANTIC_DEEP_DIFFTOOL": "meld"})
    assert kind == "custom"


# ---------------------------------------------------------------------------
# Test 7 — PyCharm detection produces a single Popen.
# ---------------------------------------------------------------------------


def test_pycharm_invoke_makes_single_popen_with_all_paths() -> None:
    with patch("pydantic_deep.toolsets.forking.editor.subprocess.Popen") as popen_mock:
        popen_mock.return_value = MagicMock()
        handles = EditorDetector.invoke(
            "pycharm",
            Path("/parent/cat.md"),
            [Path("/a/cat.md"), Path("/b/cat.md"), Path("/c/cat.md")],
        )
    assert popen_mock.call_count == 1
    args = popen_mock.call_args.args[0]
    assert args == ["pycharm", "diff", "/parent/cat.md", "/a/cat.md", "/b/cat.md", "/c/cat.md"]
    assert len(handles) == 1


def test_pycharm_detection_when_pycharm_on_path_only() -> None:
    with patch(
        "shutil.which", side_effect=lambda x: "/usr/bin/pycharm" if x == "pycharm" else None
    ):
        assert EditorDetector.detect({}) == "pycharm"


# ---------------------------------------------------------------------------
# Test 8 — VS Code detection: one Popen per branch.
# ---------------------------------------------------------------------------


def test_vscode_invoke_makes_one_popen_per_branch() -> None:
    branch_paths = [Path("/a/cat.md"), Path("/b/cat.md"), Path("/c/cat.md")]
    with patch("pydantic_deep.toolsets.forking.editor.subprocess.Popen") as popen_mock:
        popen_mock.return_value = MagicMock()
        handles = EditorDetector.invoke("vscode", Path("/parent/cat.md"), branch_paths)
    # Three branches → three Popen calls (one per branch).
    assert popen_mock.call_count == len(branch_paths) == 3
    for i, call in enumerate(popen_mock.call_args_list):
        assert call.args[0] == ["code", "--diff", "/parent/cat.md", str(branch_paths[i])]
    assert len(handles) == 3


def test_vscode_preferred_when_pycharm_missing() -> None:
    def which_stub(x: str) -> str | None:
        return "/usr/bin/code" if x == "code" else None

    with patch("shutil.which", side_effect=which_stub):
        assert EditorDetector.detect({}) == "vscode"


# ---------------------------------------------------------------------------
# Test 9 — TUI fallback returns empty list.
# ---------------------------------------------------------------------------


def test_tui_fallback_when_no_editor_found() -> None:
    with patch("shutil.which", return_value=None):
        assert EditorDetector.detect({}) == "tui"


def test_tui_invoke_returns_empty_list_and_spawns_no_processes() -> None:
    with patch("pydantic_deep.toolsets.forking.editor.subprocess.Popen") as popen_mock:
        handles = EditorDetector.invoke("tui", Path("/p"), [Path("/a")])
    assert handles == []
    assert popen_mock.call_count == 0


# ---------------------------------------------------------------------------
# Test 10 — Popen is mocked throughout (no real launches).
# ---------------------------------------------------------------------------


def test_custom_invoke_uses_template_substitution() -> None:
    """``custom`` kind: env var template gets ``{parent}`` / ``{branches}`` filled in."""
    with patch("pydantic_deep.toolsets.forking.editor.subprocess.Popen") as popen_mock:
        popen_mock.return_value = MagicMock()
        EditorDetector.invoke(
            "custom",
            Path("/p"),
            [Path("/a"), Path("/b")],
            custom_cmd="meld {parent} {branches}",
        )
    assert popen_mock.call_count == 1
    # Shell-mode invocation receives the formatted string.
    args, kwargs = popen_mock.call_args
    assert args[0] == "meld /p /a /b"
    assert kwargs == {"shell": True}


def test_custom_invoke_reads_env_when_no_template_supplied() -> None:
    with patch("pydantic_deep.toolsets.forking.editor.subprocess.Popen") as popen_mock:
        popen_mock.return_value = MagicMock()
        with patch.dict(
            "os.environ", {"PYDANTIC_DEEP_DIFFTOOL": "meld {parent} {branches}"}, clear=False
        ):
            EditorDetector.invoke("custom", Path("/p"), [Path("/a")])
    assert popen_mock.call_count == 1
    assert popen_mock.call_args.args[0] == "meld /p /a"


# ---------------------------------------------------------------------------
# parent=None — branch-only diff.
# ---------------------------------------------------------------------------


def test_pycharm_invoke_two_branches_puts_parent_in_center() -> None:
    with patch("pydantic_deep.toolsets.forking.editor.subprocess.Popen") as popen_mock:
        popen_mock.return_value = MagicMock()
        EditorDetector.invoke("pycharm", Path("/p/f"), [Path("/a/f"), Path("/b/f")])
    args = popen_mock.call_args.args[0]
    assert args == ["pycharm", "diff", "/a/f", "/p/f", "/b/f"]


def test_pycharm_invoke_no_parent_omits_parent_arg() -> None:
    with patch("pydantic_deep.toolsets.forking.editor.subprocess.Popen") as popen_mock:
        popen_mock.return_value = MagicMock()
        handles = EditorDetector.invoke("pycharm", None, [Path("/a/f"), Path("/b/f")])
    assert popen_mock.call_count == 1
    assert popen_mock.call_args.args[0] == ["pycharm", "diff", "/a/f", "/b/f"]
    assert len(handles) == 1


def test_vscode_invoke_no_parent_two_branches_diffs_first_vs_rest() -> None:
    with patch("pydantic_deep.toolsets.forking.editor.subprocess.Popen") as popen_mock:
        popen_mock.return_value = MagicMock()
        handles = EditorDetector.invoke("vscode", None, [Path("/a/f"), Path("/b/f")])
    assert popen_mock.call_count == 1
    assert popen_mock.call_args.args[0] == ["code", "--diff", "/a/f", "/b/f"]
    assert len(handles) == 1


def test_vscode_invoke_no_parent_single_branch_opens_file() -> None:
    with patch("pydantic_deep.toolsets.forking.editor.subprocess.Popen") as popen_mock:
        popen_mock.return_value = MagicMock()
        handles = EditorDetector.invoke("vscode", None, [Path("/a/f")])
    assert popen_mock.call_count == 1
    assert popen_mock.call_args.args[0] == ["code", "/a/f"]
    assert len(handles) == 1


def test_vscode_invoke_no_parent_no_branches_returns_empty() -> None:
    with patch("pydantic_deep.toolsets.forking.editor.subprocess.Popen") as popen_mock:
        handles = EditorDetector.invoke("vscode", None, [])
    assert handles == []
    assert popen_mock.call_count == 0


def test_tui_invoke_no_parent_still_empty() -> None:
    with patch("pydantic_deep.toolsets.forking.editor.subprocess.Popen") as popen_mock:
        handles = EditorDetector.invoke("tui", None, [Path("/a")])
    assert handles == []
    assert popen_mock.call_count == 0


def test_custom_invoke_no_parent_substitutes_empty_string() -> None:
    with patch("pydantic_deep.toolsets.forking.editor.subprocess.Popen") as popen_mock:
        popen_mock.return_value = MagicMock()
        EditorDetector.invoke(
            "custom", None, [Path("/a"), Path("/b")], custom_cmd="meld {parent} {branches}"
        )
    assert popen_mock.call_count == 1
    assert popen_mock.call_args.args[0] == "meld  /a /b"
