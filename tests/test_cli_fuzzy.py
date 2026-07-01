"""Tests for the fuzzy subsequence matcher used by the CLI pickers."""

from __future__ import annotations

from apps.cli.fuzzy import fuzzy_filter, fuzzy_score


class TestFuzzyScore:
    def test_empty_query_matches_everything(self) -> None:
        assert fuzzy_score("", "anything") == 0

    def test_subsequence_matches(self) -> None:
        assert fuzzy_score("mainpy", "apps/cli/main.py") is not None

    def test_non_subsequence_returns_none(self) -> None:
        assert fuzzy_score("xyz", "apps/cli/main.py") is None

    def test_out_of_order_returns_none(self) -> None:
        # "ba" cannot match "abc" — chars must appear in order.
        assert fuzzy_score("ba", "abc") is None

    def test_case_insensitive(self) -> None:
        assert fuzzy_score("MAIN", "main.py") is not None

    def test_contiguous_outranks_scattered(self) -> None:
        contiguous = fuzzy_score("main", "main.py")
        scattered = fuzzy_score("main", "m-a-i-n.py")
        assert contiguous is not None and scattered is not None
        assert contiguous > scattered

    def test_boundary_match_scores_well(self) -> None:
        # "c" right after the "/" boundary beats a mid-word "c".
        boundary = fuzzy_score("c", "a/config")
        midword = fuzzy_score("c", "abcdef")
        assert boundary is not None and midword is not None
        assert boundary > midword


class TestFuzzyFilter:
    def test_empty_query_preserves_order(self) -> None:
        items = ["b", "a", "c"]
        assert fuzzy_filter("", items, key=lambda x: x) == ["b", "a", "c"]

    def test_filters_and_ranks(self) -> None:
        files = ["apps/cli/main.py", "tests/test_main.py", "README.md", "src/util.py"]
        out = fuzzy_filter("mainpy", files, key=lambda x: x)
        assert "README.md" not in out
        # Both main.py files match; the exact path with the tighter match ranks first.
        assert out[0] in ("apps/cli/main.py", "tests/test_main.py")

    def test_exact_substring_ranks_first(self) -> None:
        cmds = [("/compact", "compress"), ("/copy", "copy text"), ("/context", "show context")]
        out = fuzzy_filter("copy", cmds, key=lambda c: f"{c[0]} {c[1]}")
        assert out[0][0] == "/copy"

    def test_no_matches_returns_empty(self) -> None:
        assert fuzzy_filter("zzzz", ["abc", "def"], key=lambda x: x) == []
