"""Tests for the pydantic-ai 2.0 compatibility shims."""

from __future__ import annotations

from pydantic_ai.usage import RunUsage

from pydantic_deep._compat import install_run_usage_call_shim


def test_run_usage_is_callable_and_returns_self() -> None:
    # Importing pydantic_deep already installed the shim, so an old-style
    # `result.usage()` call resolves to the RunUsage instance itself.
    usage = RunUsage(input_tokens=7)
    assert usage() is usage
    assert usage().input_tokens == 7


def test_install_is_idempotent() -> None:
    # Already installed at import time, so a re-install is a no-op.
    assert install_run_usage_call_shim() is False


def test_install_applies_when_absent() -> None:
    # Simulate a fresh interpreter: drop the marker + __call__, then re-install.
    delattr(RunUsage, "_pd_call_shim")
    del RunUsage.__call__
    try:
        assert install_run_usage_call_shim() is True
        assert RunUsage()() is not None  # callable again
    finally:
        # Leave the shim installed for the rest of the suite.
        install_run_usage_call_shim()
