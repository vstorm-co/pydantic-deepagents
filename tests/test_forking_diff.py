"""Live Run Forking — diff explorer tests (issue #103)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, cast

import pytest
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models.test import TestModel
from pydantic_ai_backends import StateBackend

from pydantic_deep import (
    BranchChange,
    BranchDiffReport,
    BranchIsolation,
    BranchOverlay,
    BranchSpec,
    DeepAgentDeps,
    ForkCoordinator,
    InMemoryForkStateStore,
    LiveForkCapability,
    create_deep_agent,
)
from pydantic_deep.features.forking import NOT_ENABLED_MESSAGE, create_fork_toolset
from pydantic_deep.features.forking.coordinator import BranchRuntime
from pydantic_deep.features.forking.diff import (
    _binary_placeholder,
    _change_identity,
    _classify_agreement,
    _decode_text,
    _is_binary_bytes,
    build_diff_report,
)
from pydantic_deep.features.forking.types import BranchStatus


def _make_status(branch_id: str, label: str) -> BranchStatus:
    return BranchStatus(
        id=branch_id,
        label=label,
        state="running",
        current_turn=0,
        last_activity_at=datetime.now(timezone.utc),
    )


async def _make_runtime(
    *,
    branch_id: str,
    label: str,
    overlay: BranchOverlay | None,
) -> BranchRuntime:
    """Build a minimal :class:`BranchRuntime` with throwaway spec/task/deps.

    The diff builder only reads `runtime.overlay` and
    `runtime.status`; the other fields are stubbed to keep tests fast
    and isolated from the agent run loop.
    """

    async def _noop() -> None:
        return None

    task = asyncio.create_task(_noop())
    await task  # drain immediately so the test doesn't leak running tasks
    return BranchRuntime(
        spec=BranchSpec(label=label, steer=""),
        task=task,
        deps=cast(DeepAgentDeps, object()),
        overlay=overlay,
        status=_make_status(branch_id, label),
    )


async def _overlay_with_writes(
    parent: StateBackend,
    writes: dict[str, str | bytes],
) -> BranchOverlay:
    overlay = BranchOverlay(parent)
    for path, content in writes.items():
        overlay.write(path, content)
    return overlay


# ---------------------------------------------------------------------------
# 1. Same path modified differently in all branches → agreement="split"
# ---------------------------------------------------------------------------


async def test_diff_split_when_branches_modify_same_path_differently() -> None:
    parent = StateBackend()
    parent.write("foo.py", "parent\n")

    overlay_a = await _overlay_with_writes(parent, {"foo.py": "branch-a\n"})
    overlay_b = await _overlay_with_writes(parent, {"foo.py": "branch-b\n"})

    runtime_a = await _make_runtime(branch_id="a", label="alpha", overlay=overlay_a)
    runtime_b = await _make_runtime(branch_id="b", label="beta", overlay=overlay_b)

    report = await build_diff_report("fork-1", [runtime_a, runtime_b])

    assert len(report.paths) == 1
    pd = report.paths[0]
    assert pd.path == "foo.py"
    assert pd.agreement == "split"
    assert pd.parent_content == "parent\n"
    assert pd.branches["a"].new_content == "branch-a\n"
    assert pd.branches["b"].new_content == "branch-b\n"
    assert "branch-a" in pd.branches["a"].unified_diff_vs_parent
    assert "branch-b" in pd.branches["b"].unified_diff_vs_parent
    assert report.summary.split_paths == 1
    assert report.summary.unanimous_paths == 0
    assert report.summary.agreement_score == 0.0


# ---------------------------------------------------------------------------
# 2. Same path modified identically in all branches → agreement="unanimous_change"
# ---------------------------------------------------------------------------


async def test_diff_unanimous_change_when_branches_modify_identically() -> None:
    parent = StateBackend()
    parent.write("shared.py", "v1\n")

    overlay_a = await _overlay_with_writes(parent, {"shared.py": "v2\n"})
    overlay_b = await _overlay_with_writes(parent, {"shared.py": "v2\n"})

    report = await build_diff_report(
        "fork-2",
        [
            await _make_runtime(branch_id="a", label="alpha", overlay=overlay_a),
            await _make_runtime(branch_id="b", label="beta", overlay=overlay_b),
        ],
    )

    assert report.paths[0].agreement == "unanimous_change"
    assert report.summary.unanimous_paths == 1
    assert report.summary.split_paths == 0
    assert report.summary.agreement_score == 1.0


# ---------------------------------------------------------------------------
# 3. Path touched only by one branch → agreement="unique"
# ---------------------------------------------------------------------------


async def test_diff_unique_when_only_one_branch_touches_path() -> None:
    parent = StateBackend()
    parent.write("base.py", "x\n")

    overlay_a = await _overlay_with_writes(parent, {"only-a.py": "hello\n"})
    overlay_b = BranchOverlay(parent)  # b touched nothing

    report = await build_diff_report(
        "fork-3",
        [
            await _make_runtime(branch_id="a", label="alpha", overlay=overlay_a),
            await _make_runtime(branch_id="b", label="beta", overlay=overlay_b),
        ],
    )

    assert len(report.paths) == 1
    pd = report.paths[0]
    assert pd.path == "only-a.py"
    assert pd.agreement == "unique"
    assert pd.parent_content is None
    assert pd.branches["a"].operation == "created"
    assert pd.branches["b"].operation == "untouched"
    assert report.summary.per_branch_unique == {"a": 1, "b": 0}


# ---------------------------------------------------------------------------
# 4. Binary file → is_binary=True, placeholder content, no unified diff
# ---------------------------------------------------------------------------


async def test_diff_binary_file_returns_placeholder() -> None:
    parent = StateBackend()
    binary_payload = b"\x00\x01\x02\x03" * 64
    overlay_a = await _overlay_with_writes(parent, {"asset.bin": binary_payload})

    report = await build_diff_report(
        "fork-4",
        [await _make_runtime(branch_id="a", label="alpha", overlay=overlay_a)],
    )

    pd = report.paths[0]
    branch_a = pd.branches["a"]
    assert branch_a.is_binary is True
    assert branch_a.new_content is None
    assert branch_a.unified_diff_vs_parent.startswith("[binary · ")
    assert "sha256:" in branch_a.unified_diff_vs_parent
    assert branch_a.size_bytes == len(binary_payload)


async def test_diff_divergent_binary_writes_are_split() -> None:
    """Two branches writing DIFFERENT binary bytes to one path → 'split', not agreement.

    Regression: binary changes carry new_content=None, so classification keyed on
    new_content alone mislabelled divergent binary writes as unanimous_change.
    """
    parent = StateBackend()
    overlay_a = await _overlay_with_writes(parent, {"asset.bin": b"\x00\x01\x02" * 64})
    overlay_b = await _overlay_with_writes(parent, {"asset.bin": b"\x00\x09\x09" * 64})

    report = await build_diff_report(
        "fork-bin",
        [
            await _make_runtime(branch_id="a", label="alpha", overlay=overlay_a),
            await _make_runtime(branch_id="b", label="beta", overlay=overlay_b),
        ],
    )

    pd = next(p for p in report.paths if p.path == "asset.bin")
    assert pd.branches["a"].is_binary is True
    assert pd.branches["b"].is_binary is True
    assert pd.agreement == "split"


async def test_diff_identical_binary_writes_are_unanimous() -> None:
    """Two branches writing the SAME binary bytes → unanimous_change (true agreement)."""
    parent = StateBackend()
    payload = b"\x00\x07\x07" * 64
    overlay_a = await _overlay_with_writes(parent, {"asset.bin": payload})
    overlay_b = await _overlay_with_writes(parent, {"asset.bin": payload})

    report = await build_diff_report(
        "fork-bin2",
        [
            await _make_runtime(branch_id="a", label="alpha", overlay=overlay_a),
            await _make_runtime(branch_id="b", label="beta", overlay=overlay_b),
        ],
    )

    pd = next(p for p in report.paths if p.path == "asset.bin")
    assert pd.agreement == "unanimous_change"


def _binary_change(
    branch_id: str,
    *,
    placeholder: str,
    digest: str | None,
) -> BranchChange:
    return BranchChange(
        branch_id=branch_id,
        branch_label=branch_id,
        operation="created",
        new_content=None,
        unified_diff_vs_parent=placeholder,
        size_bytes=0,
        is_binary=True,
        binary_sha256=digest,
    )


def test_binary_change_identity_uses_full_digest_not_truncated_placeholder() -> None:
    """Bug 83: distinct binaries sharing the 12-hex placeholder must not agree.

    Two binaries of equal length whose sha256 collides in the first 48 bits
    would share an identical human-readable placeholder. Classification keyed
    on that placeholder would mislabel them as agreement; keying on the FULL
    sha256 digest keeps them 'split'.
    """
    shared_placeholder = "[binary · 192 · sha256:deadbeefcafe]"
    change_a = _binary_change("a", placeholder=shared_placeholder, digest="deadbeefcafe" + "0" * 52)
    change_b = _binary_change("b", placeholder=shared_placeholder, digest="deadbeefcafe" + "1" * 52)

    # Placeholders collide, but the full-digest identity diverges.
    assert change_a.unified_diff_vs_parent == change_b.unified_diff_vs_parent
    assert _change_identity(change_a) != _change_identity(change_b)
    assert _classify_agreement({"a": change_a, "b": change_b}) == "split"


def test_binary_change_identity_agrees_on_matching_full_digest() -> None:
    """Identical full digests classify as agreement even with a shared placeholder."""
    placeholder = "[binary · 192 · sha256:deadbeefcafe]"
    digest = "deadbeefcafe" + "0" * 52
    change_a = _binary_change("a", placeholder=placeholder, digest=digest)
    change_b = _binary_change("b", placeholder=placeholder, digest=digest)

    assert _change_identity(change_a) == _change_identity(change_b)
    assert _classify_agreement({"a": change_a, "b": change_b}) == "unanimous_change"


def test_binary_placeholder_accepts_precomputed_digest() -> None:
    """`_binary_placeholder` reuses a precomputed digest and equals the implicit hash."""
    import hashlib

    data = b"\x00\x01\x02" * 8
    full = hashlib.sha256(data).hexdigest()
    assert _binary_placeholder(data, digest=full) == _binary_placeholder(data)
    assert full[:12] in _binary_placeholder(data, digest=full)


async def test_build_diff_report_rejects_duplicate_status_ids() -> None:
    """Bug 84: duplicate runtime status ids would clobber per-branch maps."""
    parent = StateBackend()
    overlay_a = await _overlay_with_writes(parent, {"foo.py": "a\n"})
    overlay_b = await _overlay_with_writes(parent, {"foo.py": "b\n"})
    runtime_a = await _make_runtime(branch_id="dup", label="alpha", overlay=overlay_a)
    runtime_b = await _make_runtime(branch_id="dup", label="beta", overlay=overlay_b)
    with pytest.raises(ValueError, match="unique runtime status ids"):
        await build_diff_report("fork-dup", [runtime_a, runtime_b])


def test_decode_text_returns_none_for_invalid_utf8() -> None:
    """Unit test: `_decode_text` returns None for non-UTF-8 bytes.

    Covers the failure path that callers map to `new_content=None` or
    parent_content=None. Tested at the helper boundary because
    `StateBackend` normalises bytes through `errors="replace"` and
    therefore never feeds invalid UTF-8 into the higher-level builder.
    """
    assert _decode_text(b"\xff\xfe latin1") is None
    assert _decode_text(b"plain ascii") == "plain ascii"


def test_is_binary_bytes_threshold() -> None:
    """Null bytes outside the first 8 KB are not classified binary."""
    assert _is_binary_bytes(b"\x00 short") is True
    assert _is_binary_bytes(b"a" * 9000 + b"\x00") is False


# ---------------------------------------------------------------------------
# 5. File >500 lines → truncated unified diff with elision marker
# ---------------------------------------------------------------------------


async def test_diff_large_file_truncated() -> None:
    parent = StateBackend()
    parent.write("big.py", "")
    big_content = "\n".join(f"line {i}" for i in range(700)) + "\n"
    overlay_a = await _overlay_with_writes(parent, {"big.py": big_content})

    report = await build_diff_report(
        "fork-5",
        [await _make_runtime(branch_id="a", label="alpha", overlay=overlay_a)],
    )

    diff_text = report.paths[0].branches["a"].unified_diff_vs_parent
    assert "lines truncated" in diff_text


# ---------------------------------------------------------------------------
# 6. paths filter limits report to specified paths only
# ---------------------------------------------------------------------------


async def test_diff_respects_paths_filter() -> None:
    parent = StateBackend()
    overlay_a = await _overlay_with_writes(parent, {"keep.py": "x\n", "ignore.py": "y\n"})

    report = await build_diff_report(
        "fork-6",
        [await _make_runtime(branch_id="a", label="alpha", overlay=overlay_a)],
        paths_filter=["keep.py"],
    )

    reported_paths = [pd.path for pd in report.paths]
    assert reported_paths == ["keep.py"]


async def test_diff_paths_filter_keeps_untouched_paths_for_transparency() -> None:
    parent = StateBackend()
    overlay_a = await _overlay_with_writes(parent, {"touched.py": "y\n"})

    report = await build_diff_report(
        "fork-6b",
        [await _make_runtime(branch_id="a", label="alpha", overlay=overlay_a)],
        paths_filter=["never-touched.py"],
    )

    assert [pd.path for pd in report.paths] == ["never-touched.py"]
    assert report.paths[0].agreement == "unanimous_no_change"
    # total_paths_touched reflects the union of branches' actual touches,
    # not the filter — keeps agreement_score meaningful.
    assert report.summary.total_paths_touched == 1


async def test_diff_agreement_score_not_falsely_perfect_when_split_filtered_out() -> None:
    """Filtering out a genuinely-conflicting path must NOT inflate agreement_score.

    Regression: split_paths was counted over the filtered set while the
    denominator was the full union, so filtering away a real split path yielded
    agreement_score == 1.0 ("perfect agreement") despite the branches conflicting.
    """
    parent = StateBackend()
    overlay_a = await _overlay_with_writes(parent, {"conflict.py": "alpha\n"})
    overlay_b = await _overlay_with_writes(parent, {"conflict.py": "beta\n"})

    report = await build_diff_report(
        "fork-6c",
        [
            await _make_runtime(branch_id="a", label="alpha", overlay=overlay_a),
            await _make_runtime(branch_id="b", label="beta", overlay=overlay_b),
        ],
        # Hide the conflicting path from the displayed diff.
        paths_filter=["unrelated.py"],
    )

    # The conflict path is not shown ...
    assert [pd.path for pd in report.paths] == ["unrelated.py"]
    # ... but the metric still reflects the real conflict (scored over the full union).
    assert report.summary.split_paths == 1
    assert report.summary.total_paths_touched == 1
    assert report.summary.agreement_score == 0.0


# ---------------------------------------------------------------------------
# 7. agreement_score arithmetic across mixed scenarios
# ---------------------------------------------------------------------------


async def test_diff_agreement_score_all_split() -> None:
    parent = StateBackend()
    parent.write("p1.py", "x\n")
    parent.write("p2.py", "y\n")
    overlay_a = await _overlay_with_writes(parent, {"p1.py": "a1\n", "p2.py": "a2\n"})
    overlay_b = await _overlay_with_writes(parent, {"p1.py": "b1\n", "p2.py": "b2\n"})

    report = await build_diff_report(
        "fork-7a",
        [
            await _make_runtime(branch_id="a", label="alpha", overlay=overlay_a),
            await _make_runtime(branch_id="b", label="beta", overlay=overlay_b),
        ],
    )
    assert report.summary.split_paths == 2
    assert report.summary.agreement_score == 0.0


async def test_diff_agreement_score_all_unanimous() -> None:
    parent = StateBackend()
    parent.write("p1.py", "x\n")
    overlay_a = await _overlay_with_writes(parent, {"p1.py": "same\n"})
    overlay_b = await _overlay_with_writes(parent, {"p1.py": "same\n"})

    report = await build_diff_report(
        "fork-7b",
        [
            await _make_runtime(branch_id="a", label="alpha", overlay=overlay_a),
            await _make_runtime(branch_id="b", label="beta", overlay=overlay_b),
        ],
    )
    assert report.summary.agreement_score == 1.0


async def test_diff_agreement_score_mixed() -> None:
    parent = StateBackend()
    parent.write("p1.py", "x\n")
    parent.write("p2.py", "y\n")
    parent.write("p3.py", "z\n")

    overlay_a = await _overlay_with_writes(
        parent, {"p1.py": "same\n", "p2.py": "same\n", "p3.py": "a3\n"}
    )
    overlay_b = await _overlay_with_writes(
        parent, {"p1.py": "same\n", "p2.py": "same\n", "p3.py": "b3\n"}
    )

    report = await build_diff_report(
        "fork-7c",
        [
            await _make_runtime(branch_id="a", label="alpha", overlay=overlay_a),
            await _make_runtime(branch_id="b", label="beta", overlay=overlay_b),
        ],
    )
    # 3 paths total, 1 split → score = 1 - 1/3 = 2/3
    assert report.summary.total_paths_touched == 3
    assert report.summary.split_paths == 1
    assert report.summary.unanimous_paths == 2
    assert report.summary.agreement_score == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# 8. Deletion classification — unit test of the classifier
# ---------------------------------------------------------------------------


def test_diff_classifies_deletion_as_split() -> None:
    """When one branch deletes and another keeps the file, the classifier returns 'split'."""
    deleted_change = BranchChange(
        branch_id="a",
        branch_label="alpha",
        operation="deleted",
        new_content=None,
        unified_diff_vs_parent="--- a/x.py\n+++ b/x.py\n@@ -1 +0,0 @@\n-x\n",
        size_bytes=0,
        is_binary=False,
    )
    kept_change = BranchChange(
        branch_id="b",
        branch_label="beta",
        operation="modified",
        new_content="x-modified\n",
        unified_diff_vs_parent="",
        size_bytes=11,
        is_binary=False,
    )
    untouched = BranchChange(
        branch_id="c",
        branch_label="gamma",
        operation="untouched",
        new_content=None,
        unified_diff_vs_parent="",
        size_bytes=0,
        is_binary=False,
    )

    assert _classify_agreement({"a": deleted_change, "b": kept_change, "c": untouched}) == "split"


# ---------------------------------------------------------------------------
# 9. File untouched by any branch and not in paths filter → excluded
# ---------------------------------------------------------------------------


async def test_diff_untouched_paths_excluded() -> None:
    parent = StateBackend()
    parent.write("untouched.py", "stays\n")  # exists in parent but neither branch touches

    overlay_a = await _overlay_with_writes(parent, {"changed.py": "new\n"})
    overlay_b = BranchOverlay(parent)

    report = await build_diff_report(
        "fork-9",
        [
            await _make_runtime(branch_id="a", label="alpha", overlay=overlay_a),
            await _make_runtime(branch_id="b", label="beta", overlay=overlay_b),
        ],
    )

    reported_paths = [pd.path for pd in report.paths]
    assert reported_paths == ["changed.py"]
    assert "untouched.py" not in reported_paths


# ---------------------------------------------------------------------------
# Coverage edge: branch with no overlay (BranchIsolation.backend="share")
# ---------------------------------------------------------------------------


async def test_diff_branch_with_no_overlay_marked_untouched() -> None:
    parent = StateBackend()
    overlay_a = await _overlay_with_writes(parent, {"foo.py": "a-content\n"})

    report = await build_diff_report(
        "fork-share",
        [
            await _make_runtime(branch_id="a", label="alpha", overlay=overlay_a),
            await _make_runtime(branch_id="shared", label="shared", overlay=None),
        ],
    )

    pd = report.paths[0]
    assert pd.branches["shared"].operation == "untouched"
    assert report.summary.per_branch_unique == {"a": 1, "shared": 0}


# ---------------------------------------------------------------------------
# Coverage edge: no branches touched anything
# ---------------------------------------------------------------------------


async def test_diff_all_branches_no_overlay_with_filter() -> None:
    """All runtimes have `overlay=None` → parent_backend stays None inside the loop.

    Exercises the `parent_backend is None` fall-through inside the path
    loop — only reachable when a `paths_filter` forces at least one
    iteration even though no branch has an overlay.
    """
    report = await build_diff_report(
        "fork-noparent",
        [
            await _make_runtime(branch_id="a", label="alpha", overlay=None),
            await _make_runtime(branch_id="b", label="beta", overlay=None),
        ],
        paths_filter=["forced/path.py"],
    )
    assert len(report.paths) == 1
    pd = report.paths[0]
    assert pd.parent_content is None
    assert pd.agreement == "unanimous_no_change"


async def test_diff_unique_when_first_branch_is_untouched() -> None:
    """Dict-order trick: untouched branch listed first → loop skips it before breaking.

    Covers the `continue past untouched` branch in `per_branch_unique`
    accumulation, which a straightforward dict where the touched branch
    is inserted first would never hit.
    """
    parent = StateBackend()
    overlay_b = await _overlay_with_writes(parent, {"owned.py": "b!\n"})

    # Insert the untouched runtime FIRST so the unique-tally loop must skip it.
    report = await build_diff_report(
        "fork-unique-order",
        [
            await _make_runtime(branch_id="a", label="alpha", overlay=None),
            await _make_runtime(branch_id="b", label="beta", overlay=overlay_b),
        ],
    )
    pd = report.paths[0]
    assert pd.agreement == "unique"
    assert report.summary.per_branch_unique == {"a": 0, "b": 1}


async def test_diff_no_branches_touched_anything() -> None:
    parent = StateBackend()
    overlay_a = BranchOverlay(parent)
    overlay_b = BranchOverlay(parent)

    report = await build_diff_report(
        "fork-empty",
        [
            await _make_runtime(branch_id="a", label="alpha", overlay=overlay_a),
            await _make_runtime(branch_id="b", label="beta", overlay=overlay_b),
        ],
    )

    assert report.paths == []
    assert report.summary.total_paths_touched == 0
    assert report.summary.agreement_score == 1.0


# ---------------------------------------------------------------------------
# Coverage edge: empty runtimes list (defensive — exercises the union default)
# ---------------------------------------------------------------------------


async def test_diff_empty_runtimes_list() -> None:
    report = await build_diff_report("fork-noop", [])
    assert report.paths == []
    assert report.summary.total_paths_touched == 0
    assert report.summary.agreement_score == 1.0


# ---------------------------------------------------------------------------
# build_diff_report — `operation="deleted"` rendering for recorded deletes
# ---------------------------------------------------------------------------


async def test_diff_branch_with_delete_produces_deleted_operation() -> None:
    parent = StateBackend()
    parent.write("/x.py", "v0-line1\nv0-line2\n")

    overlay_deleter = BranchOverlay(parent)
    overlay_deleter.delete("/x.py")

    overlay_modifier = BranchOverlay(parent)
    overlay_modifier.write("/x.py", "modified\n")

    report = await build_diff_report(
        "fork-delete",
        [
            await _make_runtime(branch_id="a", label="alpha", overlay=overlay_deleter),
            await _make_runtime(branch_id="b", label="beta", overlay=overlay_modifier),
        ],
    )

    assert len(report.paths) == 1
    pd = report.paths[0]
    assert pd.path == "/x.py"
    deleter_change = pd.branches["a"]
    assert deleter_change.operation == "deleted"
    assert deleter_change.new_content is None
    assert deleter_change.size_bytes == 0
    assert deleter_change.is_binary is False
    # The unified diff against /dev/null shows parent lines removed.
    assert "/dev/null" in deleter_change.unified_diff_vs_parent
    assert "-v0-line1" in deleter_change.unified_diff_vs_parent
    # Different operations across branches → split.
    assert pd.agreement == "split"


async def test_diff_lone_deleter_branch_classified_unique() -> None:
    parent = StateBackend()
    parent.write("/x.py", "v0\n")

    overlay_deleter = BranchOverlay(parent)
    overlay_deleter.delete("/x.py")

    overlay_untouched = BranchOverlay(parent)

    report = await build_diff_report(
        "fork-lone-delete",
        [
            await _make_runtime(branch_id="a", label="alpha", overlay=overlay_deleter),
            await _make_runtime(branch_id="b", label="beta", overlay=overlay_untouched),
        ],
    )

    assert report.paths[0].agreement == "unique"
    assert report.paths[0].branches["a"].operation == "deleted"
    assert report.paths[0].branches["b"].operation == "untouched"


async def test_diff_unanimous_delete_classified_as_unanimous_change() -> None:
    parent = StateBackend()
    parent.write("/x.py", "v0\n")

    overlay_a = BranchOverlay(parent)
    overlay_a.delete("/x.py")
    overlay_b = BranchOverlay(parent)
    overlay_b.delete("/x.py")

    report = await build_diff_report(
        "fork-unanimous-delete",
        [
            await _make_runtime(branch_id="a", label="alpha", overlay=overlay_a),
            await _make_runtime(branch_id="b", label="beta", overlay=overlay_b),
        ],
    )

    assert report.paths[0].agreement == "unanimous_change"
    assert all(bc.operation == "deleted" for bc in report.paths[0].branches.values())


# ---------------------------------------------------------------------------
# Coverage edge: parent contains a binary file (resolve_parent → bytes only)
# ---------------------------------------------------------------------------


async def test_diff_binary_parent_content() -> None:
    parent = StateBackend()
    parent.write("img.bin", b"\x00\x01" * 32)
    overlay_a = await _overlay_with_writes(parent, {"img.bin": b"\x00\x02" * 32})

    report = await build_diff_report(
        "fork-binparent",
        [await _make_runtime(branch_id="a", label="alpha", overlay=overlay_a)],
    )

    pd = report.paths[0]
    # Parent is binary → parent_content stays None even though file exists in parent.
    assert pd.parent_content is None
    assert pd.branches["a"].is_binary is True


# ---------------------------------------------------------------------------
# Tool integration helpers — shared fixture (DEENUU1 P9: deduplicate setup)
# ---------------------------------------------------------------------------


def _make_test_agent() -> Agent[DeepAgentDeps, str]:
    return Agent(TestModel(), deps_type=DeepAgentDeps)


def _seed_history(text: str) -> list[Any]:
    return [ModelRequest(parts=[UserPromptPart(content=text)])]


def _make_tool_ctx(deps: DeepAgentDeps) -> RunContext[DeepAgentDeps]:
    """Build a minimal `RunContext` for invoking a tool function directly.

    `RunContext` has no public test factory; `__new__` produces an
    uninitialised instance whose only used attribute is `deps`. Anything
    else accessed on the returned context will `AttributeError` — the
    tests only exercise the `ctx.deps` path.
    """
    ctx = cast(Any, RunContext.__new__(RunContext))
    ctx.deps = deps
    return cast(RunContext[DeepAgentDeps], ctx)


async def _make_coord_with_fork(
    *,
    with_handle: bool = True,
) -> tuple[DeepAgentDeps, ForkCoordinator, Any]:
    """Build a wired DeepAgentDeps + ForkCoordinator pair for tool-level tests.

    Returns `(deps, coordinator, handle)` — `handle` is `None` when
    `with_handle=False` (caller wants a coordinator that has not yet forked).
    """
    agent = _make_test_agent()
    deps = DeepAgentDeps(backend=StateBackend())
    coordinator = ForkCoordinator(
        agent=agent,
        parent_deps=deps,
        max_branches=2,
        max_depth=1,
        store=InMemoryForkStateStore(),
    )
    deps.fork_coordinator = coordinator
    handle = None
    if with_handle:
        handle = await coordinator.fork(
            [BranchSpec(label="alpha", steer="hi"), BranchSpec(label="beta", steer="hello")],
            parent_history=_seed_history("user-msg"),
            isolation=BranchIsolation(),
        )
    return deps, coordinator, handle


def _diff_tool_from(toolset: Any) -> Any:
    """Pull the `diff_branches` tool function out of a forking toolset.

    Centralises the `toolset.tools` access — `tools` is a public
    attribute on `FunctionToolset` but not on the `AbstractToolset`
    base, so callers iterating `agent.toolsets` need to narrow the type.
    """
    return toolset.tools["diff_branches"]


async def _drain_branch_tasks(coordinator: ForkCoordinator) -> None:
    """Cancel and await every branch task so tests don't leak background work."""
    await coordinator.aclose()
    await asyncio.gather(
        *(rt.task for rt in coordinator.branches.values()),
        return_exceptions=True,
    )


# ---------------------------------------------------------------------------
# Tool integration tests
# ---------------------------------------------------------------------------


async def test_diff_tool_wrong_fork_id_returns_error() -> None:
    deps, coordinator, handle = await _make_coord_with_fork()
    diff_tool = _diff_tool_from(create_fork_toolset())

    result = await diff_tool.function(_make_tool_ctx(deps), "not-the-fork", None)
    assert isinstance(result, str)
    assert "does not match" in result
    assert handle.fork_id in result

    await _drain_branch_tasks(coordinator)


async def test_diff_tool_no_active_fork_returns_error() -> None:
    deps, _coordinator, _ = await _make_coord_with_fork(with_handle=False)
    diff_tool = _diff_tool_from(create_fork_toolset())

    result = await diff_tool.function(_make_tool_ctx(deps), "any-id", None)
    assert isinstance(result, str)
    assert "no active fork" in result


async def test_diff_tool_when_forking_disabled() -> None:
    deps = DeepAgentDeps(backend=StateBackend())  # fork_coordinator stays None
    diff_tool = _diff_tool_from(create_fork_toolset())

    result = await diff_tool.function(_make_tool_ctx(deps), "any-id", None)
    assert result == NOT_ENABLED_MESSAGE


async def test_diff_tool_returns_typed_report_on_success() -> None:
    """End-to-end: real coordinator + overlays → tool returns BranchDiffReport."""
    deps, coordinator, handle = await _make_coord_with_fork()
    coordinator.capability = LiveForkCapability()

    # Drive overlays directly — TestModel-driven branch tasks finish on
    # their own; we don't await them here, instead seeding overlay state
    # manually for deterministic assertions.
    for rt in coordinator.branches.values():
        assert rt.overlay is not None
        rt.overlay.write("hello.py", f"hi from {rt.spec.label}\n")

    diff_tool = _diff_tool_from(create_fork_toolset())
    result = await diff_tool.function(_make_tool_ctx(deps), handle.fork_id, None)

    assert isinstance(result, BranchDiffReport)
    assert result.fork_id == handle.fork_id
    assert len(result.paths) == 1
    assert result.paths[0].path == "hello.py"
    assert result.paths[0].agreement == "split"

    await _drain_branch_tasks(coordinator)


# ---------------------------------------------------------------------------
# Public build_diff_report — documented entry point used by the CLI, judge, and docs
# ---------------------------------------------------------------------------


async def test_public_build_diff_report_entry_point() -> None:
    """`build_diff_report` is re-exported and produces the same report shape."""
    from pydantic_deep import build_diff_report

    parent = StateBackend()
    overlay_a = await _overlay_with_writes(parent, {"foo.py": "a\n"})
    overlay_b = await _overlay_with_writes(parent, {"foo.py": "b\n"})

    report = await build_diff_report(
        "fork-public",
        [
            await _make_runtime(branch_id="a", label="alpha", overlay=overlay_a),
            await _make_runtime(branch_id="b", label="beta", overlay=overlay_b),
        ],
    )
    assert isinstance(report, BranchDiffReport)
    assert report.summary.split_paths == 1


# ---------------------------------------------------------------------------
# create_deep_agent integration — diff_branches tool actually works end-to-end
# ---------------------------------------------------------------------------


async def test_diff_branches_tool_wired_through_create_deep_agent() -> None:
    """The `forking=True` wiring path produces a working `diff_branches` tool.

    Goes beyond a registration check — finds the registered
    `LiveForkCapability` instance, simulates `for_run` to allocate a
    coordinator, then invokes the registered `diff_branches` tool and
    asserts it returns a typed :class:`BranchDiffReport`.

    Avoids `agent.run` because `TestModel` auto-calls every registered
    tool with stub payloads, which makes `fork_run` raise on the warmup.
    Simulating `for_run` directly is the smallest test surface that still
    proves the full wiring chain works.
    """
    agent = create_deep_agent(model=TestModel(), forking=True)

    forking_toolset = None
    for ts in agent.toolsets:
        if getattr(ts, "id", None) == "deep-forking":
            # FunctionToolset.tools is public; the base AbstractToolset doesn't
            # declare it, so the iteration narrows away the attribute. Cast.
            forking_toolset = cast(Any, ts)
            break
    assert forking_toolset is not None, "deep-forking toolset must be registered"
    assert "diff_branches" in forking_toolset.tools

    # Locate the LiveForkCapability that create_deep_agent registered, then
    # ask it to allocate a per-run coordinator on our test deps.
    from pydantic_ai.capabilities import CombinedCapability

    root = agent.root_capability
    capabilities_iter = root.capabilities if isinstance(root, CombinedCapability) else [root]
    fork_cap: LiveForkCapability | None = None
    for cap in capabilities_iter:
        if isinstance(cap, LiveForkCapability):
            fork_cap = cap
            break
    assert fork_cap is not None, "LiveForkCapability must be registered on agent"

    deps = DeepAgentDeps(backend=StateBackend())
    await fork_cap.for_run(_make_tool_ctx(deps))
    coordinator = deps.fork_coordinator
    assert coordinator is not None

    handle = await coordinator.fork(
        [BranchSpec(label="alpha", steer="x"), BranchSpec(label="beta", steer="y")],
        parent_history=_seed_history("warmup"),
        isolation=BranchIsolation(),
    )
    for rt in coordinator.branches.values():
        assert rt.overlay is not None
        rt.overlay.write("readme.md", f"# {rt.spec.label}\n")

    diff_tool = _diff_tool_from(forking_toolset)
    result = await diff_tool.function(_make_tool_ctx(deps), handle.fork_id, None)
    assert isinstance(result, BranchDiffReport)
    assert result.fork_id == handle.fork_id
    assert any(pd.path == "readme.md" for pd in result.paths)

    await _drain_branch_tasks(coordinator)
