"""CLI-side reminder helpers — config building and live mode switching."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.cli.app import DeepApp

_REMINDER_LABELS: dict[str, str] = {
    "off": "off",
    "first": "first message only",
    "context": "first + recent context",
    "llm": "LLM generator",
}


_CHEAP_PROVIDER: dict[str, str] = {
    "anthropic": "anthropic:claude-haiku-4-5-20251001",
    "openrouter": "openrouter:anthropic/claude-haiku-4-5",
    "openai": "openai:gpt-5.4-mini",
    "google": "google-gla:gemini-3.1-flash-lite-preview",
}


def _get_cheap_model(main_model: str) -> str:
    """Return the cheapest fast model for the same provider as main_model."""
    provider = main_model.split(":")[0] if ":" in main_model else "anthropic"
    return _CHEAP_PROVIDER.get(provider, main_model)


def _build_reminder_config(
    periodic_reminder: bool | None,
    reminder_mode: str | None,
    config: Any,
    on_reminder: Callable[[int, str], None] | None = None,
) -> Any:
    """Build a PeriodicReminderConfig (or None) from CLI/config args."""
    enabled = periodic_reminder if periodic_reminder is not None else config.periodic_reminder
    if not enabled:
        return None
    mode = reminder_mode or config.reminder_mode or "llm"
    if mode == "off":
        return None
    from pydantic_deep.capabilities.periodic_reminder import (
        LLMReminderGenerator,
        make_config_for_mode,
    )

    cfg = make_config_for_mode(mode)
    if mode == "llm":
        cfg.generator = LLMReminderGenerator(model=_get_cheap_model(config.model))
    cfg.on_reminder = on_reminder
    return cfg


def _apply_reminder_mode(app: DeepApp, mode: str) -> None:
    """Update the running agent's PeriodicReminderCapability without restart."""
    from pydantic_deep.capabilities.periodic_reminder import PeriodicReminderCapability

    agent = app.agent
    if agent is None:
        app.notify("No agent running", severity="warning")
        return

    caps: list = getattr(agent, "_capabilities", [])
    existing = next((c for c in caps if isinstance(c, PeriodicReminderCapability)), None)

    if mode == "off":
        if existing is not None:
            caps.remove(existing)
        app._reminder_mode = "off"  # type: ignore[attr-defined]
        app.notify("Selected reminder mode: off")
        return

    from pydantic_deep.capabilities.periodic_reminder import make_config_for_mode

    new_config = make_config_for_mode(mode)
    new_config.on_reminder = existing.config.on_reminder if existing is not None else None

    if existing is not None:
        existing.config = new_config
        existing._turn_counter = 0
        existing._reminder_count = 0
    else:
        caps.append(PeriodicReminderCapability(config=new_config))

    app._reminder_mode = mode  # type: ignore[attr-defined]
    app.notify(f"Selected reminder mode: {_REMINDER_LABELS.get(mode, mode)}")

    try:
        from apps.cli.config import DEFAULT_CONFIG_PATH, set_config_value

        set_config_value(DEFAULT_CONFIG_PATH, "periodic_reminder", str(mode != "off").lower())
        if mode != "off":
            set_config_value(DEFAULT_CONFIG_PATH, "reminder_mode", mode)
    except Exception:
        pass
