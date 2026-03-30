"""Declarative agent specification for YAML/JSON configuration.

Allows defining deep agents via YAML or JSON files instead of Python code.
The spec mirrors ``create_deep_agent()`` parameters 1:1.

Example:
    ```python
    from pydantic_deep import DeepAgent

    # Load from YAML
    agent, deps = DeepAgent.from_file("agent.yaml")

    # Load from dict
    agent, deps = DeepAgent.from_spec({
        "model": "openai:gpt-4.1",
        "include_todo": True,
        "include_memory": True,
    })

    # Save spec to file
    DeepAgent.to_file("agent.yaml", model="openai:gpt-4.1", include_memory=True)
    ```

YAML format:
    ```yaml
    model: openai:gpt-4.1
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

from pydantic_deep.agent import create_deep_agent
from pydantic_deep.deps import DeepAgentDeps


class DeepAgentSpec(BaseModel):
    """Declarative agent specification — mirrors ``create_deep_agent()`` params.

    All fields have the same defaults as ``create_deep_agent()``.
    Only serializable parameters are included (callbacks and Python objects
    like ``backend``, ``tools``, ``toolsets`` must be passed as overrides).
    """

    model_config = ConfigDict(extra="forbid")

    # Core
    model: str | None = None
    instructions: str | None = None
    output_style: str | None = None
    styles_dir: str | list[str] | None = None
    retries: int = 3

    # Subagents
    subagents: list[dict[str, Any]] | None = None
    skill_directories: list[str] | None = None

    # Include flags
    include_todo: bool = True
    include_filesystem: bool = True
    include_subagents: bool = True
    include_skills: bool = True
    include_general_purpose_subagent: bool = True
    include_plan: bool = True
    include_execute: bool | None = None
    include_memory: bool = False
    include_checkpoints: bool = False
    include_teams: bool = False
    include_web: bool = False
    include_history_archive: bool = True

    # Subagent config
    max_nesting_depth: int = 0

    # Interrupt
    interrupt_on: dict[str, bool] | None = None

    # Processors
    eviction_token_limit: int | None = None
    patch_tool_calls: bool = False

    # Filesystem
    image_support: bool = False
    edit_format: str = "hashline"

    # Context management
    context_manager: bool = True
    context_manager_max_tokens: int | None = None
    summarization_model: str | None = None

    # Context files
    context_files: list[str] | None = None
    context_discovery: bool = False

    # Memory
    memory_dir: str | None = None

    # Checkpointing
    checkpoint_frequency: str = "every_tool"
    max_checkpoints: int = 20

    # History archive
    history_messages_path: str = ".pydantic-deep/messages.json"

    # Cost tracking
    cost_tracking: bool = True
    cost_budget_usd: float | None = None

    # Plans
    plans_dir: str | None = None

    # Model settings
    model_settings: dict[str, Any] | None = None

    # Instrumentation
    instrument: bool | None = None


def _load_yaml(text: str) -> dict[str, Any]:
    """Load YAML text, raising ImportError if PyYAML is not installed."""
    try:
        import yaml  # type: ignore[import-untyped]
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
    return yaml.dump(data, default_flow_style=False, sort_keys=False)  # type: ignore[no-any-return]


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
            **overrides: Override spec values (e.g., ``model="openai:gpt-4.1"``).
                Non-serializable params like ``backend``, ``tools``, ``on_cost_update``
                can only be passed here.

        Returns:
            Tuple of (agent, deps) ready for ``agent.run()``.

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

        return cls.from_spec(data, **overrides)

    @classmethod
    def from_spec(
        cls,
        data: dict[str, Any],
        **overrides: Any,
    ) -> tuple[Any, DeepAgentDeps]:
        """Create an agent from a dict specification.

        Args:
            data: Dict with ``create_deep_agent()`` parameter names as keys.
            **overrides: Override spec values. Takes precedence over data.

        Returns:
            Tuple of (agent, deps) ready for ``agent.run()``.

        Example:
            ```python
            agent, deps = DeepAgent.from_spec({
                "model": "openai:gpt-4.1",
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
            "skills",
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
        spec_overrides: dict[str, Any] = {}
        passthrough: dict[str, Any] = {}
        for k, v in overrides.items():
            if k in non_spec_keys or k not in spec_fields:
                passthrough[k] = v
            elif k in spec_fields and not isinstance(
                v, (str, int, float, bool, list, dict, type(None))
            ):
                # Non-serializable value for a spec field (e.g., model=TestModel())
                passthrough[k] = v
            else:
                spec_overrides[k] = v

        # Merge: data + spec_overrides (overrides win)
        merged = {**data, **spec_overrides}

        # Validate through Pydantic model
        spec = DeepAgentSpec(**merged)

        # Build kwargs for create_deep_agent
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
            **params: ``create_deep_agent()`` parameters to save.

        Example:
            ```python
            DeepAgent.to_file(
                "agent.yaml",
                model="openai:gpt-4.1",
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
    from pydantic_ai_backends import StateBackend

    return StateBackend()
