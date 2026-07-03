"""Logic for the `pydantic-deep keys` command group.

Pure, I/O-free helpers so the display and name-resolution are testable; the
typer commands in `main.py` handle prompting and printing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from apps.cli.credentials import CREDENTIALS, Credential, find_credential, mask
from apps.cli.keystore import get_stored_keys


@dataclass(frozen=True)
class KeyStatus:
    """Display row for one credential."""

    credential: Credential
    is_set: bool
    display_value: str  # masked/plain value, or "" when unset
    source: str  # "env", "stored", or ""


def iter_key_status() -> list[KeyStatus]:
    """Status of every known credential: set-or-not, masked value, source.

    A real environment variable is reported as ``source="env"``; a value only in
    keys.toml as ``source="stored"``.
    """
    stored = get_stored_keys()
    rows: list[KeyStatus] = []
    for cred in CREDENTIALS:
        env_val = os.environ.get(cred.env_var)
        if env_val:
            value, source = env_val, "env"
        elif cred.env_var in stored:
            value, source = stored[cred.env_var], "stored"
        else:
            rows.append(KeyStatus(cred, False, "", ""))
            continue
        shown = mask(value) if cred.secret else value
        rows.append(KeyStatus(cred, True, shown, source))
    return rows


def resolve_credential(token: str) -> Credential | None:
    """Resolve a user token to a credential.

    Accepts a 1-based index into ``CREDENTIALS``, an exact env-var name, or a
    case-insensitive env-var name. Returns None if nothing matches (the caller
    may still treat ``token`` as a free-form env var).
    """
    token = token.strip()
    if token.isdigit():
        idx = int(token) - 1
        if 0 <= idx < len(CREDENTIALS):
            return CREDENTIALS[idx]
        return None
    if (exact := find_credential(token)) is not None:
        return exact
    upper = token.upper()
    for cred in CREDENTIALS:
        if cred.env_var.upper() == upper:
            return cred
    return None


__all__ = ["KeyStatus", "iter_key_status", "resolve_credential"]
