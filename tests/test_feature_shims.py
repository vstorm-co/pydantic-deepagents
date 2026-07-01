"""Backward-compat shims for moved feature modules (reorg option C).

Each feature moved to `pydantic_deep.features.<name>`; the old deep import
paths remain as deprecation shims that re-export the public names. These tests
assert the shims still resolve the names and emit a DeprecationWarning.
"""

from __future__ import annotations

import importlib

import pytest

import pydantic_deep
from pydantic_deep.features import browser as browser_feature
from pydantic_deep.features import checkpointing as checkpointing_feature
from pydantic_deep.features import context as context_feature
from pydantic_deep.features import eviction as eviction_feature
from pydantic_deep.features import forking as forking_feature
from pydantic_deep.features import history_archive as history_archive_feature
from pydantic_deep.features import hooks as hooks_feature
from pydantic_deep.features import improve as improve_feature
from pydantic_deep.features import liteparse as liteparse_feature
from pydantic_deep.features import memory as memory_feature
from pydantic_deep.features import message_queue as message_queue_feature
from pydantic_deep.features import patch as patch_feature
from pydantic_deep.features import periodic_reminder as periodic_reminder_feature
from pydantic_deep.features import plan as plan_feature
from pydantic_deep.features import skills as skills_feature
from pydantic_deep.features import stuck_loop as stuck_loop_feature
from pydantic_deep.features import teams as teams_feature


class TestMemoryShim:
    def test_toolsets_memory_reexports_and_warns(self) -> None:
        import pydantic_deep.toolsets.memory as shim

        with pytest.warns(DeprecationWarning, match="features.memory"):
            importlib.reload(shim)

        # Names resolve to the canonical feature objects.
        assert shim.AgentMemoryToolset is memory_feature.AgentMemoryToolset
        assert shim.MemoryFile is memory_feature.MemoryFile
        assert shim.MemoryAccessError is memory_feature.MemoryAccessError
        assert shim.load_memory is memory_feature.load_memory
        assert shim.get_memory_path is memory_feature.get_memory_path
        assert shim.format_memory_prompt is memory_feature.format_memory_prompt
        assert shim.DEFAULT_MEMORY_DIR == memory_feature.DEFAULT_MEMORY_DIR
        # Private helper preserved for back-compat.
        assert callable(shim._select_recent_lines)

    def test_capabilities_memory_reexports_and_warns(self) -> None:
        import pydantic_deep.capabilities.memory as shim

        with pytest.warns(DeprecationWarning, match="features.memory"):
            importlib.reload(shim)

        assert shim.MemoryCapability is memory_feature.MemoryCapability

    def test_top_level_exports_stable(self) -> None:
        # The blessed top-level surface keeps working unchanged.
        assert pydantic_deep.AgentMemoryToolset is memory_feature.AgentMemoryToolset
        assert pydantic_deep.MemoryCapability is memory_feature.MemoryCapability
        assert pydantic_deep.MemoryFile is memory_feature.MemoryFile


class TestContextShim:
    def test_toolsets_context_reexports_and_warns(self) -> None:
        import pydantic_deep.toolsets.context as shim

        with pytest.warns(DeprecationWarning, match="features.context"):
            importlib.reload(shim)

        assert shim.ContextToolset is context_feature.ContextToolset
        assert shim.ContextFile is context_feature.ContextFile
        assert shim.load_context_files is context_feature.load_context_files
        assert shim.format_context_prompt is context_feature.format_context_prompt
        assert shim.DEFAULT_CONTEXT_FILENAMES == context_feature.DEFAULT_CONTEXT_FILENAMES
        assert callable(shim._discover_and_load)

    def test_capabilities_context_reexports_and_warns(self) -> None:
        import pydantic_deep.capabilities.context as shim

        with pytest.warns(DeprecationWarning, match="features.context"):
            importlib.reload(shim)

        assert shim.ContextFilesCapability is context_feature.ContextFilesCapability

    def test_top_level_exports_stable(self) -> None:
        assert pydantic_deep.ContextToolset is context_feature.ContextToolset
        assert pydantic_deep.ContextFilesCapability is context_feature.ContextFilesCapability
        assert pydantic_deep.ContextFile is context_feature.ContextFile


class TestBrowserShim:
    def test_toolsets_browser_reexports_and_warns(self) -> None:
        import pydantic_deep.toolsets.browser as shim

        with pytest.warns(DeprecationWarning, match="features.browser"):
            importlib.reload(shim)

        assert shim.BrowserToolset is browser_feature.BrowserToolset
        assert shim.DEFAULT_TIMEOUT_MS == browser_feature.DEFAULT_TIMEOUT_MS
        assert callable(shim._html_to_markdown)
        assert callable(shim._check_allowed_domain)

    def test_capabilities_browser_reexports_and_warns(self) -> None:
        import pydantic_deep.capabilities.browser as shim

        with pytest.warns(DeprecationWarning, match="features.browser"):
            importlib.reload(shim)

        assert shim.BrowserCapability is browser_feature.BrowserCapability
        assert shim.BROWSER_INSTRUCTIONS == browser_feature.BROWSER_INSTRUCTIONS

    def test_top_level_exports_stable(self) -> None:
        assert pydantic_deep.BrowserToolset is browser_feature.BrowserToolset
        assert pydantic_deep.BrowserCapability is browser_feature.BrowserCapability


class TestEvictionShim:
    def test_processors_eviction_reexports_and_warns(self) -> None:
        import pydantic_deep.processors.eviction as shim

        with pytest.warns(DeprecationWarning, match="features.eviction"):
            importlib.reload(shim)

        assert shim.EvictionCapability is eviction_feature.EvictionCapability
        assert shim.DEFAULT_TOKEN_LIMIT == eviction_feature.DEFAULT_TOKEN_LIMIT
        assert callable(shim._content_to_str)
        assert callable(shim._sanitize_id)

    def test_top_level_exports_stable(self) -> None:
        assert pydantic_deep.EvictionCapability is eviction_feature.EvictionCapability


class TestPatchShim:
    def test_processors_patch_reexports_and_warns(self) -> None:
        import pydantic_deep.processors.patch as shim

        with pytest.warns(DeprecationWarning, match="features.patch"):
            importlib.reload(shim)

        assert shim.PatchToolCallsCapability is patch_feature.PatchToolCallsCapability
        assert shim.patch_tool_calls_processor is patch_feature.patch_tool_calls_processor
        assert shim.CANCELLED_MESSAGE == patch_feature.CANCELLED_MESSAGE

    def test_top_level_exports_stable(self) -> None:
        assert pydantic_deep.PatchToolCallsCapability is patch_feature.PatchToolCallsCapability


class TestHistoryArchiveShim:
    def test_processors_history_archive_reexports_and_warns(self) -> None:
        import pydantic_deep.processors.history_archive as shim

        with pytest.warns(DeprecationWarning, match="features.history_archive"):
            importlib.reload(shim)

        assert (
            shim.create_history_search_toolset
            is history_archive_feature.create_history_search_toolset
        )
        assert shim.SEARCH_HISTORY_DESCRIPTION == history_archive_feature.SEARCH_HISTORY_DESCRIPTION
        assert callable(shim._bm25_rank)
        assert callable(shim._load_messages)


class TestCheckpointingShim:
    def test_toolsets_checkpointing_reexports_and_warns(self) -> None:
        import pydantic_deep.toolsets.checkpointing as shim

        with pytest.warns(DeprecationWarning, match="features.checkpointing"):
            importlib.reload(shim)

        assert shim.InMemoryCheckpointStore is checkpointing_feature.InMemoryCheckpointStore
        assert shim.CheckpointMiddleware is checkpointing_feature.CheckpointMiddleware
        assert shim.CheckpointToolset is checkpointing_feature.CheckpointToolset

    def test_top_level_exports_stable(self) -> None:
        assert (
            pydantic_deep.InMemoryCheckpointStore is checkpointing_feature.InMemoryCheckpointStore
        )


class TestLiteparseShim:
    def test_toolsets_liteparse_reexports_and_warns(self) -> None:
        import pydantic_deep.toolsets.liteparse as shim

        with pytest.warns(DeprecationWarning, match="features.liteparse"):
            importlib.reload(shim)

        assert shim.LiteparseToolset is liteparse_feature.LiteparseToolset
        assert shim.PARSE_DOCUMENT_DESCRIPTION == liteparse_feature.PARSE_DOCUMENT_DESCRIPTION

    def test_top_level_exports_stable(self) -> None:
        assert pydantic_deep.LiteparseToolset is liteparse_feature.LiteparseToolset


class TestForkingShim:
    def test_toolsets_forking_reexports_and_warns(self) -> None:
        import pydantic_deep.toolsets.forking as shim

        with pytest.warns(DeprecationWarning, match="features.forking"):
            importlib.reload(shim)

        assert shim.ForkCoordinator is forking_feature.ForkCoordinator
        assert shim.create_fork_toolset is forking_feature.create_fork_toolset

    def test_forking_submodule_shims_resolve(self) -> None:
        # Every documented deep submodule path still resolves through its shim.
        from pydantic_deep.features.forking import coordinator as feat_coord
        from pydantic_deep.features.forking import types as feat_types
        from pydantic_deep.toolsets.forking.budget import BudgetWatcher
        from pydantic_deep.toolsets.forking.coordinator import ForkCoordinator
        from pydantic_deep.toolsets.forking.diff import build_diff_report
        from pydantic_deep.toolsets.forking.editor import EditorDetector
        from pydantic_deep.toolsets.forking.isolation import clone_for_branch
        from pydantic_deep.toolsets.forking.judge import JudgeAgent
        from pydantic_deep.toolsets.forking.materializer import ForkMaterializer
        from pydantic_deep.toolsets.forking.store import InMemoryForkStateStore
        from pydantic_deep.toolsets.forking.types import BranchSpec

        assert ForkCoordinator is feat_coord.ForkCoordinator
        assert build_diff_report is forking_feature.build_diff_report
        assert clone_for_branch is forking_feature.clone_for_branch
        assert JudgeAgent is forking_feature.JudgeAgent
        # Reachable, distinct symbols from each shimmed submodule.
        assert BudgetWatcher is not None
        assert EditorDetector is not None
        assert ForkMaterializer is not None
        assert InMemoryForkStateStore is forking_feature.InMemoryForkStateStore
        assert BranchSpec is feat_types.BranchSpec

    def test_capabilities_forking_reexports_and_warns(self) -> None:
        import pydantic_deep.capabilities.forking as shim

        with pytest.warns(DeprecationWarning, match="features.forking"):
            importlib.reload(shim)

        assert shim.LiveForkCapability is forking_feature.capability.LiveForkCapability

    def test_top_level_exports_stable(self) -> None:
        assert pydantic_deep.ForkCoordinator is forking_feature.ForkCoordinator
        assert pydantic_deep.LiveForkCapability is forking_feature.capability.LiveForkCapability


class TestSkillsShim:
    def test_toolsets_skills_reexports_and_warns(self) -> None:
        import pydantic_deep.toolsets.skills as shim

        with pytest.warns(DeprecationWarning, match="features.skills"):
            importlib.reload(shim)

        assert shim.SkillsToolset is skills_feature.SkillsToolset
        assert shim.Skill is skills_feature.Skill
        assert shim.SkillsCapability is skills_feature.SkillsCapability

    def test_skills_submodule_shims_resolve(self) -> None:
        # Every documented deep submodule path still resolves through its shim.
        from pydantic_deep.features.skills import backend as feat_backend
        from pydantic_deep.features.skills import directory as feat_directory
        from pydantic_deep.toolsets.skills.backend import BackendSkillsDirectory
        from pydantic_deep.toolsets.skills.directory import SkillsDirectory
        from pydantic_deep.toolsets.skills.exceptions import SkillException
        from pydantic_deep.toolsets.skills.local import LocalSkillScriptExecutor
        from pydantic_deep.toolsets.skills.toolset import SkillsToolset
        from pydantic_deep.toolsets.skills.types import Skill as ShimSkill

        assert BackendSkillsDirectory is feat_backend.BackendSkillsDirectory
        assert SkillsDirectory is feat_directory.SkillsDirectory
        assert ShimSkill is skills_feature.Skill
        assert SkillException is skills_feature.SkillException
        assert LocalSkillScriptExecutor is skills_feature.LocalSkillScriptExecutor
        assert SkillsToolset is skills_feature.SkillsToolset

    def test_capabilities_skills_reexports_and_warns(self) -> None:
        import pydantic_deep.capabilities.skills as shim

        with pytest.warns(DeprecationWarning, match="features.skills"):
            importlib.reload(shim)

        assert shim.SkillsCapability is skills_feature.SkillsCapability

    def test_top_level_exports_stable(self) -> None:
        assert pydantic_deep.SkillsToolset is skills_feature.SkillsToolset
        assert pydantic_deep.SkillsCapability is skills_feature.SkillsCapability


class TestPlanShim:
    def test_toolsets_plan_reexports_and_warns(self) -> None:
        import pydantic_deep.toolsets.plan as shim

        with pytest.warns(DeprecationWarning, match="features.plan"):
            importlib.reload(shim)

        assert shim.create_plan_toolset is plan_feature.create_plan_toolset
        assert shim.PlanOption is plan_feature.PlanOption

    def test_top_level_exports_stable(self) -> None:
        assert pydantic_deep.PlanOption is plan_feature.PlanOption


class TestTeamsShim:
    def test_toolsets_teams_reexports_and_warns(self) -> None:
        import pydantic_deep.toolsets.teams as shim

        with pytest.warns(DeprecationWarning, match="features.teams"):
            importlib.reload(shim)

        assert shim.AgentTeam is teams_feature.AgentTeam
        assert shim.create_team_toolset is teams_feature.create_team_toolset
        assert shim.TeamMessageBus is teams_feature.TeamMessageBus

    def test_top_level_exports_stable(self) -> None:
        assert pydantic_deep.AgentTeam is teams_feature.AgentTeam
        assert pydantic_deep.create_team_toolset is teams_feature.create_team_toolset


class TestMessageQueueShim:
    def test_capabilities_message_queue_reexports_and_warns(self) -> None:
        import pydantic_deep.capabilities.message_queue as shim

        with pytest.warns(DeprecationWarning, match="features.message_queue"):
            importlib.reload(shim)

        assert shim.MessageQueue is message_queue_feature.MessageQueue
        assert shim.MessageQueueCapability is message_queue_feature.MessageQueueCapability
        assert shim.run_with_queue is message_queue_feature.run_with_queue


class TestHooksShim:
    def test_capabilities_hooks_reexports_and_warns(self) -> None:
        import pydantic_deep.capabilities.hooks as shim

        with pytest.warns(DeprecationWarning, match="features.hooks"):
            importlib.reload(shim)

        assert shim.HooksCapability is hooks_feature.HooksCapability
        assert shim.Hook is hooks_feature.Hook
        assert shim.HookEvent is hooks_feature.HookEvent
        assert shim.default_security_hook is hooks_feature.default_security_hook
        assert callable(shim._match_hooks)
        assert callable(shim._run_hook)

    def test_top_level_exports_stable(self) -> None:
        assert pydantic_deep.HooksCapability is hooks_feature.HooksCapability
        assert pydantic_deep.Hook is hooks_feature.Hook


class TestImproveShim:
    def test_improve_package_reexports_and_warns(self) -> None:
        import pydantic_deep.improve as shim

        with pytest.warns(DeprecationWarning, match="features.improve"):
            importlib.reload(shim)

        assert shim.SessionExtractor is improve_feature.SessionExtractor
        assert shim.ImproveToolset is improve_feature.ImproveToolset
        assert shim.ImprovementReport is improve_feature.ImprovementReport

    def test_toolsets_improve_reexports_and_warns(self) -> None:
        import pydantic_deep.toolsets.improve as shim

        with pytest.warns(DeprecationWarning, match="features.improve"):
            importlib.reload(shim)

        assert shim.ImproveToolset is improve_feature.ImproveToolset
        assert callable(shim._format_report)
        assert callable(shim._format_status)


class TestStuckLoopShim:
    def test_capabilities_stuck_loop_reexports_and_warns(self) -> None:
        import pydantic_deep.capabilities.stuck_loop as shim

        with pytest.warns(DeprecationWarning, match="features.stuck_loop"):
            importlib.reload(shim)

        assert shim.StuckLoopDetection is stuck_loop_feature.StuckLoopDetection
        assert shim.StuckLoopError is stuck_loop_feature.StuckLoopError

    def test_top_level_exports_stable(self) -> None:
        assert pydantic_deep.StuckLoopDetection is stuck_loop_feature.StuckLoopDetection
        assert pydantic_deep.StuckLoopError is stuck_loop_feature.StuckLoopError


class TestPeriodicReminderShim:
    def test_capabilities_periodic_reminder_reexports_and_warns(self) -> None:
        import pydantic_deep.capabilities.periodic_reminder as shim

        with pytest.warns(DeprecationWarning, match="features.periodic_reminder"):
            importlib.reload(shim)

        assert (
            shim.PeriodicReminderCapability is periodic_reminder_feature.PeriodicReminderCapability
        )
        assert shim.make_config_for_mode is periodic_reminder_feature.make_config_for_mode
        assert callable(shim._should_fire)

    def test_top_level_exports_stable(self) -> None:
        assert (
            pydantic_deep.PeriodicReminderCapability
            is periodic_reminder_feature.PeriodicReminderCapability
        )
