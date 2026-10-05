"""Live Run Forking — a branch's copy-on-write view of the parent workspace."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.workspaces import (
    LocalWorkspaceBackend,
    ReadOnlyWorkspace,
    Workspace,
    WorkspaceTimeoutError,
)

from pydantic_deep import (
    BranchIsolation,
    BranchOverlay,
    LocalBranchOverlay,
    branch_workspace,
)
from pydantic_deep.features.forking.isolation import (
    _branch_snapshot,
    _propagate_mutations,
    branch_overlay,
    local_root,
)
from pydantic_deep.features.forking.materializer import ForkMaterializer
from tests.workspaces import state_workspace


def _overlay(files: dict[str, str] | None = None) -> BranchOverlay:
    return BranchOverlay(state_workspace(files))


def _local(tmp_path: Path) -> tuple[Path, LocalBranchOverlay]:
    root = tmp_path.resolve()
    return root, LocalBranchOverlay(Workspace(LocalWorkspaceBackend(root)))


# ---------------------------------------------------------------------------
# Reads fall through, writes stay in the branch
# ---------------------------------------------------------------------------


async def test_writes_stay_in_the_branch() -> None:
    parent = state_workspace({"/foo.py": "v0"})
    a, b = BranchOverlay(parent), BranchOverlay(parent)
    await a.write_bytes("/foo.py", b"vA")
    assert await a.read_bytes("/foo.py") == b"vA"
    assert await b.read_bytes("/foo.py") == b"v0"
    assert await parent.read_bytes("/foo.py") == b"v0"
    assert [(c.path, c.op) for c in a.changes()] == [("/foo.py", "write")]


async def test_identity_and_working_dir_come_from_the_parent() -> None:
    parent = state_workspace()
    overlay = BranchOverlay(parent)
    assert overlay.parent is parent
    assert overlay.ref is None
    assert await overlay.working_dir() == "/"


async def test_stat_and_exists_cover_both_layers() -> None:
    overlay = _overlay({"/parent.py": "p"})
    await overlay.write_bytes("/dir/new.py", b"abc")
    assert (await overlay.stat("/dir/new.py")).size == 3
    assert (await overlay.stat("/dir")).is_dir
    assert (await overlay.stat("/parent.py")).size == 1
    assert await overlay.exists("/parent.py") and await overlay.exists("/dir/new.py")
    assert not await overlay.exists("/nothing.py")


async def test_list_dir_merges_both_layers() -> None:
    overlay = _overlay({"/a.py": "x", "/gone.py": "y"})
    await overlay.write_bytes("/b.py", b"y")
    await overlay.write_bytes("/only/c.py", b"z")
    await overlay.remove("/gone.py")
    assert sorted(e.path for e in await overlay.list_dir("/")) == ["/a.py", "/b.py", "/only"]
    assert [e.path for e in await overlay.list_dir("/only")] == ["/only/c.py"]
    with pytest.raises(FileNotFoundError):
        await overlay.list_dir("/missing")


async def test_a_workspace_over_the_overlay_works_like_any_other() -> None:
    workspace = Workspace(_overlay({"/notes.md": "hello"}))
    await workspace.write_text("out/result.txt", "done")
    assert await workspace.read_text("notes.md") == "hello"
    assert await workspace.read_text("out/result.txt") == "done"


async def test_a_directory_cannot_be_written_as_a_file() -> None:
    overlay = _overlay({"/pkg/mod.py": "x"})
    with pytest.raises(IsADirectoryError):
        await overlay.write_bytes("/pkg", b"no")
    await overlay.make_dir("/made")
    with pytest.raises(IsADirectoryError):
        await overlay.write_bytes("/made", b"no")


# ---------------------------------------------------------------------------
# Directories and removals
# ---------------------------------------------------------------------------


async def test_make_dir_records_a_new_directory_once() -> None:
    overlay = _overlay({"/file.txt": "x", "/pkg/mod.py": "y"})
    await overlay.make_dir("/new/deep")
    await overlay.make_dir("/new/deep")
    await overlay.make_dir("/pkg")
    assert [(c.path, c.op) for c in overlay.changes()] == [("/new/deep", "mkdir")]
    with pytest.raises(FileExistsError):
        await overlay.make_dir("/file.txt")


async def test_removing_a_file_or_a_directory_hides_it() -> None:
    overlay = _overlay({"/x.py": "v0", "/proj/sub/file.txt": "c", "/proj/keep.txt": "k"})
    await overlay.remove("/x.py")
    await overlay.remove("/proj/sub")
    assert [(c.path, c.op) for c in overlay.changes()] == [
        ("/x.py", "delete"),
        ("/proj/sub", "rmdir"),
    ]
    assert not await overlay.exists("/x.py")
    assert not await overlay.exists("/proj/sub/file.txt")
    for read in (overlay.read_bytes, overlay.stat, overlay.list_dir):
        with pytest.raises(FileNotFoundError):
            await read("/proj/sub/file.txt" if read is not overlay.list_dir else "/proj/sub")
    assert [e.path for e in await overlay.list_dir("/proj")] == ["/proj/keep.txt"]
    with pytest.raises(FileNotFoundError):
        await overlay.remove("/x.py")
    deleted = overlay.deleted()
    deleted.clear()
    assert overlay.deleted() == {"/x.py", "/proj/sub"}


async def test_removing_a_file_the_branch_wrote_drops_it_from_the_overlay() -> None:
    overlay = _overlay()
    await overlay.write_bytes("/tmp.txt", b"x")
    await overlay.remove("/tmp.txt")
    assert not await overlay.exists("/tmp.txt")


async def test_writing_inside_a_removed_directory_brings_the_file_back() -> None:
    overlay = _overlay({"/proj/jajo/old.txt": "old", "/x.py": "v0"})
    await overlay.remove("/proj/jajo")
    await overlay.write_bytes("/proj/jajo/new.txt", b"new")
    await overlay.remove("/x.py")
    await overlay.make_dir("/x.py.d")
    await overlay.write_bytes("/x.py", b"v1")
    assert await overlay.read_bytes("/proj/jajo/new.txt") == b"new"
    assert await overlay.exists("/proj/jajo/old.txt")  # the tombstone covering it is gone
    assert await overlay.read_bytes("/x.py") == b"v1"
    assert "/x.py" not in overlay.deleted()


# ---------------------------------------------------------------------------
# Materializer
# ---------------------------------------------------------------------------


async def test_the_materializer_sees_first_touch_and_every_change(tmp_path: Path) -> None:
    materializer = ForkMaterializer(root=tmp_path / "fork", fork_id="f")
    overlay = _overlay({"/x.py": "v0"})
    overlay.attach_materializer(materializer, "approach_a")
    await overlay.write_bytes("/x.py", b"v1")
    await overlay.write_bytes("/new.py", b"n")
    await overlay.make_dir("/d")
    await overlay.remove("/new.py")
    assert materializer.pre_flush_snapshot() == {"/x.py": b"v0", "/new.py": None}
    assert materializer.branch_path("approach_a", "/x.py").read_bytes() == b"v1"
    assert not materializer.branch_path("approach_a", "/new.py").exists()


async def test_a_mirror_that_fails_is_logged_not_raised(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class _Broken(ForkMaterializer):
        def flush_change(self, *args: Any) -> None:
            raise OSError("disk full")

    overlay = _overlay()
    overlay.attach_materializer(_Broken(root=tmp_path / "fork", fork_id="f"), "a")
    with caplog.at_level(logging.WARNING):
        await overlay.write_bytes("/x.py", b"v1")
    assert "materializer mirror failed" in caplog.text
    assert await overlay.read_bytes("/x.py") == b"v1"


# ---------------------------------------------------------------------------
# Merging back
# ---------------------------------------------------------------------------


async def test_flush_replays_every_change_onto_the_parent() -> None:
    parent = state_workspace({"/keep.py": "k", "/old.py": "o", "/olddir/f.txt": "f"})
    overlay = BranchOverlay(parent)
    await overlay.write_bytes("/keep.py", b"k1")
    await overlay.write_bytes("/keep.py", b"k2")
    await overlay.remove("/old.py")
    await overlay.remove("/old.py") if await overlay.exists("/old.py") else None
    await overlay.remove("/olddir")
    await overlay.make_dir("/newdir")
    await overlay.write_bytes("/again.py", b"a")
    await overlay.remove("/again.py")
    await overlay.write_bytes("/again.py", b"b")

    report = await overlay.flush_to(parent)

    assert report.applied_paths == ["/keep.py", "/newdir", "/again.py"]
    assert report.deleted_paths == ["/old.py", "/olddir"]
    assert report.applied_changes == 9 - 1
    assert (report.conflicts, report.errors) == ([], [])
    assert await parent.read_bytes("/keep.py") == b"k2"
    assert await parent.read_bytes("/again.py") == b"b"
    assert not await parent.exists("/old.py") and not await parent.exists("/olddir")
    assert (await parent.stat("/newdir")).is_dir


async def test_a_removal_the_parent_already_made_is_still_applied() -> None:
    parent = state_workspace({"/x.py": "v0"})
    overlay = BranchOverlay(parent)
    await overlay.remove("/x.py")
    await parent.remove("/x.py")
    report = await overlay.flush_to(parent)
    assert report.deleted_paths == ["/x.py"] and report.errors == []


async def test_a_path_a_third_actor_changed_is_a_conflict_not_overwritten() -> None:
    parent = state_workspace({"/mod.py": "base", "/gone.py": "g", "/new.py": "n"})
    overlay = BranchOverlay(parent)
    await overlay.write_bytes("/mod.py", b"branch")
    await overlay.write_bytes("/gone.py", b"branch")
    await overlay.write_bytes("/new.py", b"branch")
    await overlay.write_bytes("/untracked.py", b"branch")
    await parent.write_bytes("/mod.py", b"third actor")
    await parent.remove("/gone.py")

    snapshot = {"/mod.py": b"base", "/gone.py": b"g", "/new.py": b"n"}
    report = await overlay.flush_to(parent, snapshot)

    assert report.conflicts == ["/gone.py", "/mod.py"]
    assert report.applied_paths == ["/new.py", "/untracked.py"]
    assert await parent.read_bytes("/mod.py") == b"third actor"


async def test_a_change_the_parent_refuses_is_reported_and_the_rest_applied() -> None:
    parent = state_workspace({"/a.py": "a"})
    overlay = BranchOverlay(parent)
    await overlay.write_bytes("/a.py", b"a1")
    await overlay.write_bytes("/b.py", b"b1")
    await overlay.write_bytes("/a.py", b"a2")

    report = await overlay.flush_to(ReadOnlyWorkspace(parent))

    assert [(e.path, e.op) for e in report.errors] == [
        ("/a.py", "write"),
        ("/b.py", "write"),
        ("/a.py", "write"),
    ]
    assert report.applied_paths == [] and report.applied_changes == 0


async def test_a_failure_after_a_success_withdraws_the_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = state_workspace()
    overlay = BranchOverlay(parent)
    await overlay.write_bytes("/a.py", b"1")
    await overlay.write_bytes("/a.py", b"2")
    calls = 0
    real_write = parent.write_bytes

    async def flaky(path: str, data: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk full")
        await real_write(path, data)

    monkeypatch.setattr(parent, "write_bytes", flaky)
    report = await overlay.flush_to(parent)
    assert report.applied_paths == [] and [e.message for e in report.errors] == ["disk full"]


# ---------------------------------------------------------------------------
# Choosing the overlay and the branch's workspace
# ---------------------------------------------------------------------------


def test_local_root_looks_through_wrappers(tmp_path: Path) -> None:
    local = Workspace(LocalWorkspaceBackend(tmp_path))
    assert local_root(local) == tmp_path.resolve()
    assert local_root(ReadOnlyWorkspace(local)) == tmp_path.resolve()
    assert local_root(state_workspace()) is None


def test_a_local_parent_gets_an_overlay_that_runs_commands(tmp_path: Path) -> None:
    assert isinstance(
        branch_overlay(Workspace(LocalWorkspaceBackend(tmp_path))), LocalBranchOverlay
    )
    assert type(branch_overlay(state_workspace())) is BranchOverlay


def test_copy_isolation_gives_a_workspace_over_an_overlay() -> None:
    parent = state_workspace()
    workspace, overlay = branch_workspace(parent, BranchIsolation())
    assert overlay is not None and workspace.backend is overlay and overlay.parent is parent


# ---------------------------------------------------------------------------
# Commands in a local branch run in a copy, and their effects are recorded
# ---------------------------------------------------------------------------


async def test_a_command_never_touches_the_parent(tmp_path: Path) -> None:
    root, overlay = _local(tmp_path)
    (root / "real.py").write_text("keep me")
    (root / "edit.py").write_text("before")
    workspace = Workspace(overlay)

    await workspace.run(f"rm {root / 'real.py'}; echo after > edit.py; mkdir newdir", shell=True)

    assert (root / "real.py").read_text() == "keep me"
    assert (root / "edit.py").read_text() == "before"
    assert not (root / "newdir").exists()
    ops = {(c.path, c.op) for c in overlay.changes()}
    assert (str(root / "real.py"), "delete") in ops
    assert (str(root / "edit.py"), "write") in ops
    assert (str(root / "newdir"), "mkdir") in ops
    assert await overlay.read_bytes(str(root / "edit.py")) == b"after\n"


async def test_a_command_sees_the_branch_and_not_what_it_removed(tmp_path: Path) -> None:
    root, overlay = _local(tmp_path)
    (root / "gone.txt").write_text("x")
    (root / "olddir").mkdir()
    (root / "olddir" / "f.txt").write_text("f")
    await overlay.write_bytes(str(root / "sub" / "branch.txt"), b"from branch")
    await overlay.make_dir(str(root / "emptydir"))
    await overlay.remove(str(root / "gone.txt"))
    await overlay.remove(str(root / "olddir"))

    result = await Workspace(overlay).run(
        ["sh", "-c", f"cat {root}/sub/branch.txt; ls; test -e gone.txt || echo no-gone"]
    )

    assert "from branch" in result.stdout
    assert "emptydir" in result.stdout and "olddir" not in result.stdout
    assert "no-gone" in result.stdout


async def test_removing_a_directory_with_a_command_is_recorded(tmp_path: Path) -> None:
    root, overlay = _local(tmp_path)
    (root / "empty").mkdir()
    await Workspace(overlay).run("rmdir empty", shell=True)
    assert (str(root / "empty"), "rmdir") in {(c.path, c.op) for c in overlay.changes()}


async def test_what_a_timed_out_command_did_is_still_recorded(tmp_path: Path) -> None:
    root, overlay = _local(tmp_path)
    with pytest.raises(WorkspaceTimeoutError):
        await Workspace(overlay).run("echo partial > out.txt; sleep 5", shell=True, timeout=0.5)
    assert await overlay.read_bytes(str(root / "out.txt")) == b"partial\n"


async def test_a_file_that_cannot_be_captured_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    root, overlay = _local(tmp_path)
    with caplog.at_level(logging.WARNING):
        await Workspace(overlay).run("echo x > secret.txt; chmod 000 secret.txt", shell=True)
    assert "failed to capture" in caplog.text


def test_snapshot_can_bring_the_virtualenv(tmp_path: Path) -> None:
    root, overlay = _local(tmp_path)
    (root / ".venv").mkdir()
    with overlay.snapshot(root, include_venv=True) as snap:
        assert (Path(snap) / ".venv").is_symlink()
    with overlay.snapshot(root) as snap:
        assert not (Path(snap) / ".venv").exists()


def test_a_path_outside_the_root_lands_inside_the_snapshot(tmp_path: Path) -> None:
    from pydantic_ai_backends import StateBackend

    from pydantic_deep.features.forking.types import FileChange

    root = tmp_path / "root"
    root.mkdir()
    store = StateBackend()
    store.write_bytes("/elsewhere/x.txt", b"x")
    from datetime import datetime, timezone

    change = FileChange(path="/elsewhere/x.txt", op="write", timestamp=datetime.now(timezone.utc))
    with _branch_snapshot(root, store, [change], set()) as snap:
        assert (Path(snap) / "elsewhere" / "x.txt").read_bytes() == b"x"


async def test_an_unchanged_snapshot_records_nothing(tmp_path: Path) -> None:
    root, overlay = _local(tmp_path)
    state = {"a.txt": (False, "1:abc")}
    await _propagate_mutations(tmp_path, root, state, dict(state), overlay)
    assert overlay.changes() == []


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------


def test_collect_state_records_empty_directories(tmp_path: Path) -> None:
    """_collect_state records empty directories as entries ending with '/'."""
    from pydantic_deep.features.forking.isolation import _collect_state

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    state: dict[str, tuple[bool, float]] = {}
    _collect_state(tmp_path, tmp_path, state)
    assert "empty/" in state


def test_collect_state_does_not_record_nonempty_directories(tmp_path: Path) -> None:
    """_collect_state does NOT record directories that contain files."""
    from pydantic_deep.features.forking.isolation import _collect_state

    nonempty = tmp_path / "has_file"
    nonempty.mkdir()
    (nonempty / "f.txt").write_text("content")

    state: dict[str, tuple[bool, float]] = {}
    _collect_state(tmp_path, tmp_path, state)
    assert "has_file/" not in state
    assert "has_file/f.txt" in state


def test_rewrite_parent_root_only_on_path_boundaries() -> None:
    from pydantic_deep.features.forking.isolation import _rewrite_parent_root

    root = "/home/u/proj"
    snap = "/tmp/snap"

    # Boundary matches ARE rewritten: separator, end-of-string, whitespace, quote.
    assert _rewrite_parent_root(f"cat {root}/a.py", root, snap) == f"cat {snap}/a.py"
    assert _rewrite_parent_root(f"cd {root}", root, snap) == f"cd {snap}"
    assert _rewrite_parent_root(f"ls {root} -la", root, snap) == f"ls {snap} -la"
    assert _rewrite_parent_root(f"cat '{root}/a.py'", root, snap) == f"cat '{snap}/a.py'"

    # A sibling sharing the prefix must NOT be mangled.
    assert _rewrite_parent_root(f"cat {root}_backup/x", root, snap) == f"cat {root}_backup/x"
    # The root inside an unrelated literal token must NOT be rewritten.
    assert _rewrite_parent_root(f"echo {root}xyz", root, snap) == f"echo {root}xyz"

    # Empty root is a no-op.
    assert _rewrite_parent_root("ls -la", "", snap) == "ls -la"


def test_copy_tree_recurses_into_subdirectory(tmp_path: Path) -> None:
    """_copy_tree mirrors subdirectory structure as real copies and skips _SNAP_SKIP_DIRS."""
    from pydantic_deep.features.forking.isolation import _SNAP_SKIP_DIRS, _copy_tree

    src = tmp_path / "src"
    src.mkdir()
    (src / "root_file.py").write_text("root")
    subdir = src / "subdir"
    subdir.mkdir()
    (subdir / "nested.py").write_text("nested")
    # Add a _SNAP_SKIP_DIRS entry — should be skipped.
    skip_name = next(iter(_SNAP_SKIP_DIRS))
    (src / skip_name).mkdir()
    (src / skip_name / "ignored.py").write_text("ignored")

    dst = tmp_path / "dst"
    dst.mkdir()
    _copy_tree(src, dst)

    # Files are detached real copies, NOT symlinks (copy-on-write isolation).
    assert (dst / "root_file.py").is_file()
    assert not (dst / "root_file.py").is_symlink()
    assert (dst / "root_file.py").read_text() == "root"
    assert (dst / "subdir").is_dir()
    assert (dst / "subdir" / "nested.py").is_file()
    assert not (dst / "subdir" / "nested.py").is_symlink()
    assert (dst / "subdir" / "nested.py").read_text() == "nested"
    assert not (dst / skip_name).exists()

    # Writing into the copy must not touch the source (the isolation guarantee).
    (dst / "root_file.py").write_text("branch-modified")
    assert (src / "root_file.py").read_text() == "root"


def test_copy_tree_skips_unreadable_entry(tmp_path: Path) -> None:
    """_copy_tree logs and skips an entry it can't copy (e.g. a dangling symlink)."""
    from pydantic_deep.features.forking.isolation import _copy_tree

    src = tmp_path / "src"
    src.mkdir()
    (src / "good.py").write_text("ok")
    # Dangling symlink: copy2(follow_symlinks=True) raises FileNotFoundError (OSError).
    (src / "dangling.py").symlink_to(tmp_path / "missing-target.py")

    dst = tmp_path / "dst"
    dst.mkdir()
    _copy_tree(src, dst)

    # The good file is copied; the unreadable entry is skipped (absent), no raise.
    assert (dst / "good.py").read_text() == "ok"
    assert not (dst / "dangling.py").exists()


def test_collect_state_skips_snap_skip_dirs(tmp_path: Path) -> None:
    """_collect_state does not recurse into _SNAP_SKIP_DIRS entries."""
    from pydantic_deep.features.forking.isolation import _SNAP_SKIP_DIRS, _collect_state

    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "real.py").write_text("real")
    skip_name = next(iter(_SNAP_SKIP_DIRS))
    skip_dir = snap / skip_name
    skip_dir.mkdir()
    (skip_dir / "deep.py").write_text("deep")

    out: dict[str, tuple[bool, float]] = {}
    _collect_state(snap, snap, out)

    assert "real.py" in out
    assert f"{skip_name}/deep.py" not in out
    assert not any(k.startswith(skip_name) for k in out)


def test_collect_state_recurses_into_subdirectory(tmp_path: Path) -> None:
    """_collect_state recurses into normal subdirectories."""
    from pydantic_deep.features.forking.isolation import _collect_state

    snap = tmp_path / "snap"
    snap.mkdir()
    sub = snap / "pkg"
    sub.mkdir()
    (sub / "module.py").write_text("x")

    out: dict[str, tuple[bool, float]] = {}
    _collect_state(snap, snap, out)

    assert "pkg/module.py" in out


def test_collect_state_skips_non_file_non_dir_entries(tmp_path: Path) -> None:
    """_collect_state ignores entries that are not symlinks, files, or directories."""
    import os

    from pydantic_deep.features.forking.isolation import _collect_state

    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "real.py").write_text("real")
    # Named pipe is not a symlink, not a regular file, not a directory.
    fifo = snap / "mypipe"
    os.mkfifo(fifo)

    out: dict[str, tuple[bool, float]] = {}
    _collect_state(snap, snap, out)

    assert "real.py" in out
    assert "mypipe" not in out


def test_collect_state_permission_error_returns_silently(tmp_path: Path) -> None:
    """_collect_state silently returns when os.scandir raises PermissionError."""
    from unittest.mock import patch

    from pydantic_deep.features.forking.isolation import _collect_state

    with patch("os.scandir", side_effect=PermissionError("no access")):
        out: dict[str, tuple[bool, float]] = {}
        _collect_state(tmp_path, tmp_path, out)  # must not raise
    assert out == {}


def test_collect_state_symlink_signature_oserror_fallback(tmp_path: Path) -> None:
    """A dangling symlink → content signature falls back to '' (unreadable)."""
    from pydantic_deep.features.forking.isolation import _collect_state

    snap = tmp_path / "snap"
    snap.mkdir()
    link = snap / "dangling.py"
    link.symlink_to(tmp_path / "does_not_exist.py")

    out: dict[str, tuple[bool, str]] = {}
    _collect_state(snap, snap, out)

    assert "dangling.py" in out
    is_sym, sig = out["dangling.py"]
    assert is_sym
    assert sig == ""


def test_collect_state_file_signature_oserror_fallback(tmp_path: Path) -> None:
    """_collect_state uses signature='' when a file's content can't be read."""
    from unittest.mock import MagicMock, patch

    from pydantic_deep.features.forking.isolation import _collect_state

    snap = tmp_path / "snap"
    snap.mkdir()

    # Mock entry pointing at a path open() can't read → _file_signature returns ''.
    mock_entry = MagicMock()
    mock_entry.name = "file.py"
    mock_entry.path = str(snap / "nonexistent.py")
    mock_entry.is_symlink.return_value = False
    mock_entry.is_file.return_value = True
    mock_entry.is_dir.return_value = False

    with patch("os.scandir", return_value=iter([mock_entry])):
        out: dict[str, tuple[bool, str]] = {}
        _collect_state(snap, snap, out)

    assert "nonexistent.py" in out
    _, sig = out["nonexistent.py"]
    assert sig == ""


def test_snapshot_state_detects_content_change_with_preserved_mtime(tmp_path: Path) -> None:
    """A same-size content rewrite with mtime restored is still detected.

    Regression for mtime-only detection: the signature is content-based, so a
    write that preserves mtime (or lands within the mtime tick) still changes
    the signature.
    """
    import os

    from pydantic_deep.features.forking.isolation import _snapshot_state

    snap = tmp_path / "snap"
    snap.mkdir()
    f = snap / "a.py"
    f.write_text("aaaa")
    st = os.stat(f)
    pre = _snapshot_state(snap)

    # Same byte length, different content, mtime restored to the original.
    f.write_text("bbbb")
    os.utime(f, (st.st_atime, st.st_mtime))
    post = _snapshot_state(snap)

    assert pre["a.py"][1] != post["a.py"][1]


async def test_a_command_sees_branch_edits_over_parent_files(tmp_path: Path) -> None:
    root, overlay = _local(tmp_path)
    (root / "conf.txt").write_text("parent")
    (root / "d").mkdir()
    (root / "d" / "inner.txt").write_text("i")
    await overlay.write_bytes(str(root / "conf.txt"), b"branch")
    await overlay.write_bytes(str(root / "d" / "inner.txt"), b"edited")
    await overlay.write_bytes(str(root / "scratch.txt"), b"s")
    await overlay.remove(str(root / "scratch.txt"))
    await overlay.remove(str(root / "d"))

    result = await Workspace(overlay).run("cat conf.txt; ls", shell=True)

    assert result.stdout.startswith("branch")
    assert "scratch.txt" not in result.stdout and "d\n" not in result.stdout


def test_snapshot_without_a_virtualenv_adds_none(tmp_path: Path) -> None:
    root, overlay = _local(tmp_path)
    with overlay.snapshot(root, include_venv=True) as snap:
        assert not (Path(snap) / ".venv").exists()


async def test_a_write_after_a_flushed_removal_is_applied() -> None:
    parent = state_workspace()
    overlay = BranchOverlay(parent)
    await overlay.write_bytes("/a.py", b"1")
    await overlay.write_bytes("/b.py", b"2")
    report = await overlay.flush_to(parent)
    assert report.applied_paths == ["/a.py", "/b.py"] and report.deleted_paths == []


async def test_a_removal_recorded_twice_is_reported_once() -> None:
    parent = state_workspace({"/x.py": "v0"})
    overlay = BranchOverlay(parent)
    overlay._record_removal("/x.py", op="delete")
    overlay._record_removal("/x.py", op="delete")
    report = await overlay.flush_to(parent)
    assert report.deleted_paths == ["/x.py"] and report.applied_changes == 2
