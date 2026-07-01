"""Diff builder over fork branches.

Produces a typed :class:`BranchDiffReport` by walking each branch's
:class:`~pydantic_deep.toolsets.forking.isolation.BranchOverlay` changes,
grouping them by path, and rendering unified diffs against the shared
parent backend. Consumed by the CLI merge picker, IDE bridge, and judge.

The module exposes :func:`build_diff_report` (public) and helpers; the
agent-facing `diff_branches` tool lives in this package's `__init__`
to keep the toolset's tool registry in one file.

**Read consistency.** :func:`build_diff_report` does not acquire the
coordinator's `_lock`. While a branch is still writing, an in-flight
`FileChange` may not yet be visible in `overlay.changes()`. This is
intentional - the diff is a read-only inspection and blocking on the
coordinator lock can starve concurrent writers. The report is therefore
best-effort and may miss writes that complete during report construction.
"""

from __future__ import annotations

import difflib
import hashlib
from typing import TYPE_CHECKING, Protocol

from pydantic_deep._text import create_content_preview
from pydantic_deep.features.forking.types import (
    BranchChange,
    BranchDiffAgreement,
    BranchDiffOperation,
    BranchDiffReport,
    DiffSummary,
    PathDiff,
)

if TYPE_CHECKING:
    from pydantic_deep.features.forking.coordinator import BranchRuntime


class _BytesReadable(Protocol):
    """Minimal sync read surface needed by the diff builder.

    Both ``BackendProtocol`` and ``BranchOverlay`` satisfy this. Using a
    narrow local protocol keeps strict typing happy without depending on
    backend-level method signature quirks.
    """

    def exists(self, path: str) -> bool: ...
    def read_bytes(self, path: str) -> bytes: ...


#: Bytes read from the start of a file when sniffing for binary content.
_BINARY_SNIFF_BYTES: int = 8192

#: Lines threshold above which a unified diff is replaced with a head/tail preview.
_LARGE_DIFF_LINE_THRESHOLD: int = 500

#: Lines preserved at the head/tail of a truncated unified diff.
_TRUNCATE_HEAD_LINES: int = 200
_TRUNCATE_TAIL_LINES: int = 200

#: Hex characters of the sha256 digest surfaced in the binary placeholder.
_BINARY_HASH_PREFIX_HEX_LEN: int = 12


def _is_binary_bytes(data: bytes) -> bool:
    """Return `True` when `data` contains a null byte in its first ~8 KB."""
    return b"\x00" in data[:_BINARY_SNIFF_BYTES]


def _binary_placeholder(data: bytes, *, digest: str | None = None) -> str:
    """Return the `[binary · {size} · sha256:{12 hex}]` placeholder string.

    `digest` may be a precomputed full hex sha256 to avoid hashing twice;
    only its first :data:`_BINARY_HASH_PREFIX_HEX_LEN` chars are displayed.
    """
    full = digest if digest is not None else hashlib.sha256(data).hexdigest()
    return f"[binary · {len(data)} · sha256:{full[:_BINARY_HASH_PREFIX_HEX_LEN]}]"


async def _read_path_bytes(backend: _BytesReadable, path: str) -> bytes | None:
    """Read `path` from `backend` as raw bytes, or `None` if absent.

    Uses ``exists()`` first because some backends (notably ``StateBackend``)
    silently return ``b""`` for missing paths instead of raising.
    """
    if not backend.exists(path):
        return None
    try:
        return backend.read_bytes(path)
    except (FileNotFoundError, KeyError):  # pragma: no cover - defensive
        return None


def _decode_text(data: bytes) -> str | None:
    """Decode `data` as UTF-8 text; return `None` if it isn't valid UTF-8."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _render_unified_diff(
    parent: str | None,
    branch: str | None,
    path: str,
) -> str:
    """Render a stdlib unified diff for one path; empty string when both sides empty."""
    parent_lines = (parent or "").splitlines(keepends=True)
    branch_lines = (branch or "").splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            parent_lines,
            branch_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=3,
        )
    )


def _truncate_unified_diff(diff_text: str) -> str:
    """Cap rendered unified diffs at 500 lines by reusing the eviction preview helper."""
    if diff_text.count("\n") + 1 <= _LARGE_DIFF_LINE_THRESHOLD:
        return diff_text
    return create_content_preview(
        diff_text,
        head_lines=_TRUNCATE_HEAD_LINES,
        tail_lines=_TRUNCATE_TAIL_LINES,
    )


def _change_identity(bc: BranchChange) -> tuple[bool, str | None]:
    """Return a content-identity key for comparing two branch changes.

    Binary changes carry `new_content=None` (raw bytes are never captured),
    so two branches writing *different* bytes to the same path would compare
    equal on `new_content` and be mislabelled as agreement. Use the FULL
    sha256 digest (:attr:`BranchChange.binary_sha256`) as the identity for
    binary changes: the human-readable `unified_diff_vs_parent` placeholder
    keeps only a 12-hex (48-bit) prefix, which can collide across distinct
    binaries of equal length and spuriously read as agreement. Text changes
    use `new_content` directly.
    """
    if bc.is_binary:
        return (True, bc.binary_sha256)
    return (False, bc.new_content)


def _classify_agreement(branches: dict[str, BranchChange]) -> BranchDiffAgreement:
    """Classify a path's per-branch outcomes into one of the four agreement labels."""
    touchers = [bc for bc in branches.values() if bc.operation != "untouched"]
    if not touchers:
        return "unanimous_no_change"
    if len(touchers) == 1:
        return "unique"
    first = touchers[0]
    for other in touchers[1:]:
        if (
            other.operation != first.operation
            or other.is_binary != first.is_binary
            or _change_identity(other) != _change_identity(first)
        ):
            return "split"
    return "unanimous_change"


async def _resolve_parent_content(
    parent_backend: _BytesReadable,
    path: str,
) -> tuple[str | None, bytes | None]:
    """Return `(parent_text_or_none, parent_raw_bytes_or_none)` for a path.

    Binary parent content surfaces as `(None, raw_bytes)` so callers can
    still detect binary status without exposing undecodable bytes through
    the text field of :class:`PathDiff`.
    """
    raw = await _read_path_bytes(parent_backend, path)
    if raw is None:
        return None, None
    if _is_binary_bytes(raw):
        return None, raw
    return _decode_text(raw), raw


async def _build_branch_change(
    *,
    runtime: BranchRuntime,
    path: str,
    touched_paths: set[str],
    parent_text: str | None,
    parent_raw: bytes | None,
) -> BranchChange:
    """Build a single :class:`BranchChange` describing a branch's outcome at `path`."""
    overlay = runtime.overlay
    branch_id = runtime.status.id
    branch_label = runtime.status.label

    if overlay is None or path not in touched_paths:
        return BranchChange(
            branch_id=branch_id,
            branch_label=branch_label,
            operation="untouched",
            new_content=None,
            unified_diff_vs_parent="",
            size_bytes=0,
            is_binary=False,
        )

    if path in overlay.deleted():
        diff_text = "".join(
            difflib.unified_diff(
                (parent_text or "").splitlines(keepends=True),
                [],
                fromfile=f"a/{path}",
                tofile="/dev/null",
                n=3,
            )
        )
        return BranchChange(
            branch_id=branch_id,
            branch_label=branch_label,
            operation="deleted",
            new_content=None,
            unified_diff_vs_parent=_truncate_unified_diff(diff_text),
            size_bytes=0,
            is_binary=False,
        )

    # raise > assert so the invariant guard survives python -O.
    raw = await _read_path_bytes(overlay, path)
    if raw is None:  # pragma: no cover - invariant guard; see comment above
        raise RuntimeError(
            f"overlay recorded a change for {path!r} but its content is missing — "
            f"BranchOverlay contract violated."
        )

    is_binary = _is_binary_bytes(raw)
    operation: BranchDiffOperation = "modified" if parent_raw is not None else "created"

    if is_binary:
        digest = hashlib.sha256(raw).hexdigest()
        placeholder = _binary_placeholder(raw, digest=digest)
        return BranchChange(
            branch_id=branch_id,
            branch_label=branch_label,
            operation=operation,
            new_content=None,
            unified_diff_vs_parent=placeholder,
            size_bytes=len(raw),
            is_binary=True,
            binary_sha256=digest,
        )

    decoded = _decode_text(raw)
    new_text = "" if decoded is None else decoded
    return BranchChange(
        branch_id=branch_id,
        branch_label=branch_label,
        operation=operation,
        new_content=new_text,
        unified_diff_vs_parent=_truncate_unified_diff(
            _render_unified_diff(parent_text, new_text, path)
        ),
        size_bytes=len(raw),
        is_binary=False,
    )


async def build_diff_report(
    fork_id: str,
    runtimes: list[BranchRuntime],
    *,
    paths_filter: list[str] | None = None,
) -> BranchDiffReport:
    """Build a :class:`BranchDiffReport` from a list of branch runtimes.

    This is the public entry point for the diff explorer. The
    agent-facing :func:`diff_branches` tool calls into this; downstream
    consumers (CLI merge picker, judge) call it directly for
    programmatic access.

    Args:
        fork_id: Identifier of the fork being inspected - echoed in the
            report's `fork_id` field.
        runtimes: Branch runtimes to compare; usually `list(coordinator.branches.values())`.
        paths_filter: Optional path list; when provided, only these paths
            appear in the report. Untouched filtered paths surface as
            `agreement="unanimous_no_change"` for transparency.

    Returns:
        A :class:`BranchDiffReport` covering every touched path (or every
        filtered path). See module docstring for read-consistency caveat.
    """
    # Every per-branch map below is keyed on `runtime.status.id`; duplicate
    # ids would silently clobber one branch's touched-set / unique counter with
    # another's. raise > assert so the precondition survives python -O.
    branch_ids = [runtime.status.id for runtime in runtimes]
    if len(set(branch_ids)) != len(branch_ids):
        raise ValueError(
            "build_diff_report requires unique runtime status ids; "
            f"got duplicates in {branch_ids!r}."
        )

    touched_per_branch: dict[str, set[str]] = {}
    for runtime in runtimes:
        overlay = runtime.overlay
        if overlay is None:
            touched_per_branch[runtime.status.id] = set()
            continue
        touched_per_branch[runtime.status.id] = {change.path for change in overlay.changes()}

    union_touched: set[str] = set().union(*touched_per_branch.values()) if runtimes else set()

    report_set = set(paths_filter) if paths_filter is not None else union_touched
    # Summary metrics cover the full touched union regardless of the display filter, so
    # filtering out a conflicting path can't falsely inflate agreement_score.
    paths_to_classify = sorted(union_touched | report_set)

    parent_backend: _BytesReadable | None = None
    for runtime in runtimes:
        if runtime.overlay is not None:
            parent_backend = runtime.overlay.parent
            break

    path_diffs: list[PathDiff] = []
    per_branch_unique: dict[str, int] = {runtime.status.id: 0 for runtime in runtimes}
    unanimous_paths = 0
    split_paths = 0

    for path in paths_to_classify:
        if parent_backend is None:
            parent_text, parent_raw = None, None
        else:
            parent_text, parent_raw = await _resolve_parent_content(parent_backend, path)

        branches_for_path: dict[str, BranchChange] = {}
        for runtime in runtimes:
            change = await _build_branch_change(
                runtime=runtime,
                path=path,
                touched_paths=touched_per_branch[runtime.status.id],
                parent_text=parent_text,
                parent_raw=parent_raw,
            )
            branches_for_path[runtime.status.id] = change

        agreement = _classify_agreement(branches_for_path)

        # PathDiff entries respect the display filter ...
        if path in report_set:
            path_diffs.append(
                PathDiff(
                    path=path,
                    parent_content=parent_text,
                    branches=branches_for_path,
                    agreement=agreement,
                )
            )

        # ... but summary metrics count over the full touched union only.
        if path not in union_touched:
            continue
        if agreement in ("unanimous_change", "unanimous_no_change"):
            unanimous_paths += 1
        elif agreement == "split":
            split_paths += 1
        else:  # agreement == "unique" - the four-value Literal is exhaustive
            for branch_id, change in branches_for_path.items():  # pragma: no branch
                # "unique" guarantees exactly one touched branch - the loop
                # always finds it and breaks; no natural-end exit.
                if change.operation != "untouched":
                    per_branch_unique[branch_id] += 1
                    break

    total_paths_touched = len(union_touched)
    agreement_score = 1.0 - split_paths / max(total_paths_touched, 1)

    summary = DiffSummary(
        total_paths_touched=total_paths_touched,
        unanimous_paths=unanimous_paths,
        split_paths=split_paths,
        per_branch_unique=per_branch_unique,
        agreement_score=agreement_score,
    )

    return BranchDiffReport(fork_id=fork_id, paths=path_diffs, summary=summary)


__all__ = ["build_diff_report"]
