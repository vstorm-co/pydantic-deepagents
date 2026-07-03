"""First-run onboarding for the CLI.

Onboarding is needed when no model is configured anywhere (env, project, or the
user-level ``~/.pydantic-deep/config.toml``) — a user who hasn't picked a model
hasn't set the tool up yet. On first launch we walk them through picking a
provider, entering its key, and choosing a model; the choice is written to the
global config so it carries across every project.
"""

from __future__ import annotations

import contextlib

from rich.console import Console

from apps.cli.config import (
    config_has_model,
    get_global_config_path,
    get_global_dir,
    set_config_value,
)
from apps.cli.credentials import CREDENTIALS, Credential
from apps.cli.keystore import save_key
from apps.cli.model_history import record_model_use
from pydantic_deep.models import DEFAULT_MODEL


def needs_onboarding() -> bool:
    """True when no model is configured yet — the signal for first-run setup."""
    return not config_has_model()


def is_new_user() -> bool:
    """True when the user has no global state yet (never onboarded)."""
    return not get_global_dir().exists()


def mark_onboarded() -> None:
    """Create the global dir so the user is no longer treated as new."""
    get_global_dir().mkdir(parents=True, exist_ok=True)


def _set_global_model(model: str) -> None:
    """Persist the default model to the user-level config (cross-project)."""
    with contextlib.suppress(Exception):
        set_config_value(get_global_config_path(), "model", model)


def _provider_credentials() -> list[Credential]:
    """The model-provider credentials, de-duplicated by provider (first wins)."""
    seen: set[str] = set()
    out: list[Credential] = []
    for cred in CREDENTIALS:
        if cred.provider_id and cred.provider_id not in seen:
            seen.add(cred.provider_id)
            out.append(cred)
    return out


def _default_model_for(cred: Credential) -> str:
    """Best default model string for a chosen provider credential."""
    from apps.cli.providers import PROVIDER_DEFAULT_MODELS

    return PROVIDER_DEFAULT_MODELS.get(cred.provider_id, "")


def _skip() -> None:
    """Record a skip so onboarding doesn't nag again: fall back to the default model."""
    _set_global_model(DEFAULT_MODEL)
    mark_onboarded()


def run_onboarding(console: Console | None = None) -> str | None:
    """Interactive first-run flow. Returns the chosen model string, or None.

    Saves the entered key to the global keystore and writes the chosen model to
    the user-level config. Skipping falls back to the default model so the user
    isn't prompted again.
    """
    import typer

    console = console or Console()
    console.print("\n[bold]Welcome to pydantic-deep 👋[/bold]")
    console.print("Let's connect a model provider so the agent can think.\n")

    providers = _provider_credentials()
    for i, cred in enumerate(providers, 1):
        console.print(f"  [cyan]{i:2}[/cyan]. {cred.label}")
    console.print("  [dim] 0[/dim]. Skip for now")

    choice = typer.prompt("\nPick a provider", default="1").strip()
    if choice in ("0", ""):
        _skip()
        console.print("[dim]Skipped. Set keys later with:[/dim] pydantic-deep keys set")
        return None
    if not choice.isdigit() or not (1 <= int(choice) <= len(providers)):
        console.print("[yellow]Not a valid choice — skipping onboarding.[/yellow]")
        _skip()
        return None

    cred = providers[int(choice) - 1]
    if cred.url:
        console.print(f"[dim]Get a key at {cred.url}[/dim]")
    key = typer.prompt(f"Paste your {cred.label} key", hide_input=True).strip()
    if key:
        save_key(cred.env_var, key)
        console.print(f"[green]✓[/green] Saved {cred.env_var}")

    model = _default_model_for(cred)
    model = typer.prompt("Default model", default=model).strip() if model else model
    if not model:
        model = DEFAULT_MODEL
    record_model_use(model)
    _set_global_model(model)
    console.print(f"[green]✓[/green] Model set to [bold]{model}[/bold]")

    mark_onboarded()
    console.print("\n[bold green]You're all set![/bold green] Launching…\n")
    return model


__all__ = ["is_new_user", "mark_onboarded", "needs_onboarding", "run_onboarding"]
