"""Declarative agent specification for YAML/JSON configuration.

Allows defining deep agents via YAML or JSON files instead of Python code.
The spec mirrors `create_deep_agent()` parameters 1:1.

Example:
    ```python
    from pydantic_deep import DeepAgent

    # Load from YAML
    agent, deps = DeepAgent.from_file("agent.yaml")

    # Load from dict
    agent, deps = DeepAgent.from_spec({
        "model": "anthropic:claude-opus-4-6",
        "include_todo": True,
        "include_memory": True,
    })

    # Save spec to file
    DeepAgent.to_file("agent.yaml", model="anthropic:claude-opus-4-6", include_memory=True)
    ```

YAML format:
    ```yaml
    model: anthropic:claude-opus-4-6
    instructions: You are a helpful coding assistant.
    include_todo: true
    include_filesystem: true
    include_memory: true
    memory_dir: .pydantic-deep
    retries: 3
    model_settings:
      temperature: 0.7
    ```
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic_ai_backends import StateBackend

from pydantic_deep.agent import create_deep_agent
from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.features.checkpointing import CheckpointFrequency


class DeepAgentSpec(BaseModel):
    """Declarative agent specification - mirrors `create_deep_agent()` params.

    All fields have the same defaults as `create_deep_agent()`.
    Only serializable parameters are included (callbacks and Python objects
    like `backend`, `tools`, `toolsets` must be passed as overrides).
    """

    model_config = ConfigDict(extra="forbid")
    model: str | None = None
    fallback_model: str | list[str] | None = None
    instructions: str | None = None
    output_style: str | None = None
    styles_dir: str | list[str] | None = None
    retries: int = 3
    subagents: list[dict[str, Any]] | None = None
    skill_directories: list[str] | None = None
    include_todo: bool = True
    include_filesystem: bool = True
    include_subagents: bool = True
    include_skills: bool = True
    include_builtin_subagents: bool = True
    include_plan: bool = True
    include_execute: bool | None = None
    include_memory: bool = True
    include_checkpoints: bool = False
    include_teams: bool = False
    include_monitoring: bool = True
    include_improve: bool = False
    include_liteparse: bool = False
    stuck_loop_detection: bool = True
    periodic_reminder: bool | None = None
    forking: bool = False
    tool_search: bool = False
    web_search: bool = True
    web_fetch: bool = True
    thinking: bool | str = "high"
    include_history_archive: bool = True
    max_nesting_depth: int = 1
    interrupt_on: dict[str, bool] | None = None
    eviction_token_limit: int | None = 20_000
    max_binary_content: int | None = 3
    patch_tool_calls: bool = True
    edit_format: str = "hashline"
    context_manager: bool = True
    context_manager_max_tokens: int | None = None
    summarization_model: str | None = None
    context_files: list[str] | None = None
    context_discovery: bool = False
    memory_dir: str | None = None
    checkpoint_frequency: CheckpointFrequency = "every_tool"
    max_checkpoints: int = 20
    history_messages_path: str = ".pydantic-deep/messages.json"
    cost_tracking: bool = True
    cost_budget_usd: float | None = None
    plans_dir: str | None = None
    model_settings: dict[str, Any] | None = None
    instrument: bool | None = None


def _load_yaml(text: str) -> dict[str, Any]:
    """Load YAML text, raising ImportError if PyYAML is not installed."""
    try:
        import yaml  # type: ignore[import-untyped,unused-ignore]
    except ImportError as e:  # pragma: no cover
        raise ImportError(  # pragma: no cover
            "PyYAML is required for YAML spec files. "
            "Install with: pip install 'pydantic-deep[yaml]'"
        ) from e
    return yaml.safe_load(text)  # type: ignore[no-any-return]


def _dump_yaml(data: dict[str, Any]) -> str:
    """Dump dict to YAML string."""
    try:
        import yaml
    except ImportError as e:  # pragma: no cover
        raise ImportError(  # pragma: no cover
            "PyYAML is required for YAML spec files. "
            "Install with: pip install 'pydantic-deep[yaml]'"
        ) from e
    return yaml.dump(data, default_flow_style=False, sort_keys=False)


class DeepAgent:
    """Factory for creating deep agents from declarative specs.

    Provides class methods to load agent configurations from YAML/JSON
    files or dicts, and save configurations to files.
    """

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        **overrides: Any,
    ) -> tuple[Any, DeepAgentDeps]:
        """Create an agent from a YAML or JSON spec file.

        Args:
            path: Path to YAML (.yaml/.yml) or JSON (.json) file.
            **overrides: Override spec values (e.g., `model="anthropic:claude-opus-4-6"`).
                Non-serializable params like `backend`, `tools`, `on_cost_update`
                can only be passed here.

        Returns:
            Tuple of (agent, deps) ready for `agent.run()`.

        Example:
            ```python
            agent, deps = DeepAgent.from_file("agent.yaml")
            result = await agent.run("Hello", deps=deps)
            ```
        """
        file_path = Path(path)
        text = file_path.read_text(encoding="utf-8")

        if file_path.suffix in (".yaml", ".yml"):
            data = _load_yaml(text)
        elif file_path.suffix == ".json":
            data = json.loads(text)
        else:
            # Try YAML first, fall back to JSON
            try:
                data = _load_yaml(text)
            except Exception:  # pragma: no cover
                data = json.loads(text)  # pragma: no cover

        if not isinstance(data, dict):
            raise ValueError(
                f"Spec file {path} must contain a mapping at the top level, "
                f"got {type(data).__name__}"
            )

        return cls.from_spec(data, **overrides)

    @classmethod
    def from_spec(
        cls,
        data: dict[str, Any],
        **overrides: Any,
    ) -> tuple[Any, DeepAgentDeps]:
        """Create an agent from a dict specification.

        Args:
            data: Dict with `create_deep_agent()` parameter names as keys.
            **overrides: Override spec values. Takes precedence over data.

        Returns:
            Tuple of (agent, deps) ready for `agent.run()`.

        Example:
            ```python
            agent, deps = DeepAgent.from_spec({
                "model": "anthropic:claude-opus-4-6",
                "include_todo": True,
                "include_memory": True,
            })
            ```
        """
        # Separate non-serializable overrides from spec-compatible ones
        non_spec_keys = {
            "backend",
            "tools",
            "toolsets",
            "hooks",
            "on_context_update",
            "on_before_compress",
            "on_after_compress",
            "on_eviction",
            "on_cost_update",
            "middleware",
            "checkpoint_store",
            "subagent_registry",
            "subagent_extra_toolsets",
            "history_processors",
            "output_type",
        }

        # Also pass through any key not in DeepAgentSpec fields (e.g., model=TestModel())
        spec_fields = set(DeepAgentSpec.model_fields)

        def _partition(
            items: dict[str, Any],
            spec_part: dict[str, Any],
            passthrough_part: dict[str, Any],
        ) -> None:
            for k, v in items.items():
                if k in non_spec_keys or k not in spec_fields:
                    passthrough_part[k] = v
                elif not isinstance(v, (str, int, float, bool, list, dict, type(None))):
                    # Non-serializable value for a spec field (e.g., model=TestModel())
                    passthrough_part[k] = v
                else:
                    spec_part[k] = v

        # Partition both data and overrides so non-spec / non-serializable keys
        # are routed to passthrough regardless of where they were supplied.
        spec_data: dict[str, Any] = {}
        spec_overrides: dict[str, Any] = {}
        passthrough: dict[str, Any] = {}
        _partition(data, spec_data, passthrough)
        _partition(overrides, spec_overrides, passthrough)

        # Merge: data + spec_overrides (overrides win)
        merged = {**spec_data, **spec_overrides}

        # Validate through Pydantic model
        spec = DeepAgentSpec(**merged)

        # Build kwargs for create_deep_agent.
        # Note: this uses exclude_none (not exclude_defaults like to_file). The
        # asymmetry is intentional: to_file produces minimal files containing only
        # non-default values, while from_spec must forward every explicit value.
        # This relies on DeepAgentSpec defaults staying in sync with
        # create_deep_agent defaults (verified by test_spec_defaults_match_factory).
        kwargs = spec.model_dump(exclude_none=True)

        # Add non-serializable params
        kwargs.update(passthrough)

        agent = create_deep_agent(**kwargs)
        deps = DeepAgentDeps(backend=passthrough.get("backend") or _default_backend())

        return agent, deps

    @classmethod
    def to_file(cls, path: str | Path, **params: Any) -> None:
        """Save agent parameters as a YAML or JSON spec file.

        Only serializable parameters are saved. Non-serializable params
        (callbacks, Python objects) are silently excluded.

        Args:
            path: Output path. Extension determines format (.yaml/.yml or .json).
            **params: `create_deep_agent()` parameters to save.

        Example:
            ```python
            DeepAgent.to_file(
                "agent.yaml",
                model="anthropic:claude-opus-4-6",
                include_todo=True,
                include_memory=True,
                memory_dir=".pydantic-deep",
            )
            ```
        """
        # Filter to spec-compatible keys only
        spec = DeepAgentSpec(**{k: v for k, v in params.items() if k in DeepAgentSpec.model_fields})

        data = spec.model_dump(exclude_defaults=True)

        file_path = Path(path)
        content = json.dumps(data, indent=2) if file_path.suffix == ".json" else _dump_yaml(data)

        file_path.write_text(content, encoding="utf-8")


def _default_backend() -> Any:
    """Create default StateBackend for spec-loaded agents."""

    return StateBackend()
