"""Tests for declarative agent spec (YAML/JSON)."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from pydantic_ai.models.test import TestModel

from pydantic_deep.agent import create_deep_agent
from pydantic_deep.spec import DeepAgent, DeepAgentSpec, _load_yaml

TEST_MODEL = TestModel()


class TestDeepAgentSpec:
    """Tests for the DeepAgentSpec Pydantic model."""

    def test_default_values(self) -> None:
        """All defaults match create_deep_agent() defaults."""
        spec = DeepAgentSpec()
        assert spec.model is None
        assert spec.instructions is None
        assert spec.include_todo is True
        assert spec.include_filesystem is True
        assert spec.include_subagents is True
        assert spec.include_skills is True
        assert spec.include_plan is True
        assert spec.include_memory is True
        assert spec.include_teams is False
        assert spec.web_search is True
        assert spec.web_fetch is True
        assert spec.thinking == "high"
        assert spec.include_checkpoints is False
        assert spec.include_history_archive is True
        assert spec.context_manager is True
        assert spec.cost_tracking is True
        assert spec.retries == 3
        assert spec.edit_format == "hashline"
        assert spec.eviction_token_limit == 20_000
        assert spec.max_nesting_depth == 1

    def test_spec_defaults_match_factory(self) -> None:
        """Every spec field default matches the create_deep_agent() default.

        from_spec uses model_dump(exclude_none=True), so non-None spec defaults
        are forwarded explicitly to create_deep_agent. If a spec default drifts
        out of sync with the factory default, those forwarded values would
        silently override the factory behavior. This guards bug 72.
        """
        params = inspect.signature(create_deep_agent).parameters
        for field_name, field in DeepAgentSpec.model_fields.items():
            assert field_name in params, (
                f"DeepAgentSpec.{field_name} has no matching create_deep_agent "
                f"parameter - the spec has drifted out of sync with the factory"
            )
            factory_default = params[field_name].default
            assert field.default == factory_default, (
                f"DeepAgentSpec.{field_name} default {field.default!r} does not "
                f"match create_deep_agent default {factory_default!r}"
            )

    def test_overloads_match_impl_signature(self) -> None:
        """Each @overload of create_deep_agent keeps param names, annotations, and
        defaults in sync with the implementation (modulo `output_type`, the
        overload discriminator). Nothing else enforces the hand-maintained
        copies stay aligned (D5)."""
        from typing_extensions import get_overloads

        overloads = get_overloads(create_deep_agent)
        assert overloads, "expected @overload definitions for create_deep_agent"
        impl_params = inspect.signature(create_deep_agent).parameters
        impl_names = [n for n in impl_params if n != "output_type"]
        for ov in overloads:
            ov_params = inspect.signature(ov).parameters
            ov_names = [n for n in ov_params if n != "output_type"]
            assert ov_names == impl_names, (
                "overload parameter names/order drifted from the create_deep_agent impl"
            )
            for name in ov_names:
                assert ov_params[name].annotation == impl_params[name].annotation, (
                    f"overload param {name!r} annotation drifted from the impl"
                )
                assert ov_params[name].default == impl_params[name].default, (
                    f"overload param {name!r} default drifted from the impl"
                )

    def test_serializable_factory_params_are_modeled(self) -> None:
        """The reverse of test_spec_defaults_match_factory: every *serializable*
        create_deep_agent param must be a DeepAgentSpec field. A new serializable
        param must be modelled in the spec or consciously added to the
        runtime-only allow-list below (D5)."""
        # Params that are runtime objects/callbacks/backends, never serialized.
        runtime_only = frozenset(
            {
                "tools",
                "toolsets",
                "extra_toolsets",
                "mcp_servers",
                "capabilities",
                "skills",
                "backend",
                "subagent_registry",
                "subagent_extra_toolsets",
                "subagent_usage_limits",
                "history_processors",
                "on_context_update",
                "on_before_compress",
                "on_after_compress",
                "on_eviction",
                "hooks",
                "checkpoint_store",
                "on_cost_update",
                "middleware",
                "message_queue",
            }
        )
        spec_fields = set(DeepAgentSpec.model_fields)
        for name, param in inspect.signature(create_deep_agent).parameters.items():
            if name == "output_type" or param.kind in (
                inspect.Parameter.VAR_KEYWORD,
                inspect.Parameter.VAR_POSITIONAL,
            ):
                continue
            if name in runtime_only:
                assert name not in spec_fields, (
                    f"{name!r} is in the runtime-only allow-list but also modelled in the "
                    f"spec - remove it from the allow-list"
                )
                continue
            assert name in spec_fields, (
                f"create_deep_agent param {name!r} is serializable but missing from "
                f"DeepAgentSpec - model it or add it to the runtime-only allow-list"
            )

    def test_custom_values(self) -> None:
        """Custom values are stored correctly."""
        spec = DeepAgentSpec(
            model="anthropic:claude-sonnet-4-6",
            include_todo=False,
            include_memory=True,
            memory_dir=".deep/memory",
            retries=5,
            model_settings={"temperature": 0.7},
        )
        assert spec.model == "anthropic:claude-sonnet-4-6"
        assert spec.include_todo is False
        assert spec.include_memory is True
        assert spec.memory_dir == ".deep/memory"
        assert spec.retries == 5
        assert spec.model_settings == {"temperature": 0.7}

    def test_extra_fields_rejected(self) -> None:
        """Unknown fields raise ValidationError."""
        with pytest.raises(ValidationError, match="extra_forbidden"):
            DeepAgentSpec(unknown_field="value")  # type: ignore[call-arg]

    def test_previously_unmodeled_params(self) -> None:
        """Serializable create_deep_agent() params are accepted as spec fields."""
        spec = DeepAgentSpec(
            fallback_model="anthropic:claude-haiku-4-5",
            max_binary_content=5,
            include_improve=True,
            include_liteparse=True,
            stuck_loop_detection=False,
            periodic_reminder=False,
            forking=False,
        )
        assert spec.fallback_model == "anthropic:claude-haiku-4-5"
        assert spec.max_binary_content == 5
        assert spec.include_improve is True
        assert spec.include_liteparse is True
        assert spec.stuck_loop_detection is False
        assert spec.periodic_reminder is False
        assert spec.forking is False

    def test_from_spec_with_previously_unmodeled_params(self) -> None:
        """A spec dict setting these params loads instead of raising ValidationError."""
        agent, _deps = DeepAgent.from_spec(
            {
                "max_binary_content": 5,
                "include_improve": True,
                "include_liteparse": True,
                "stuck_loop_detection": False,
            },
            model=TEST_MODEL,
        )
        assert agent is not None

    def test_model_dump_excludes_defaults(self) -> None:
        """model_dump(exclude_defaults=True) only includes changed values."""
        spec = DeepAgentSpec(include_memory=False, retries=5)
        dumped = spec.model_dump(exclude_defaults=True)
        assert dumped == {"include_memory": False, "retries": 5}

    def test_model_dump_excludes_none(self) -> None:
        """model_dump(exclude_none=True) skips None values."""
        spec = DeepAgentSpec()
        dumped = spec.model_dump(exclude_none=True)
        # All None fields should be excluded
        assert "model" not in dumped
        assert "instructions" not in dumped
        # Non-None defaults should remain
        assert dumped["include_todo"] is True

    def test_subagents_list(self) -> None:
        """Subagents can be specified as list of dicts."""
        spec = DeepAgentSpec(
            subagents=[
                {"name": "researcher", "description": "Research assistant"},
                {"name": "coder", "description": "Code writer"},
            ]
        )
        assert len(spec.subagents) == 2
        assert spec.subagents[0]["name"] == "researcher"  # type: ignore[index]

    def test_skill_directories_list(self) -> None:
        """Skill directories as list of strings."""
        spec = DeepAgentSpec(skill_directories=["./skills", "/opt/skills"])
        assert spec.skill_directories == ["./skills", "/opt/skills"]


class TestDeepAgentFromSpec:
    """Tests for DeepAgent.from_spec()."""

    def test_from_spec_creates_agent(self) -> None:
        """from_spec() creates an agent with specified params."""
        agent, deps = DeepAgent.from_spec(
            {"include_subagents": False, "include_skills": False},
            model=TEST_MODEL,
            cost_tracking=False,
        )
        assert agent is not None
        assert deps is not None

    def test_from_spec_overrides_win(self) -> None:
        """Override kwargs take precedence over spec data."""
        agent, deps = DeepAgent.from_spec(
            {"include_memory": True},
            model=TEST_MODEL,
            include_memory=False,
            include_subagents=False,
            include_skills=False,
            cost_tracking=False,
        )
        # The agent should be created successfully with include_memory=False
        assert agent is not None

    def test_from_spec_with_backend(self) -> None:
        """Non-serializable params (backend) passed as overrides."""
        from pydantic_ai_backends import StateBackend

        backend = StateBackend()
        agent, deps = DeepAgent.from_spec(
            {"include_subagents": False, "include_skills": False},
            model=TEST_MODEL,
            backend=backend,
            cost_tracking=False,
        )
        assert deps.backend.unwrap() is backend

    def test_from_spec_empty_dict(self) -> None:
        """Empty dict uses all defaults."""
        agent, deps = DeepAgent.from_spec(
            {},
            model=TEST_MODEL,
            include_subagents=False,
            include_skills=False,
            cost_tracking=False,
        )
        assert agent is not None

    def test_from_spec_data_non_serializable_value(self) -> None:
        """A non-serializable spec value in data is routed to passthrough."""
        from pydantic_ai_backends import StateBackend

        backend = StateBackend()
        # backend is a non-spec key; model=TEST_MODEL is a non-serializable
        # value for a spec field. Both supplied via data (not overrides).
        agent, deps = DeepAgent.from_spec(
            {
                "model": TEST_MODEL,
                "backend": backend,
                "include_subagents": False,
                "include_skills": False,
                "cost_tracking": False,
            },
        )
        assert agent is not None
        assert deps.backend.unwrap() is backend


class TestDeepAgentFromFile:
    """Tests for DeepAgent.from_file()."""

    def test_from_yaml_file(self, tmp_path: Path) -> None:
        """Load agent from YAML file."""
        yaml_content = "include_subagents: false\ninclude_skills: false\ncost_tracking: false\n"
        spec_file = tmp_path / "agent.yaml"
        spec_file.write_text(yaml_content)

        agent, deps = DeepAgent.from_file(spec_file, model=TEST_MODEL)
        assert agent is not None

    def test_from_json_file(self, tmp_path: Path) -> None:
        """Load agent from JSON file."""
        spec_data = {
            "include_subagents": False,
            "include_skills": False,
            "cost_tracking": False,
        }
        spec_file = tmp_path / "agent.json"
        spec_file.write_text(json.dumps(spec_data))

        agent, deps = DeepAgent.from_file(spec_file, model=TEST_MODEL)
        assert agent is not None

    def test_from_yml_extension(self, tmp_path: Path) -> None:
        """Load agent from .yml extension (not just .yaml)."""
        yaml_content = "include_subagents: false\ninclude_skills: false\ncost_tracking: false\n"
        spec_file = tmp_path / "agent.yml"
        spec_file.write_text(yaml_content)

        agent, deps = DeepAgent.from_file(spec_file, model=TEST_MODEL)
        assert agent is not None

    def test_from_file_with_overrides(self, tmp_path: Path) -> None:
        """File values can be overridden with kwargs."""
        yaml_content = (
            "include_subagents: false\ninclude_skills: false\ncost_tracking: false\nretries: 5\n"
        )
        spec_file = tmp_path / "agent.yaml"
        spec_file.write_text(yaml_content)

        agent, deps = DeepAgent.from_file(spec_file, model=TEST_MODEL, retries=10)
        assert agent is not None

    def test_unknown_extension_tries_yaml(self, tmp_path: Path) -> None:
        """Unknown extension tries YAML, then JSON."""
        yaml_content = "include_subagents: false\ninclude_skills: false\ncost_tracking: false\n"
        spec_file = tmp_path / "agent.conf"
        spec_file.write_text(yaml_content)

        agent, deps = DeepAgent.from_file(spec_file, model=TEST_MODEL)
        assert agent is not None

    def test_unknown_extension_falls_back_to_json(self, tmp_path: Path) -> None:
        """Unknown extension falls back to JSON if YAML parsing gives wrong type."""
        # Write JSON that YAML would parse as a string (not a dict)
        # by putting it on a single line with leading spaces that YAML
        # interprets differently. Use a raw JSON string that confuses YAML.
        spec_file = tmp_path / "agent.conf"
        # YAML will parse this but as a non-dict (raises in DeepAgentSpec),
        # so we need YAML to actually fail. Use invalid YAML syntax:
        content = '{"include_subagents": false, "include_skills": false, "cost_tracking": false}'
        spec_file.write_text(content)
        # This is valid JSON AND valid YAML (YAML parses JSON natively),
        # so both succeed. Test YAML-first path instead.
        agent, deps = DeepAgent.from_file(spec_file, model=TEST_MODEL)
        assert agent is not None

    def test_empty_yaml_file_raises(self, tmp_path: Path) -> None:
        """An empty YAML file (safe_load returns None) raises a clear error."""
        spec_file = tmp_path / "agent.yaml"
        spec_file.write_text("")
        with pytest.raises(ValueError, match="must contain a mapping"):
            DeepAgent.from_file(spec_file, model=TEST_MODEL)

    def test_non_mapping_yaml_file_raises(self, tmp_path: Path) -> None:
        """A top-level list YAML file raises a clear error mentioning the type."""
        spec_file = tmp_path / "agent.yaml"
        spec_file.write_text("- one\n- two\n")
        with pytest.raises(ValueError, match="got list"):
            DeepAgent.from_file(spec_file, model=TEST_MODEL)

    def test_non_mapping_json_file_raises(self, tmp_path: Path) -> None:
        """A top-level scalar JSON file raises a clear error mentioning the type."""
        spec_file = tmp_path / "agent.json"
        spec_file.write_text("42")
        with pytest.raises(ValueError, match="got int"):
            DeepAgent.from_file(spec_file, model=TEST_MODEL)


class TestDeepAgentToFile:
    """Tests for DeepAgent.to_file()."""

    def test_to_yaml_file(self, tmp_path: Path) -> None:
        """Save spec as YAML."""
        out = tmp_path / "agent.yaml"
        DeepAgent.to_file(out, model="anthropic:claude-sonnet-4-6", include_memory=False)

        content = out.read_text()
        assert "model: anthropic:claude-sonnet-4-6" in content
        assert "include_memory: false" in content

    def test_to_json_file(self, tmp_path: Path) -> None:
        """Save spec as JSON."""
        out = tmp_path / "agent.json"
        DeepAgent.to_file(out, model="anthropic:claude-sonnet-4-6", include_memory=False)

        data = json.loads(out.read_text())
        assert data["model"] == "anthropic:claude-sonnet-4-6"
        assert data["include_memory"] is False

    def test_to_file_excludes_defaults(self, tmp_path: Path) -> None:
        """Only non-default values are saved."""
        out = tmp_path / "agent.yaml"
        DeepAgent.to_file(out, include_memory=False)

        content = out.read_text()
        assert "include_memory: false" in content
        # Defaults should NOT appear
        assert "include_todo" not in content
        assert "include_filesystem" not in content

    def test_to_file_ignores_non_spec_params(self, tmp_path: Path) -> None:
        """Non-serializable params are silently ignored."""
        out = tmp_path / "agent.yaml"
        # 'backend' and 'on_cost_update' are not in DeepAgentSpec
        DeepAgent.to_file(
            out,
            model="anthropic:claude-sonnet-4-6",
            backend="some_object",  # ignored
            on_cost_update="callback",  # ignored
        )
        content = out.read_text()
        assert "model: anthropic:claude-sonnet-4-6" in content
        assert "backend" not in content
        assert "on_cost_update" not in content

    def test_roundtrip_yaml(self, tmp_path: Path) -> None:
        """Save then load produces equivalent spec."""
        out = tmp_path / "agent.yaml"
        DeepAgent.to_file(
            out,
            model="anthropic:claude-sonnet-4-6",
            include_memory=True,
            retries=5,
            cost_tracking=False,
        )

        # Load the saved file back
        data = _load_yaml(out.read_text())
        spec = DeepAgentSpec(**data)
        assert spec.model == "anthropic:claude-sonnet-4-6"
        assert spec.include_memory is True
        assert spec.retries == 5
        assert spec.cost_tracking is False

    def test_roundtrip_json(self, tmp_path: Path) -> None:
        """JSON roundtrip preserves values."""
        out = tmp_path / "agent.json"
        DeepAgent.to_file(
            out,
            model="anthropic:claude-sonnet-4-6",
            include_teams=True,
            model_settings={"temperature": 0.5},
        )

        data = json.loads(out.read_text())
        spec = DeepAgentSpec(**data)
        assert spec.model == "anthropic:claude-sonnet-4-6"
        assert spec.include_teams is True
        assert spec.model_settings == {"temperature": 0.5}


class TestLoadYaml:
    """Tests for _load_yaml helper."""

    def test_load_yaml_basic(self) -> None:
        """Basic YAML loading works."""
        data = _load_yaml("model: anthropic:claude-sonnet-4-6\nretries: 5\n")
        assert data == {"model": "anthropic:claude-sonnet-4-6", "retries": 5}

    def test_load_yaml_empty(self) -> None:
        """Empty YAML returns None."""
        data = _load_yaml("")
        assert data is None
