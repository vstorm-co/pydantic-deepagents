"""Tests for shared text helpers in pydantic_deep._text."""

from pydantic_deep._text import NUM_CHARS_PER_TOKEN, approx_tokens, truncate_text


class TestApproxTokens:
    def test_chars_per_token(self) -> None:
        assert NUM_CHARS_PER_TOKEN == 4

    def test_estimates_by_quarter_length(self) -> None:
        assert approx_tokens("x" * 40) == 10

    def test_empty(self) -> None:
        assert approx_tokens("") == 0


class TestTruncateText:
    def test_no_truncation_when_short(self) -> None:
        text = "hello world"
        assert truncate_text(text, 400) == text

    def test_exact_limit_not_truncated(self) -> None:
        text = "x" * 400
        assert truncate_text(text, 400) == text

    def test_truncation_inserts_marker(self) -> None:
        text = "a" * 10_000
        result = truncate_text(text, 400)
        assert "truncated" in result
        assert len(result) < len(text)

    def test_head_is_70_percent(self) -> None:
        text = "A" * 800 + "B" * 800
        result = truncate_text(text, 400)
        head_part = result.split("...")[0]
        assert "A" in head_part
        assert "B" not in head_part.replace(" ", "").replace("\n", "")

    def test_tail_contains_end_of_text(self) -> None:
        text = "A" * 2000 + "ZEND"
        result = truncate_text(text, 40)
        assert result.endswith("ZEND")

    def test_zero_budget_truncates_to_marker_only(self) -> None:
        text = "abcdef" * 100
        result = truncate_text(text, 0)
        assert "truncated" in result
        assert "abcdef" not in result
