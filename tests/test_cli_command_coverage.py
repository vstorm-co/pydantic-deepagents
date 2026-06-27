"""Guard: every registered slash command is documented in the picker and help.

Stale help/picker entries are a real annoyance — these tests fail the moment a
new command is registered without being surfaced to users.
"""

from __future__ import annotations

import re

from apps.cli.commands import _COMMANDS
from apps.cli.modals.command_picker import COMMANDS as PICKER_COMMANDS

# Aliases that intentionally don't get their own picker/help line.
_ALIASES = {"/exit", "/q"}


def _registered() -> set[str]:
    return {c for c in _COMMANDS if c not in _ALIASES}


def test_every_command_in_picker() -> None:
    picker = {cmd.split()[0] for cmd, _ in PICKER_COMMANDS}
    missing = _registered() - picker
    assert not missing, f"commands missing from the command picker: {sorted(missing)}"


def test_every_command_in_help() -> None:
    from apps.cli.modals.help_view import _HELP_TEXT

    documented = set(re.findall(r"/[a-z-]+", _HELP_TEXT))
    missing = _registered() - documented
    assert not missing, f"commands missing from /help: {sorted(missing)}"


def test_no_phantom_picker_commands() -> None:
    # Every picker entry (minus arg-variants like "/fork diff") is dispatchable.
    registered = _registered()
    for cmd, _ in PICKER_COMMANDS:
        head = cmd.split()[0]
        assert head in registered, f"picker lists unregistered command: {cmd}"
