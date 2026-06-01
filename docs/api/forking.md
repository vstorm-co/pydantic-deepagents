# Forking API

Live Run Forking lets an agent explore multiple solution branches in parallel and
merge the best result. Enable it via `forking=True` on
[`create_deep_agent`][pydantic_deep.agent.create_deep_agent]. See
[Live Run Forking](../capabilities/live-fork.md) for the conceptual overview.

## LiveForkCapability

::: pydantic_deep.capabilities.forking.LiveForkCapability
    options:
      show_source: false

## ForkCoordinator

::: pydantic_deep.toolsets.forking.ForkCoordinator
    options:
      show_source: false

## create_fork_toolset

::: pydantic_deep.toolsets.forking.create_fork_toolset
    options:
      show_source: false

## ForkStateStore

::: pydantic_deep.toolsets.forking.ForkStateStore
    options:
      show_source: false

## InMemoryForkStateStore

::: pydantic_deep.toolsets.forking.InMemoryForkStateStore
    options:
      show_source: false

## build_diff_report

::: pydantic_deep.toolsets.forking.build_diff_report
    options:
      show_source: false

## JudgeAgent

::: pydantic_deep.toolsets.forking.JudgeAgent
    options:
      show_source: false

## compute_confidence

::: pydantic_deep.toolsets.forking.compute_confidence
    options:
      show_source: false

## Coordinator

::: pydantic_deep.toolsets.forking.coordinator.ForkBranchLimitError
    options:
      show_source: false

::: pydantic_deep.toolsets.forking.coordinator.ForkDepthLimitError
    options:
      show_source: false

## Isolation

::: pydantic_deep.toolsets.forking.isolation.BranchOverlay
    options:
      show_source: false

::: pydantic_deep.toolsets.forking.isolation.clone_for_branch
    options:
      show_source: false

## Editor

::: pydantic_deep.toolsets.forking.editor.EditorDetector
    options:
      show_source: false

## Judge

::: pydantic_deep.toolsets.forking.judge.count_retry_parts
    options:
      show_source: false

::: pydantic_deep.toolsets.forking.judge.count_stuck_loop_hits
    options:
      show_source: false

## Materializer

::: pydantic_deep.toolsets.forking.materializer.ForkMaterializer
    options:
      show_source: false

## Forking Types

::: pydantic_deep.types.BranchSpec
    options:
      show_source: false

::: pydantic_deep.types.BranchState
    options:
      show_source: false

::: pydantic_deep.types.BranchStatus
    options:
      show_source: false

::: pydantic_deep.types.BranchOutcome
    options:
      show_source: false

::: pydantic_deep.types.BranchIsolation
    options:
      show_source: false

::: pydantic_deep.types.BranchChange
    options:
      show_source: false

::: pydantic_deep.types.BranchCost
    options:
      show_source: false

::: pydantic_deep.types.BranchDiffAgreement
    options:
      show_source: false

::: pydantic_deep.types.BranchDiffOperation
    options:
      show_source: false

::: pydantic_deep.types.BranchDiffReport
    options:
      show_source: false

::: pydantic_deep.types.ConfidenceSignals
    options:
      show_source: false

::: pydantic_deep.types.DiffSummary
    options:
      show_source: false

::: pydantic_deep.types.FileChange
    options:
      show_source: false

::: pydantic_deep.types.FlushError
    options:
      show_source: false

::: pydantic_deep.types.FlushReport
    options:
      show_source: false

::: pydantic_deep.types.ForkCostSummary
    options:
      show_source: false

::: pydantic_deep.types.ForkHandle
    options:
      show_source: false

::: pydantic_deep.types.JudgeVerdict
    options:
      show_source: false

::: pydantic_deep.types.MergeResult
    options:
      show_source: false

::: pydantic_deep.types.MergeStrategy
    options:
      show_source: false

::: pydantic_deep.types.PathDiff
    options:
      show_source: false

::: pydantic_deep.types.ResolveOutcome
    options:
      show_source: false
