# Forking API

Live Run Forking lets an agent explore multiple solution branches in parallel and
merge the best result. Enable it via `forking=True` on
[`create_deep_agent`][pydantic_deep.agent.create_deep_agent]. See
[Live Run Forking](../advanced/forking.md) for the conceptual overview.

## LiveForkCapability

::: pydantic_deep.features.forking.capability.LiveForkCapability
    options:
      show_source: false

## ForkCoordinator

::: pydantic_deep.features.forking.ForkCoordinator
    options:
      show_source: false

## create_fork_toolset

::: pydantic_deep.features.forking.create_fork_toolset
    options:
      show_source: false

## ForkStateStore

::: pydantic_deep.features.forking.ForkStateStore
    options:
      show_source: false

## InMemoryForkStateStore

::: pydantic_deep.features.forking.InMemoryForkStateStore
    options:
      show_source: false

## build_diff_report

::: pydantic_deep.features.forking.build_diff_report
    options:
      show_source: false

## JudgeAgent

::: pydantic_deep.features.forking.JudgeAgent
    options:
      show_source: false

## compute_confidence

::: pydantic_deep.features.forking.compute_confidence
    options:
      show_source: false

## Coordinator

::: pydantic_deep.features.forking.coordinator.ForkBranchLimitError
    options:
      show_source: false

::: pydantic_deep.features.forking.coordinator.ForkDepthLimitError
    options:
      show_source: false

## Isolation

::: pydantic_deep.features.forking.isolation.BranchOverlay
    options:
      show_source: false

::: pydantic_deep.features.forking.isolation.clone_for_branch
    options:
      show_source: false

## Editor

::: pydantic_deep.features.forking.editor.EditorDetector
    options:
      show_source: false

## Judge

::: pydantic_deep.features.forking.judge.count_retry_parts
    options:
      show_source: false

::: pydantic_deep.features.forking.judge.count_stuck_loop_hits
    options:
      show_source: false

## Materializer

::: pydantic_deep.features.forking.materializer.ForkMaterializer
    options:
      show_source: false

## Forking Types

::: pydantic_deep.features.forking.types.BranchSpec
    options:
      show_source: false

::: pydantic_deep.features.forking.types.BranchState
    options:
      show_source: false

::: pydantic_deep.features.forking.types.BranchStatus
    options:
      show_source: false

::: pydantic_deep.features.forking.types.BranchOutcome
    options:
      show_source: false

::: pydantic_deep.features.forking.types.BranchIsolation
    options:
      show_source: false

::: pydantic_deep.features.forking.types.BranchChange
    options:
      show_source: false

::: pydantic_deep.features.forking.types.BranchCost
    options:
      show_source: false

::: pydantic_deep.features.forking.types.BranchDiffAgreement
    options:
      show_source: false

::: pydantic_deep.features.forking.types.BranchDiffOperation
    options:
      show_source: false

::: pydantic_deep.features.forking.types.BranchDiffReport
    options:
      show_source: false

::: pydantic_deep.features.forking.types.ConfidenceSignals
    options:
      show_source: false

::: pydantic_deep.features.forking.types.DiffSummary
    options:
      show_source: false

::: pydantic_deep.features.forking.types.FileChange
    options:
      show_source: false

::: pydantic_deep.features.forking.types.FlushError
    options:
      show_source: false

::: pydantic_deep.features.forking.types.FlushReport
    options:
      show_source: false

::: pydantic_deep.features.forking.types.ForkCostSummary
    options:
      show_source: false

::: pydantic_deep.features.forking.types.ForkHandle
    options:
      show_source: false

::: pydantic_deep.features.forking.types.JudgeVerdict
    options:
      show_source: false

::: pydantic_deep.features.forking.types.MergeResult
    options:
      show_source: false

::: pydantic_deep.features.forking.types.MergeStrategy
    options:
      show_source: false

::: pydantic_deep.features.forking.types.PathDiff
    options:
      show_source: false

::: pydantic_deep.features.forking.types.ResolveOutcome
    options:
      show_source: false
