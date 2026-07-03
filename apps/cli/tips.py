"""Rotating tips shown on the welcome hero.

A small, curated set surfacing features people miss. `random_tip` picks one for
the session; the hero rotates through the rest on a timer.
"""

from __future__ import annotations

import random

TIPS: tuple[str, ...] = (
    "Type [b]/model[/b] to switch models — search across every provider you have a key for.",
    "Set API keys without leaving the app: [b]/keys[/b] opens a searchable picker.",
    "Change reasoning depth on the fly with [b]/thinking[/b] (minimal → xhigh).",
    "[b]/init[/b] analyses your project and writes an AGENTS.md so the agent has context.",
    "Reference files inline by typing [b]@[/b] — a fuzzy file picker pops up.",
    "Run [b]/skills[/b] to see reusable skills the agent can load on demand.",
    "Delegate parallel work to sub-agents — they run in the background and report back.",
    "[b]/fork[/b] branches the conversation so you can explore an idea without losing your place.",
    "[b]/compact[/b] summarises the conversation to reclaim context when it fills up.",
    "[b]/cost[/b] shows token usage and USD spend for the session.",
    "Drop in an image from your clipboard with [b]/paste[/b].",
    "Press [b]?[/b] any time for the full list of commands.",
    "Your notes live in MEMORY.md — use [b]/remember[/b] to add one the agent will recall.",
    "[b]/theme[/b] switches the colour scheme; it's saved to your config.",
)


def random_tip() -> str:
    """Return a random tip for this session."""
    return random.choice(TIPS)


def tip_cycle(start: str | None = None) -> list[str]:
    """All tips ordered so `start` (if given) comes first — for timed rotation."""
    tips = list(TIPS)
    if start in tips:
        i = tips.index(start)
        tips = tips[i:] + tips[:i]
    return tips


__all__ = ["TIPS", "random_tip", "tip_cycle"]
