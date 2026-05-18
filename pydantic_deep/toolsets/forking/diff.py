"""Diff builder over fork branches — Stage 2 of Live Run Forking.

Produces a typed :class:`BranchDiffReport` by walking each branch's
:class:`~pydantic_deep.toolsets.forking.isolation.BranchOverlay` changes,
grouping them by path, and rendering unified diffs against the shared
parent backend. Consumed by Stage 3 (CLI merge picker), Stage 5 (IDE
bridge), and Stage 6 (judge).

The module exposes :func:`build_diff_report` (public) and helpers; the
agent-facing ``diff_branches`` tool lives in this package's ``__init__``
to keep the toolset's tool registry in one file (mirrors the Stage 1
pattern).

**Read consistency.** :func:`build_diff_report` does not acquire the
coordinator's ``_lock``. While a branch is still writing, an in-flight
``FileChange`` may not yet be visible in ``overlay.changes()``. This is
intentional — the diff is a read-only inspection and blocking on the
coordinator lock can starve concurrent writers. The report is therefore
best-effort and may miss writes that complete during report construction.
"""

from __future__ import annotations

import difflib
import hashlib
from typing import TYPE_CHECKING, Protocol

from pydantic_deep.processors.eviction import create_content_preview
from pydantic_deep.types import (
    BranchChange,
    BranchDiffAgreement,
    BranchDiffOperation,
    BranchDiffReport,
    DiffSummary,
    PathDiff,
)

if TYPE_CHECKING:
    from pydantic_deep.toolsets.forking.coordinator import BranchRuntime


class _BytesReadable(Protocol):
    """Minimal read surface needed by the diff builder.

    Both ``BackendProtocol`` and ``BranchOverlay`` satisfy this — using a
    narrow local protocol keeps strict typing happy without depending on
    backend-level method signature quirks (e.g. ``grep_raw`` arity).
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
    """Return ``True`` when ``data`` contains a null byte in its first ~8 KB."""
    return b"\x00" in data[:_BINARY_SNIFF_BYTES]


def _binary_placeholder(data: bytes) -> str:
    """Return the ``[binary · {size} · sha256:{12 hex}]`` placeholder string."""
    digest = hashlib.sha256(data).hexdigest()
    return f"[binary · {len(data)} · sha256:{digest[:_BINARY_HASH_PREFIX_HEX_LEN]}]"


def _read_path_bytes(backend: _BytesReadable, path: str) -> bytes | None:
    """Read ``path`` from ``backend`` as raw bytes, or ``None`` if absent.

    Uses ``exists()`` first because some backends (notably ``StateBackend``)
    silently return ``b""`` for missing paths instead of raising — we need
    to distinguish "empty file" from "no file" for the ``operation``
    classification (created vs modified).
    """
    if not backend.exists(path):
        return None
    try:
        return backend.read_bytes(path)
    except (FileNotFoundError, KeyError):  # pragma: no cover - defensive
        return None


def _decode_text(data: bytes) -> str | None:
    """Decode ``data`` as UTF-8 text; return ``None`` if it isn't valid UTF-8."""
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
            or other.new_content != first.new_content
            or other.is_binary != first.is_binary
        ):
            return "split"
    return "unanimous_change"


def _resolve_parent_content(
    parent_backend: _BytesReadable,
    path: str,
) -> tuple[str | None, bytes | None]:
    """Return ``(parent_text_or_none, parent_raw_bytes_or_none)`` for a path.

    Binary parent content surfaces as ``(None, raw_bytes)`` so callers can
    still detect binary status without exposing undecodable bytes through
    the text field of :class:`PathDiff`.
    """
    raw = _read_path_bytes(parent_backend, path)
    if raw is None:
        return None, None
    if _is_binary_bytes(raw):
        return None, raw
    return _decode_text(raw), raw


def _build_branch_change(
    *,
    runtime: BranchRuntime,
    path: str,
    touched_paths: set[str],
    parent_text: str | None,
    parent_raw: bytes | None,
) -> BranchChange:
    """Build a single :class:`BranchChange` describing a branch's outcome at ``path``."""
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

    # Stage 1 ``BranchOverlay`` records a change for every successful write,
    # and has no delete op — so ``_read_path_bytes`` is guaranteed to return
    # bytes here. ``_classify_agreement`` is unit-tested for the deletion case
    # via ``test_diff_classifies_deletion_as_split``; when the overlay grows
    # delete support, this function will need a branch to surface it.
    # ``raise`` rather than ``assert`` so the guard survives ``python -O``.
    raw = _read_path_bytes(overlay, path)
    if raw is None:  # pragma: no cover - invariant guard; see comment above
        raise RuntimeError(
            f"overlay recorded a change for {path!r} but its content is missing — "
            f"BranchOverlay contract violated (no-delete invariant)."
        )

    is_binary = _is_binary_bytes(raw)
    operation: BranchDiffOperation = "modified" if parent_raw is not None else "created"

    if is_binary:
        placeholder = _binary_placeholder(raw)
        return BranchChange(
            branch_id=branch_id,
            branch_label=branch_label,
            operation=operation,
            new_content=None,
            unified_diff_vs_parent=placeholder,
            size_bytes=len(raw),
            is_binary=True,
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


def build_diff_report(
    fork_id: str,
    runtimes: list[BranchRuntime],
    *,
    paths_filter: list[str] | None = None,
) -> BranchDiffReport:
    """Build a :class:`BranchDiffReport` from a list of branch runtimes.

    This is the public entry point for the Stage 2 diff explorer. The
    agent-facing :func:`diff_branches` tool calls into this; downstream
    consumers (Stage 3 CLI, Stage 6 judge) call it directly for
    programmatic access.

    Args:
        fork_id: Identifier of the fork being inspected — echoed in the
            report's ``fork_id`` field.
        runtimes: Branch runtimes to compare; usually ``list(coordinator.branches.values())``.
        paths_filter: Optional path list; when provided, only these paths
            appear in the report. Untouched filtered paths surface as
            ``agreement="unanimous_no_change"`` for transparency.

    Returns:
        A :class:`BranchDiffReport` covering every touched path (or every
        filtered path). See module docstring for read-consistency caveat.
    """
    touched_per_branch: dict[str, set[str]] = {}
    for runtime in runtimes:
        overlay = runtime.overlay
        if overlay is None:
            touched_per_branch[runtime.status.id] = set()
            continue
        touched_per_branch[runtime.status.id] = {change.path for change in overlay.changes()}

    union_touched: set[str] = set().union(*touched_per_branch.values()) if runtimes else set()

    if paths_filter is not None:
        paths_to_report = sorted(set(paths_filter))
    else:
        paths_to_report = sorted(union_touched)

    parent_backend: _BytesReadable | None = None
    for runtime in runtimes:
        if runtime.overlay is not None:
            parent_backend = runtime.overlay.parent
            break

    path_diffs: list[PathDiff] = []
    per_branch_unique: dict[str, int] = {runtime.status.id: 0 for runtime in runtimes}
    unanimous_paths = 0
    split_paths = 0

    for path in paths_to_report:
        if parent_backend is None:
            parent_text, parent_raw = None, None
        else:
            parent_text, parent_raw = _resolve_parent_content(parent_backend, path)

        branches_for_path: dict[str, BranchChange] = {}
        for runtime in runtimes:
            change = _build_branch_change(
                runtime=runtime,
                path=path,
                touched_paths=touched_per_branch[runtime.status.id],
                parent_text=parent_text,
                parent_raw=parent_raw,
            )
            branches_for_path[runtime.status.id] = change

        agreement = _classify_agreement(branches_for_path)
        path_diffs.append(
            PathDiff(
                path=path,
                parent_content=parent_text,
                branches=branches_for_path,
                agreement=agreement,
            )
        )

        if agreement in ("unanimous_change", "unanimous_no_change"):
            unanimous_paths += 1
        elif agreement == "split":
            split_paths += 1
        else:  # agreement == "unique" — the four-value Literal is exhaustive
            for branch_id, change in branches_for_path.items():  # pragma: no branch
                # "unique" guarantees exactly one touched branch — the loop
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
