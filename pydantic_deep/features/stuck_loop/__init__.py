"""Stuck-loop-detection feature — warn/error on repetitive agent tool-call loops.

A lifecycle-only slice: `capability.py` (StuckLoopDetection + StuckLoopError).
"""

from pydantic_deep.features.stuck_loop.capability import StuckLoopDetection, StuckLoopError

__all__ = ["StuckLoopDetection", "StuckLoopError"]
