"""Remember which models the user has used, most-recent-first.

Persisted to ``~/.pydantic-deep/model_history.json`` (user-level, cross-project)
so the model picker and onboarding can offer recent choices instead of a blank
prompt.
"""

from __future__ import annotations

import json
from pathlib import Path

from apps.cli.config import get_global_dir

_MAX_HISTORY = 12


def _history_path() -> Path:
    return get_global_dir() / "model_history.json"


def recent_models() -> list[str]:
    """Return previously used models, most-recent-first (may be empty)."""
    path = _history_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [m for m in data if isinstance(m, str) and m]


def record_model_use(model: str) -> None:
    """Record `model` as the most recently used (dedup, capped, newest first)."""
    model = (model or "").strip()
    if not model:
        return
    history = [m for m in recent_models() if m != model]
    history.insert(0, model)
    history = history[:_MAX_HISTORY]
    path = _history_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(history, indent=2) + "\n")
    except OSError:
        pass  # history is best-effort; never break a run over it


__all__ = ["record_model_use", "recent_models"]
