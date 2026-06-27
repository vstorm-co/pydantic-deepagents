"""Per-session debug logging to .pydantic-deep/logs/.

Provides a structured logger that writes to per-session log files,
making it easy to diagnose issues after the fact.

Usage::

    from apps.cli.debug_log import setup_logger, get_logger

    # On session start:
    setup_logger("abc123")

    # Anywhere:
    log = get_logger()
    log.info("Agent started", model="claude-sonnet")
    log.debug("Tool call", tool="read_file", elapsed=0.3)
    log.error("Improve failed", exc_info=True)
"""

from __future__ import annotations

import contextlib
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOGGER_NAME = "pydantic_deep.tui"
_MAX_LOG_FILES = 20

# Third-party loggers that attach console/Rich handlers writing to the real
# terminal. Under the Textual TUI those paint over the live screen (e.g.
# fastmcp logging MCP `tools/list` traffic). Silenced at TUI launch.
_NOISY_CONSOLE_LOGGERS = (
    "fastmcp",
    "mcp",
    "httpx",
    "httpcore",
    "fastmcp.client",
    "py.warnings",  # warnings.warn() output, routed here via captureWarnings(True)
)


def quiet_console_logging() -> None:
    """Stop third-party libraries from logging to the terminal under the TUI.

    The TUI owns the screen; any library that writes to ``sys.stdout``/``stderr``
    (fastmcp/mcp use Rich handlers) corrupts the render. Drop those handlers,
    route to a NullHandler, stop propagation, and raise the level so even a
    stray record never reaches the console. Idempotent and exception-safe.
    """
    # fastmcp re-runs ``configure_logging`` (re-adding a stderr RichHandler) when
    # a client connects — mid-generation, painting "tools/list" over the screen.
    # Disabling its logging makes that reconfigure an early-return no-op for good.
    with contextlib.suppress(Exception):
        import fastmcp

        fastmcp.settings.log_enabled = False
        fastmcp.settings.enable_rich_logging = False

    for name in _NOISY_CONSOLE_LOGGERS:
        with contextlib.suppress(Exception):
            lg = logging.getLogger(name)
            lg.handlers = [logging.NullHandler()]
            lg.propagate = False
            lg.setLevel(logging.WARNING)


_logger: logging.Logger | None = None
_session_id: str = ""


class _StructuredFormatter(logging.Formatter):
    """Formatter that appends key=value pairs from the record's extras."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = getattr(record, "_extras", None)
        if extras:
            pairs = " ".join(f"{k}={v!r}" for k, v in extras.items())
            return f"{base}  {pairs}"
        return base


class _StructuredLogger:
    """Thin wrapper around stdlib Logger that supports keyword extras."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def debug(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.DEBUG, msg, kwargs)

    def info(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.INFO, msg, kwargs)

    def warning(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.WARNING, msg, kwargs)

    def error(self, msg: str, exc_info: bool = False, **kwargs: Any) -> None:
        self._log(logging.ERROR, msg, kwargs, exc_info=exc_info)

    def _log(
        self,
        level: int,
        msg: str,
        extras: dict[str, Any],
        exc_info: bool = False,
    ) -> None:
        record = self._logger.makeRecord(
            name=self._logger.name,
            level=level,
            fn="",
            lno=0,
            msg=msg,
            args=(),
            exc_info=sys.exc_info() if exc_info else None,
        )
        record._extras = extras  # type: ignore[attr-defined]
        self._logger.handle(record)


def _get_logs_dir() -> Path:
    """Return .pydantic-deep/logs/ directory, creating if needed."""
    try:
        from apps.cli.config import get_project_dir

        logs_dir = get_project_dir() / "logs"
    except Exception:
        logs_dir = Path.home() / ".pydantic-deep" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def _cleanup_old_logs(logs_dir: Path, keep: int = _MAX_LOG_FILES) -> None:
    """Remove old session log files, keeping the most recent ones."""
    log_files = sorted(
        [f for f in logs_dir.glob("session-*.log") if f.is_file()],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    for old_file in log_files[keep:]:
        with contextlib.suppress(OSError):
            old_file.unlink()


def _update_latest_symlink(logs_dir: Path, log_file: Path) -> None:
    """Create or update latest.log symlink."""
    latest = logs_dir / "latest.log"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(log_file.name)
    except OSError:
        pass


def setup_logger(session_id: str, level: int = logging.DEBUG) -> _StructuredLogger:
    """Initialize per-session logger.

    Creates a log file at `.pydantic-deep/logs/session-<id>.log`
    and a `latest.log` symlink pointing to it.

    Args:
        session_id: Unique session identifier (used in filename).
        level: Logging level (default: DEBUG).

    Returns:
        Structured logger instance.
    """
    global _logger, _session_id
    _session_id = session_id

    logs_dir = _get_logs_dir()
    log_file = logs_dir / f"session-{session_id}.log"

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level)

    # Remove existing handlers (e.g., from previous session in same process)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()

    # File handler
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setLevel(level)
    formatter = _StructuredFormatter(
        fmt="[%(asctime)s] [%(levelname)-5s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Prevent propagation to root logger (no stdout spam)
    logger.propagate = False

    _logger = logger

    # Symlink and cleanup
    _update_latest_symlink(logs_dir, log_file)
    _cleanup_old_logs(logs_dir)

    # Initial log entry
    structured = _StructuredLogger(logger)
    structured.info(
        "Session started",
        session_id=session_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    return structured


def get_logger() -> _StructuredLogger:
    """Get the current session logger.

    Returns a no-op logger if `setup_logger()` hasn't been called yet.
    """
    global _logger
    if _logger is None:
        # Return a logger that writes nowhere (NullHandler)
        logger = logging.getLogger(_LOGGER_NAME)
        if not logger.handlers:
            logger.addHandler(logging.NullHandler())
        _logger = logger
    return _StructuredLogger(_logger)


def get_session_id() -> str:
    """Return the current session ID."""
    return _session_id
