"""Runtime compatibility shims for the pydantic-ai 2.0 API transition.

Applied on `import pydantic_deep`, so every consumer (CLI, bench, library use)
gets them without touching the upstream packages.
"""

from __future__ import annotations

from pydantic_ai.usage import RunUsage


def install_run_usage_call_shim() -> bool:
    """Let `RunUsage` be called like a function, returning itself.

    pydantic-ai 2.0 turned `AgentRunResult.usage` from a method into a property
    that returns a `RunUsage`. Code built against the older method API still
    writes `result.usage()`, which now raises ``'RunUsage' object is not
    callable`` — this is what breaks subagent runs (subagents-pydantic-ai 0.2.7
    captures usage that way). Making `RunUsage.__call__` return `self` keeps
    both `result.usage` and `result.usage()` working.

    Returns ``True`` if the shim was installed, ``False`` if it was already in
    place (idempotent).
    """
    if getattr(RunUsage, "_pd_call_shim", False):
        return False

    def _return_self(self: RunUsage) -> RunUsage:
        return self

    RunUsage.__call__ = _return_self  # type: ignore[method-assign]
    RunUsage._pd_call_shim = True  # type: ignore[attr-defined]
    return True


install_run_usage_call_shim()
