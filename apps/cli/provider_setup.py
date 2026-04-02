"""Provider setup wizard for first-run and /provider command.

Handles provider selection, API key input, and .env persistence.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

PROVIDERS = [
    {
        "name": "Anthropic",
        "prefix": "anthropic",
        "env_var": "ANTHROPIC_API_KEY",
        "models": [
            ("anthropic:claude-opus-4-6", "Claude Opus 4.6 (most capable)"),
            ("anthropic:claude-sonnet-4-6", "Claude Sonnet 4.6 (fast + smart)"),
            ("anthropic:claude-haiku-4-5-20251001", "Claude Haiku 4.5 (fastest)"),
        ],
        "default_model": "anthropic:claude-sonnet-4-6",
        "key_hint": "sk-ant-...",
    },
    {
        "name": "OpenAI",
        "prefix": "openai",
        "env_var": "OPENAI_API_KEY",
        "models": [
            ("openai:gpt-4.1", "GPT-4.1"),
            ("openai:gpt-4.1-mini", "GPT-4.1 Mini (fast)"),
        ],
        "default_model": "openai:gpt-4.1",
        "key_hint": "sk-...",
    },
    {
        "name": "Google",
        "prefix": "google",
        "env_var": "GOOGLE_API_KEY",
        "models": [
            ("google:gemini-2.5-pro", "Gemini 2.5 Pro"),
            ("google:gemini-2.5-flash", "Gemini 2.5 Flash (fast)"),
        ],
        "default_model": "google:gemini-2.5-pro",
        "key_hint": "AIza...",
    },
    {
        "name": "OpenRouter",
        "prefix": "openrouter",
        "env_var": "OPENROUTER_API_KEY",
        "models": [
            ("openrouter:anthropic/claude-sonnet-4", "Claude Sonnet 4 via OpenRouter"),
            ("openrouter:openai/gpt-4.1", "GPT-4.1 via OpenRouter"),
            ("openrouter:google/gemini-2.5-pro", "Gemini 2.5 Pro via OpenRouter"),
        ],
        "default_model": "openrouter:anthropic/claude-sonnet-4",
        "key_hint": "sk-or-...",
    },
]


def _get_env_path() -> Path:
    """Return path to .env file (project-level, then user-level)."""
    project_env = Path.cwd() / ".pydantic-deep" / ".env"
    if project_env.exists():
        return project_env
    user_env = Path.home() / ".pydantic-deep" / ".env"
    return user_env


def _load_env_key(env_var: str) -> str | None:
    """Check if env var is set (from environment or .env file)."""
    val = os.environ.get(env_var)
    if val:
        return val
    # Check .env files
    for path in [Path.cwd() / ".pydantic-deep" / ".env", Path.home() / ".pydantic-deep" / ".env"]:
        if path.exists():
            for line in path.read_text().splitlines():
                line = line.strip()
                if line.startswith(f"{env_var}="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _save_env_key(env_var: str, value: str) -> Path:
    """Save API key to .env file. Returns path used."""
    env_path = Path.cwd() / ".pydantic-deep" / ".env"
    env_path.parent.mkdir(parents=True, exist_ok=True)

    # Read existing
    existing: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip()

    existing[env_var] = value

    # Write back
    lines = [f'{k}={v}' for k, v in sorted(existing.items())]
    env_path.write_text("\n".join(lines) + "\n")

    # Also set in current process
    os.environ[env_var] = value

    return env_path


def has_any_provider_configured() -> bool:
    """Check if any provider has a non-empty API key configured."""
    for provider in PROVIDERS:
        key = _load_env_key(provider["env_var"])
        if key and len(key) > 5:  # Sanity check — not just whitespace/garbage
            return True
    return False


def run_provider_setup(console: Console, theme: Any) -> str | None:
    """Run interactive provider setup wizard.

    Returns the selected model string, or None if user quit.
    """
    console.print()
    console.print(f"[bold {theme.primary}]Provider Setup[/bold {theme.primary}]")
    console.print(f"[{theme.muted}]Choose an AI provider to get started.[/{theme.muted}]\n")

    # Show providers as numbered list
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style=f"bold {theme.primary}")
    table.add_column()
    table.add_column(style=theme.muted)

    for i, provider in enumerate(PROVIDERS, 1):
        key = _load_env_key(provider["env_var"])
        status = f"[{theme.success}]configured[/{theme.success}]" if key else ""
        table.add_row(f"{i}.", provider["name"], status)

    console.print(table)
    console.print()

    # Pick provider
    try:
        choice = input("Select provider (1-4) or 'q' to quit: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if choice.lower() in ("q", "quit", ""):
        return None

    try:
        idx = int(choice) - 1
        if not 0 <= idx < len(PROVIDERS):
            console.print(f"[{theme.error}]Invalid choice.[/{theme.error}]")
            return None
    except ValueError:
        console.print(f"[{theme.error}]Invalid choice.[/{theme.error}]")
        return None

    provider = PROVIDERS[idx]

    # Check if key already set
    existing_key = _load_env_key(provider["env_var"])
    if existing_key:
        console.print(
            f"\n[{theme.success}]{provider['name']} API key already configured.[/{theme.success}]"
        )
    else:
        # Ask for API key
        console.print(f"\n[{theme.muted}]Enter your {provider['name']} API key ({provider['key_hint']}):[/{theme.muted}]")
        try:
            key = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            return None

        if not key:
            console.print(f"[{theme.error}]No key provided.[/{theme.error}]")
            return None

        env_path = _save_env_key(provider["env_var"], key)
        console.print(f"[{theme.success}]API key saved to {env_path}[/{theme.success}]")

    # Pick model
    console.print(f"\n[{theme.muted}]Available models:[/{theme.muted}]")
    for i, (model_id, desc) in enumerate(provider["models"], 1):
        default_tag = f" [{theme.accent}]default[/{theme.accent}]" if model_id == provider["default_model"] else ""
        console.print(f"  {i}. {desc} ({model_id}){default_tag}")

    console.print(f"\n[{theme.muted}]Press Enter for default ({provider['default_model']}):[/{theme.muted}]")
    try:
        model_choice = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        return provider["default_model"]

    if not model_choice:
        selected = provider["default_model"]
    else:
        try:
            midx = int(model_choice) - 1
            if 0 <= midx < len(provider["models"]):
                selected = provider["models"][midx][0]
            else:
                selected = provider["default_model"]
        except ValueError:
            selected = provider["default_model"]

    # Save model to config
    from apps.cli.config import get_config_path, set_config_value

    try:
        set_config_value(get_config_path(), "model", selected)
        console.print(f"\n[{theme.success}]Model set to {selected}[/{theme.success}]")
    except Exception:
        pass  # Config save is best-effort

    console.print()
    return selected
