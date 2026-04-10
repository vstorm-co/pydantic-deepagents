"""Toast notification system — non-blocking notifications in the top-right.

Uses Textual's built-in notify() system. All notifications are also
written to the per-session debug log for post-hoc diagnostics.
"""

from __future__ import annotations

from apps.cli.debug_log import get_logger


def notify_info(app: object, message: str) -> None:
    """Show an info notification."""
    get_logger().info(f"[notify] {message}")
    app.notify(message, severity="information", timeout=4)  # type: ignore[union-attr]


def notify_success(app: object, message: str) -> None:
    """Show a success notification."""
    get_logger().info(f"[notify] {message}")
    app.notify(message, severity="information", timeout=4)  # type: ignore[union-attr]


def notify_warning(app: object, message: str) -> None:
    """Show a warning notification."""
    get_logger().warning(f"[notify] {message}")
    app.notify(message, severity="warning", timeout=5)  # type: ignore[union-attr]


def notify_error(app: object, message: str) -> None:
    """Show an error notification."""
    get_logger().error(f"[notify] {message}")
    app.notify(message, severity="error", timeout=6)  # type: ignore[union-attr]
