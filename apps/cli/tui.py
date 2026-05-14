"""Entry point for the Textual-based TUI.

Usage:
    python -m apps.cli.main              # with agent (uses config.toml)
    python -m apps.cli.main --preview    # UI preview (no agent)
    python -m apps.cli.main -m openai:gpt-4.1  # override model
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def run_tui(
    model: str | None = None,
    working_dir: str | Path | None = None,
    sandbox: str | None = None,
    workspace: str | None = None,
    **kwargs: Any,
) -> None:
    """Launch the Textual TUI.

    If agent creation fails (e.g. missing API key), the TUI launches
    anyway without an agent so the user can configure via /provider or /settings.
    """
    from apps.cli.app import DeepApp
    from apps.cli.config import load_config
    from apps.cli.keystore import load_keys

    # Load saved API keys from keys.toml → os.environ
    load_keys()

    config = load_config()

    try:
        from importlib.metadata import version as pkg_version

        version = pkg_version("pydantic-deep")
    except Exception:
        version = "dev"

    effective_model = model or config.model

    # Try to pick a model that has an available API key

    effective_model = DeepApp._pick_available_model(effective_model)

    agent = None
    deps = None
    startup_error: str | None = None

    # We'll create a mutable holder so the callbacks can reference the app
    # after it's created (callbacks are passed to create_cli_agent before
    # the app exists).
    app_ref: list[DeepApp | None] = [None]

    def _on_cost_update(cost_info: Any) -> None:
        """Forward cost updates from CostTracking capability to the TUI."""
        _app = app_ref[0]
        if _app is None:
            return
        try:
            from apps.cli.messages import CostUpdated

            run_cost = float(getattr(cost_info, "run_cost_usd", 0) or 0)
            total_cost = float(getattr(cost_info, "total_cost_usd", 0) or 0)
            # CostInfo has total_request_tokens / total_response_tokens
            total_input = int(getattr(cost_info, "total_request_tokens", 0) or 0)
            total_output = int(getattr(cost_info, "total_response_tokens", 0) or 0)

            _app.current_cost = run_cost
            _app.total_cost = total_cost
            # Post to current screen (not app) — Textual messages bubble up, not down
            if _app.screen is not None:
                _app.screen.post_message(
                    CostUpdated(run_cost, total_cost, total_input, total_output)
                )
        except Exception:
            pass

    def _on_context_update(pct: float, current: int, maximum: int) -> None:
        """Forward context window updates to the TUI.

        Called by ContextManagerCapability.on_usage_update(pct, total_tokens, max_tokens).
        """
        _app = app_ref[0]
        if _app is None:
            return
        try:
            _app.context_pct = float(pct)
            _app.context_current = int(current)
            _app.context_max = int(maximum)
        except Exception:
            pass

    def _on_reminder(_turn: int, _text: str) -> None:
        _app = app_ref[0]
        if _app is None:
            return
        try:  # noqa: SIM105
            _app.notify("Agent reminded of original task.", timeout=3)
        except Exception:
            pass

    # Try to create the agent — if it fails (missing API key etc.)
    # we still launch the TUI so the user can fix it from /provider
    try:
        from apps.cli.agent import create_cli_agent

        agent, deps = create_cli_agent(
            model=effective_model,
            working_dir=str(working_dir) if working_dir else None,
            on_cost_update=_on_cost_update,
            on_context_update=_on_context_update,
            on_reminder=_on_reminder,
            sandbox=sandbox,
            workspace=workspace,
            **kwargs,
        )
    except Exception as exc:
        startup_error = str(exc)
        # Log startup error (logger may not be initialized yet, so use basic logging)
        import logging

        logging.getLogger("pydantic_deep.tui").error("Agent creation failed at startup: %s", exc)

    app = DeepApp(
        agent=agent,
        deps=deps,
        working_dir=working_dir or ".",
        model=effective_model,
        version=version,
        startup_error=startup_error,
    )
    app_ref[0] = app
    try:
        app.run()
    finally:
        # Stop Docker container if sandbox backend was used
        if deps is not None and hasattr(deps.backend, "stop"):
            deps.backend.stop()


def run_preview() -> None:
    """Launch TUI without an agent (UI preview only)."""
    from apps.cli.app import DeepApp

    try:
        from importlib.metadata import version as pkg_version

        version = pkg_version("pydantic-deep")
    except Exception:
        version = "dev"

    app = DeepApp(
        model="preview",
        version=version,
        working_dir=".",
    )
    app.run()


if __name__ == "__main__":
    if "--preview" in sys.argv:
        run_preview()
    else:
        model_override: str | None = None
        args = sys.argv[1:]
        for i, arg in enumerate(args):
            if arg in ("-m", "--model") and i + 1 < len(args):
                model_override = args[i + 1]

        run_tui(model=model_override)
