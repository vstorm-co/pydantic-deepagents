"""Help modal — /help command."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

_HELP_TEXT = """\
[bold]Commands[/bold]

  [bold cyan]/clear[/bold cyan]       Clear conversation history
  [bold cyan]/compact[/bold cyan]     Compress context (LLM summarization)
  [bold cyan]/context[/bold cyan]     Show context window usage
  [bold cyan]/copy[/bold cyan]        Copy last response to clipboard
  [bold cyan]/cost[/bold cyan]        Show accumulated cost
  [bold cyan]/diff[/bold cyan]        Show git diff
  [bold cyan]/help[/bold cyan]        Show this help
  [bold cyan]/load[/bold cyan]        Load a saved session
  [bold cyan]/model[/bold cyan]       Change model
  [bold cyan]/provider[/bold cyan]    Configure AI provider
  [bold cyan]/remember[/bold cyan]    Add note to persistent memory
  [bold cyan]/remind[/bold cyan]      Switch periodic reminder mode (off / first / context / llm)
  [bold cyan]/save[/bold cyan]        Show save status
  [bold cyan]/settings[/bold cyan]    Open settings (edit config.toml)
  [bold cyan]/skills[/bold cyan]      List available skills
  [bold cyan]/todos[/bold cyan]       Toggle todo panel
  [bold cyan]/tokens[/bold cyan]      Show message count
  [bold cyan]/undo[/bold cyan]        Undo last turn
  [bold cyan]/version[/bold cyan]     Show version
  [bold cyan]/quit[/bold cyan]        Exit

[bold]Keyboard Shortcuts[/bold]

  [bold]Enter[/bold]        Send message
  [bold]Ctrl+J[/bold]       Toggle multiline input
  [bold]/[/bold]            Open command picker
  [bold]@[/bold]            Open file picker
  [bold]![/bold]            Shell command (e.g. [dim]!make test[/dim])
  [bold]Ctrl+K[/bold]       Toggle todos panel
  [bold]Ctrl+L[/bold]       Clear screen
  [bold]Ctrl+C[/bold]       Interrupt / exit
  [bold]Ctrl+D[/bold]       Exit
  [bold]PgUp/PgDn[/bold]    Scroll messages
  [bold]F1[/bold]           Help
  [bold]F2[/bold]           Settings
  [bold]F5[/bold]           Context usage
  [bold]Esc[/bold]          Close overlay / cancel
  [bold]↑ / ↓[/bold]        Input history (on empty input)

[bold]Tips[/bold]

  Prefix with [bold]![/bold] to run shell commands directly
  Use [bold]@filename[/bold] to reference files in your prompt
  Sessions are auto-saved after each turn
  Click on tool calls to expand/collapse output
"""


class HelpModal(ModalScreen[None]):
    """Scrollable help overlay."""

    DEFAULT_CSS = """
    HelpModal {
        align: center middle;
    }
    HelpModal > #help-container {
        width: 70;
        max-height: 85%;
        border: tall $primary;
        background: $surface;
        padding: 1 2;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-container"):
            yield Static(_HELP_TEXT)
            yield Static("[dim]Esc or q to close[/dim]")

    def action_dismiss(self) -> None:
        self.dismiss(None)
