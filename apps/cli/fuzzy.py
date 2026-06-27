"""Fuzzy subsequence matching for the command and file pickers.

A lightweight fzf-style matcher: the query characters must appear in order
(not necessarily contiguously) within the candidate. Matches are scored so the
most relevant candidates rank first — contiguous runs, word-boundary hits, and
early matches all score higher, while large gaps are penalised.

Used by the `/` command picker and the `@` file picker so typing ``mainpy``
finds ``apps/cli/main.py`` without spelling the whole path.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

# Characters that mark the start of a "word" inside a path or command — a match
# right after one of these is a strong signal (e.g. the "m" in "/main.py").
_BOUNDARY_CHARS = frozenset("/_-. :")

_CONSECUTIVE_BONUS = 10
_BOUNDARY_BONUS = 8
_START_BONUS = 12
_GAP_PENALTY = 3


def fuzzy_score(query: str, text: str) -> int | None:
    """Score how well ``query`` fuzzy-matches ``text`` (case-insensitive).

    Returns a score where higher is better, or ``None`` when ``query`` is not a
    subsequence of ``text``. An empty query scores 0 (matches everything).
    """
    if not query:
        return 0
    q = query.lower()
    t = text.lower()

    score = 0
    search_from = 0
    prev_idx = -2
    for qc in q:
        idx = t.find(qc, search_from)
        if idx == -1:
            return None
        if idx == prev_idx + 1:
            score += _CONSECUTIVE_BONUS
        if idx == 0:
            score += _START_BONUS
        elif t[idx - 1] in _BOUNDARY_CHARS:
            score += _BOUNDARY_BONUS
        # Penalise the characters skipped since the previous match.
        score -= (idx - search_from) * _GAP_PENALTY
        prev_idx = idx
        search_from = idx + 1
    return score


def fuzzy_filter(
    query: str,
    items: list[T],
    key: Callable[[T], str],
) -> list[T]:
    """Filter ``items`` to those matching ``query``, best matches first.

    ``key`` extracts the string to match against each item. With an empty query
    the original list is returned unchanged (stable order preserved). Ties are
    broken by shorter candidates first, then the original order, so the most
    specific match wins without reshuffling equal results.
    """
    if not query.strip():
        return items
    q = query.strip()
    scored: list[tuple[int, int, int, T]] = []
    for order, item in enumerate(items):
        text = key(item)
        score = fuzzy_score(q, text)
        if score is not None:
            scored.append((score, -len(text), -order, item))
    scored.sort(reverse=True)
    return [item for _, _, _, item in scored]
