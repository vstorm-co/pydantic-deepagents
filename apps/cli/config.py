"""Configuration system for the pydantic-deep CLI.

Config file: `.pydantic-deep/config.toml` (in working directory)

Precedence: CLI arguments > config file > hardcoded defaults.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Literal

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    try:
        import tomllib  # type: ignore[import-not-found,no-redefine]
    except ImportError:
        import tomli as tomllib  # type: ignore[import-not-found,no-redefine]

from pydantic_deep.models import DEFAULT_JUDGE_MODEL, DEFAULT_MODEL


def get_project_dir() -> Path:
    """Return `.pydantic-deep/` in CWD."""
    return Path.cwd() / ".pydantic-deep"


def get_config_path() -> Path:
    """Return path to `config.toml`."""
    return get_project_dir() / "config.toml"


def get_sessions_dir() -> Path:
    """Return path to `sessions/` directory."""
    return get_project_dir() / "sessions"


def get_history_path() -> Path:
    """Return path to `history.txt`."""
    return get_project_dir() / "history.txt"


# Keep these for backward compatibility — used by imports
DEFAULT_CONFIG_DIR = get_project_dir()
DEFAULT_CONFIG_PATH = get_config_path()
DEFAULT_THREADS_DIR = get_sessions_dir()

_BOOL_FIELDS = frozenset(
    {
        "include_skills",
        "include_plan",
        "include_memory",
        "include_subagents",
        "include_todo",
        "web_search",
        "web_fetch",
        "include_teams",
        "context_discovery",
        "show_cost",
        "show_tokens",
        "logfire",
        "include_browser",
        "browser_headless",
        "include_liteparse",
        "periodic_reminder",
    }
)

_STR_FIELDS = frozenset(
    {
        "model",
        "fallback_model",
        "theme",
        "charset",
        "reasoning_effort",
        "thinking_effort",
        "sandbox",
        "sandbox_image",
        "sandbox_env_file",
        "reminder_mode",
        "reminder_model",
    }
)

_INT_FIELDS = frozenset({"max_history", "fork_branch_count"})

_FLOAT_FIELDS = frozenset({"temperature", "fork_aggregate_budget_usd", "fork_confidence_threshold"})

#: Float fields declared `float | None` — only these may be coerced to `None`.
#: Non-optional float fields (e.g. `fork_confidence_threshold`) must reject empty/
#: `none`/`null` so a stored `None` can't later crash numeric validation.
_OPTIONAL_FLOAT_FIELDS = frozenset({"temperature", "fork_aggregate_budget_usd"})

_FORK_MERGE_STRATEGY_VALUES = frozenset({"manual", "auto", "auto_with_fallback", "vote"})


@dataclass
class CliConfig:
    """CLI configuration loaded from config.toml."""

    model: str = DEFAULT_MODEL
    working_dir: str | None = None
    shell_allow_list: list[str] = field(default_factory=list)
    theme: str = "default"
    charset: str = "auto"
    show_cost: bool = True
    show_tokens: bool = True
    history_file: str = ""  # empty = use get_history_path() at runtime
    max_history: int = 1000
    include_skills: bool = True
    include_plan: bool = True
    include_memory: bool = True
    include_subagents: bool = True
    include_todo: bool = True
    web_search: bool = True
    web_fetch: bool = True
    include_teams: bool = False
    context_discovery: bool = True
    thinking_effort: str = "high"
    approve_tools: list[str] = field(default_factory=lambda: ["execute"])
    """Tool names that require user approval before execution."""
    temperature: float | None = None
    reasoning_effort: str | None = None
    sandbox: str = "local"
    """Sandbox backend: `"local"` (default) or `"docker"`."""
    sandbox_image: str = "python:3.12-slim"
    """Docker image used when `sandbox = "docker"`."""
    sandbox_env_vars: dict[str, str] = field(default_factory=dict)
    """Environment variables injected into the Docker sandbox container."""
    sandbox_env_file: str | None = None
    """Path to a .env file whose variables are injected into the Docker sandbox container."""
    logfire: bool = False
    include_browser: bool = True
    """Enable browser automation via Playwright (requires `pydantic-deep[browser]`)."""
    browser_headless: bool = True
    """Run browser without a visible window. Default `True` — browser window is hidden."""
    include_liteparse: bool = True
    """Enable document parsing via LiteParse.

    Requires `pydantic-deep[liteparse]` and Node.js >= 18."""
    tool_search: bool = True
    """Defer the situational tool surface and discover tools on demand.

    Keeps the core read/edit/run/track loop always-loaded and hides the rest
    (subagents, skills, memory, MCP, …) until the model searches for them,
    cutting per-request input tokens. Default `True` in the CLI."""
    periodic_reminder: bool = True
    """Inject a periodic reminder of the original task every N turns."""
    reminder_mode: Literal["off", "first", "context", "llm"] = "llm"
    """Generator to use for reminders: `"first"` (zero-cost, re-states first message),
    `"context"` (compact transcript, no LLM), or `"llm"` (default, uses an LLM to summarize)."""
    reminder_model: str | None = None
    """Model used by the `"llm"` reminder generator. Defaults to the main model when `None`."""
    fallback_model: str | None = None
    """Fallback model used when the primary model fails (rate limit, 5xx). Set via /model picker."""
    fork_branch_count: int = 2
    """Number of branches the `/fork` picker prepares. Set via `/fork-config`.
    Valid range is `[1, LiveForkCapability.max_branches]` (kernel default 10)."""
    fork_aggregate_budget_usd: float | None = None
    """Fork-wide budget cap passed to `coordinator.fork(aggregate_budget_usd=...)`.
    Set via `/fork-config`; cleared by emptying the input and saving."""
    fork_branch_models: list[str | None] = field(default_factory=list)
    """Per-branch model overrides, positional (slot `i` → branch `i+1`).
    `None` entries mean "use the agent's default model". Set via
    `/fork-config`; written to TOML as `list[str]` with empty strings
    standing in for `None`."""
    fork_branch_budgets: list[float | None] = field(default_factory=list)
    """Per-branch `budget_usd` caps, positional (slot `i` → branch `i+1`).
    `None` entries mean "no per-branch cap". Set via `/fork-config`;
    written to TOML as `list[str]` (quoted floats) with empty strings
    standing in for `None` to keep the format aligned with
    :attr:`fork_branch_models`."""
    fork_merge_strategy: Literal["manual", "auto", "auto_with_fallback", "vote"] = (
        "auto_with_fallback"
    )
    """Merge strategy used when `/merge` is called.

    - `"manual"` — you always pick via the picker modal.
    - `"auto"` — judge picks and commits immediately.
    - `"auto_with_fallback"` — judge picks; above the confidence threshold you
      see the acceptance widget, below it falls back to the picker preselected.
    - `"vote"` — three judges (Haiku + GPT-4o-mini + Gemini Flash) vote;
      majority wins, commits immediately.

    Set via `/fork-config`."""
    fork_judge_model: str = DEFAULT_JUDGE_MODEL
    """Model used as the judge in `auto` / `auto_with_fallback` modes.

    Any pydantic-ai model string is valid, e.g.
    `"openrouter:anthropic/claude-haiku-4-5"` or
    `"openai:gpt-4o-mini"`. Set via `/fork-config`."""
    fork_confidence_threshold: float = 0.80
    """Confidence threshold for `auto_with_fallback`.

    Combined confidence must be at or above this value for the acceptance
    widget to appear; below it falls through to the manual picker.
    Set via `/fork-config`."""


def load_config(path: Path | None = None) -> CliConfig:
    """Load config from TOML file with environment variable overrides.

    Precedence: environment variables > config file > defaults.
    """
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        config = CliConfig()
    else:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        config = _parse_config(data)

    _apply_env_overrides(config)
    return config


def _apply_env_overrides(config: CliConfig) -> None:
    """Apply PYDANTIC_DEEP_* environment variable overrides."""
    env_model = os.environ.get("PYDANTIC_DEEP_MODEL")
    if env_model:
        config.model = env_model

    env_working_dir = os.environ.get("PYDANTIC_DEEP_WORKING_DIR")
    if env_working_dir:
        config.working_dir = env_working_dir

    env_theme = os.environ.get("PYDANTIC_DEEP_THEME")
    if env_theme:
        config.theme = env_theme

    env_charset = os.environ.get("PYDANTIC_DEEP_CHARSET")
    if env_charset:
        config.charset = env_charset


def validate_config(config: CliConfig) -> list[str]:
    """Validate config values, returning a list of warning messages."""
    warnings: list[str] = []
    if config.model and ":" not in config.model:
        warnings.append(
            f"Model '{config.model}' missing provider prefix (e.g. 'anthropic:claude-opus-4-6')"
        )
    if config.working_dir:
        from pathlib import Path as _Path

        if not _Path(config.working_dir).exists():
            warnings.append(f"Working directory '{config.working_dir}' does not exist")
    known_themes = {"default", "emerald", "minimal", "ocean", "rose"}
    if config.theme not in known_themes:
        warnings.append(
            f"Unknown theme '{config.theme}'. Known themes: {', '.join(sorted(known_themes))}"
        )
    known_charsets = {"auto", "unicode", "ascii"}
    if config.charset not in known_charsets:
        warnings.append(
            f"Unknown charset '{config.charset}'. Known: {', '.join(sorted(known_charsets))}"
        )
    known_sandboxes = {"local", "docker"}
    if config.sandbox not in known_sandboxes:
        warnings.append(
            f"Unknown sandbox '{config.sandbox}'. Known: {', '.join(sorted(known_sandboxes))}"
        )
    if config.max_history < 0:
        warnings.append("max_history must be non-negative")
    known_reminder_modes = {"off", "first", "context", "llm"}
    if config.reminder_mode not in known_reminder_modes:
        warnings.append(
            f"Unknown reminder_mode '{config.reminder_mode}'. "
            f"Known modes: {', '.join(sorted(known_reminder_modes))}"
        )
    if config.fork_branch_count < 1 or config.fork_branch_count > 10:
        warnings.append(
            f"fork_branch_count={config.fork_branch_count} is outside the typical [1, 10] "
            "range; will be capped at the agent's LiveForkCapability.max_branches at "
            "fork time."
        )
    if config.fork_aggregate_budget_usd is not None and config.fork_aggregate_budget_usd <= 0:
        warnings.append("fork_aggregate_budget_usd must be positive")
    for i, b in enumerate(config.fork_branch_budgets):
        if b is not None and b <= 0:
            warnings.append(f"fork_branch_budgets[{i}] must be positive, got {b}")
    if config.fork_merge_strategy not in _FORK_MERGE_STRATEGY_VALUES:
        warnings.append(
            f"Unknown fork_merge_strategy '{config.fork_merge_strategy}'. "
            f"Valid values: {', '.join(sorted(_FORK_MERGE_STRATEGY_VALUES))}"
        )
    if config.fork_confidence_threshold < 0.0 or config.fork_confidence_threshold > 1.0:
        warnings.append("fork_confidence_threshold must be in [0.0, 1.0]")
    return warnings


def _parse_config(data: dict[str, Any]) -> CliConfig:
    """Parse TOML dict into CliConfig, ignoring unknown keys.

    Normalises `fork_branch_models`: TOML lists are `list[str]`, but the
    canonical Python type is `list[str | None]` — empty strings stand in for
    `None` on disk and are mapped back here so :func:`load_config` always
    returns the documented type.
    """
    valid_fields = {f.name for f in fields(CliConfig)}
    filtered = {k: v for k, v in data.items() if k in valid_fields}
    raw_models = filtered.get("fork_branch_models")
    if isinstance(raw_models, list):
        filtered["fork_branch_models"] = [m if m else None for m in raw_models]
    raw_budgets = filtered.get("fork_branch_budgets")
    if isinstance(raw_budgets, list):
        normalised_budgets: list[float | None] = []
        for b in raw_budgets:
            if b in (None, "", 0, 0.0):
                normalised_budgets.append(None)
            else:
                normalised_budgets.append(float(b))
        filtered["fork_branch_budgets"] = normalised_budgets
    return CliConfig(**filtered)


def get_config_value(key: str, config: CliConfig) -> Any:
    """Get a config value by key.

    Raises:
        KeyError: If the key is not a valid config field.
    """
    if not hasattr(config, key):
        msg = f"Unknown config key: {key}"
        raise KeyError(msg)
    return getattr(config, key)


def set_config_value(path: Path, key: str, value: str) -> None:
    """Set a config value in the TOML file.

    Creates the file and parent directories if they don't exist.
    """
    valid_fields = {f.name for f in fields(CliConfig)}
    if key not in valid_fields:
        msg = f"Unknown config key: {key}. Valid keys: {', '.join(sorted(valid_fields))}"
        raise KeyError(msg)

    if path.exists():
        with open(path, "rb") as f:
            data = tomllib.load(f)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {}

    data[key] = _coerce_value(key, value)
    _write_toml(path, data)


def _coerce_float_field(key: str, value: str) -> float | None:
    """Coerce a (possibly optional) float field, rejecting blanks on required ones."""
    if value.lower() in ("none", "null", ""):
        if key in _OPTIONAL_FLOAT_FIELDS:
            return None
        raise ValueError(f"{key} requires a numeric value; '{value}' is not allowed")
    return float(value)


def _coerce_env_dict(value: str) -> dict[str, str]:
    """Parse comma-separated `KEY=VALUE` pairs into a dict.

    Without this the raw string fell through unchanged, so a later
    `{**config.sandbox_env_vars}` spread (agent.py) raised TypeError.
    """
    env: dict[str, str] = {}
    for raw_pair in value.split(","):
        pair = raw_pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise ValueError(
                f"sandbox_env_vars expects comma-separated KEY=VALUE pairs; '{pair}' has no '='"
            )
        k, v = pair.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def _coerce_merge_strategy(value: str) -> str:
    """Validate and normalise a fork merge-strategy value."""
    v = value.strip().lower()
    if v not in _FORK_MERGE_STRATEGY_VALUES:
        raise ValueError(
            f"Invalid fork_merge_strategy '{value}'. "
            f"Valid: {', '.join(sorted(_FORK_MERGE_STRATEGY_VALUES))}"
        )
    return v


def _coerce_value(key: str, value: str) -> Any:
    """Coerce a raw string config value to the typed value for `key`."""
    if key in _BOOL_FIELDS:
        return value.lower() in ("true", "1", "yes")
    if key in _INT_FIELDS:
        return int(value)
    if key in _FLOAT_FIELDS:
        return _coerce_float_field(key, value)
    if key in ("shell_allow_list", "approve_tools"):
        return [v.strip() for v in value.split(",") if v.strip()]
    if key == "sandbox_env_vars":
        return _coerce_env_dict(value)
    if key in ("fork_branch_models", "fork_branch_budgets"):
        # Keep the list count-aligned with fork_branch_count: the persisted string
        # encodes one slot per branch (N-1 commas), so an all-default 1-branch
        # config is "" → [None], and "," → [None, None]. Special-casing the empty
        # string to [] dropped the positional length, so code indexing model/budget
        # by branch slot would rely on the picker's padding to avoid an IndexError.
        return [v.strip() or None for v in value.split(",")]
    if key == "fork_merge_strategy":
        return _coerce_merge_strategy(value)
    if key == "working_dir" and value.lower() in ("none", "null", ""):
        return None
    if key == "thinking_effort" and value.strip() == "":
        # Blank means "reset to default": coerce to None so _write_toml drops
        # the key and CliConfig's default ("high") applies on next load. A bare
        # "" would otherwise be persisted and passed straight through as the
        # agent's thinking value (agent.py).
        return None
    return value


def _write_toml(path: Path, data: dict[str, Any]) -> None:
    """Write a flat key-value dict as TOML."""
    scalar_lines: list[str] = []
    table_lines: list[str] = []
    for key in sorted(data):
        value = data[key]
        if value is None:
            continue
        if isinstance(value, dict):
            if value:
                table_lines.append(f"\n[{key}]")
                for k, v in sorted(value.items()):
                    table_lines.append(f'{k} = "{v}"')
        elif isinstance(value, bool):
            scalar_lines.append(f"{key} = {'true' if value else 'false'}")
        elif isinstance(value, (float, int)):
            scalar_lines.append(f"{key} = {value}")
        elif isinstance(value, list):
            items = ", ".join('""' if v is None else f'"{v}"' for v in value)
            scalar_lines.append(f"{key} = [{items}]")
        else:
            scalar_lines.append(f'{key} = "{value}"')
    all_lines = scalar_lines + table_lines
    path.write_text("\n".join(all_lines) + "\n")


def format_config(config: CliConfig) -> str:
    """Format config for display."""
    lines: list[str] = []
    for f in fields(config):
        value = getattr(config, f.name)
        lines.append(f"  {f.name} = {value!r}")
    return "\n".join(lines)


__all__ = [
    "CliConfig",
    "DEFAULT_CONFIG_DIR",
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_THREADS_DIR",
    "format_config",
    "get_config_path",
    "get_config_value",
    "get_history_path",
    "get_project_dir",
    "get_sessions_dir",
    "load_config",
    "set_config_value",
]
