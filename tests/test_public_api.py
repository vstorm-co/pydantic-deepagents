"""The blessed top-level surface stays wired to the canonical feature modules.

Every feature lives in `pydantic_deep.features.<name>`; `pydantic_deep` re-exports
the public names. These tests assert the re-exports are the same objects, so a
move inside a feature package can never silently change the public API.
"""

from __future__ import annotations

import pydantic_deep
from pydantic_deep.features import browser as browser_feature
from pydantic_deep.features import checkpointing as checkpointing_feature
from pydantic_deep.features import context as context_feature
from pydantic_deep.features import eviction as eviction_feature
from pydantic_deep.features import forking as forking_feature
from pydantic_deep.features import hooks as hooks_feature
from pydantic_deep.features import liteparse as liteparse_feature
from pydantic_deep.features import memory as memory_feature
from pydantic_deep.features import patch as patch_feature
from pydantic_deep.features import periodic_reminder as periodic_reminder_feature
from pydantic_deep.features import plan as plan_feature
from pydantic_deep.features import skills as skills_feature
from pydantic_deep.features import stuck_loop as stuck_loop_feature
from pydantic_deep.features import teams as teams_feature


def test_memory_exports() -> None:
    assert pydantic_deep.AgentMemoryToolset is memory_feature.AgentMemoryToolset
    assert pydantic_deep.MemoryCapability is memory_feature.MemoryCapability
    assert pydantic_deep.MemoryFile is memory_feature.MemoryFile


def test_context_exports() -> None:
    assert pydantic_deep.ContextToolset is context_feature.ContextToolset
    assert pydantic_deep.ContextFilesCapability is context_feature.ContextFilesCapability
    assert pydantic_deep.ContextFile is context_feature.ContextFile


def test_browser_exports() -> None:
    assert pydantic_deep.BrowserToolset is browser_feature.BrowserToolset
    assert pydantic_deep.BrowserCapability is browser_feature.BrowserCapability


def test_eviction_exports() -> None:
    assert pydantic_deep.EvictionCapability is eviction_feature.EvictionCapability


def test_patch_exports() -> None:
    assert pydantic_deep.PatchToolCallsCapability is patch_feature.PatchToolCallsCapability
    assert pydantic_deep.patch_tool_calls_processor is patch_feature.patch_tool_calls_processor


def test_checkpointing_exports() -> None:
    assert pydantic_deep.InMemoryCheckpointStore is checkpointing_feature.InMemoryCheckpointStore
    assert pydantic_deep.CheckpointMiddleware is checkpointing_feature.CheckpointMiddleware
    assert pydantic_deep.CheckpointToolset is checkpointing_feature.CheckpointToolset


def test_liteparse_exports() -> None:
    assert pydantic_deep.LiteparseToolset is liteparse_feature.LiteparseToolset


def test_forking_exports() -> None:
    assert pydantic_deep.ForkCoordinator is forking_feature.ForkCoordinator
    assert pydantic_deep.LiveForkCapability is forking_feature.capability.LiveForkCapability
    assert pydantic_deep.create_fork_toolset is forking_feature.create_fork_toolset


def test_skills_exports() -> None:
    assert pydantic_deep.SkillsToolset is skills_feature.SkillsToolset
    assert pydantic_deep.SkillsCapability is skills_feature.SkillsCapability
    assert pydantic_deep.Skill is skills_feature.Skill


def test_plan_exports() -> None:
    assert pydantic_deep.PlanOption is plan_feature.PlanOption
    assert pydantic_deep.create_plan_toolset is plan_feature.create_plan_toolset


def test_teams_exports() -> None:
    assert pydantic_deep.AgentTeam is teams_feature.AgentTeam
    assert pydantic_deep.create_team_toolset is teams_feature.create_team_toolset


def test_hooks_exports() -> None:
    assert pydantic_deep.HooksCapability is hooks_feature.HooksCapability
    assert pydantic_deep.Hook is hooks_feature.Hook
    assert pydantic_deep.HookEvent is hooks_feature.HookEvent


def test_stuck_loop_exports() -> None:
    assert pydantic_deep.StuckLoopDetection is stuck_loop_feature.StuckLoopDetection
    assert pydantic_deep.StuckLoopError is stuck_loop_feature.StuckLoopError


def test_periodic_reminder_exports() -> None:
    assert (
        pydantic_deep.PeriodicReminderCapability
        is periodic_reminder_feature.PeriodicReminderCapability
    )
    assert pydantic_deep.make_config_for_mode is periodic_reminder_feature.make_config_for_mode
