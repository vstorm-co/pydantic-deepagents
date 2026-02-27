"""Data models for SWE-bench evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SWEBenchInstance:
    """A single SWE-bench evaluation instance.

    Mirrors the HuggingFace dataset columns from princeton-nlp/SWE-bench.
    """

    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    hints_text: str = ""
    patch: str = ""  # Gold patch (for reference, not shown to agent)
    test_patch: str = ""
    FAIL_TO_PASS: str = ""  # JSON list of test names
    PASS_TO_PASS: str = ""  # JSON list of test names
    version: str = ""
    environment_setup_commit: str = ""


@dataclass
class Prediction:
    """SWE-bench prediction output format (JSONL).

    Format expected by ``swebench.harness.run_evaluation``.
    """

    instance_id: str
    model_name_or_path: str
    model_patch: str

    def to_dict(self) -> dict[str, str]:
        return {
            "instance_id": self.instance_id,
            "model_name_or_path": self.model_name_or_path,
            "model_patch": self.model_patch,
        }


@dataclass
class InstanceResult:
    """Result from running the agent on a single SWE-bench instance."""

    instance_id: str
    model_patch: str = ""
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    error: str | None = None
    tokens_used: int = 0
    trajectory: str = ""  # Markdown trajectory of tool calls


@dataclass
class RunConfig:
    """Configuration for a SWE-bench evaluation run."""

    model: str = "openai:gpt-4.1"
    dataset: str = "princeton-nlp/SWE-bench_Verified"
    split: str = "test"
    instance_ids: list[str] = field(default_factory=list)
    workers: int = 1
    timeout: int = 300
    output_path: str = "predictions.jsonl"
    temperature: float = 0.0
    cost_budget_usd: float | None = None
    model_settings: dict[str, Any] | None = None
    image_template: str | None = None  # Docker image template, None = auto-detect
    trajs_dir: str | None = None  # Directory for trajectory files (None = no saving)
