"""Tests for model-visible MCP resource/skill support (issue #178)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai._run_context import RunContext
from pydantic_ai.messages import BinaryContent
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets import CombinedToolset, FunctionToolset
from pydantic_ai.usage import RunUsage

from pydantic_deep.mcp.resources import (
    SKILL_URI_SCHEME,
    _coerce_text,
    _is_skill_doc_uri,
    _skill_id_from_uri,
    create_mcp_resources_toolset,
)


@dataclass
class _FakeResource:
    uri: str
    name: str = ""
    description: str = ""
    mime_type: str = ""


@dataclass
class _FakeProvider:
    """Stand-in for a connected ``MCPToolset``."""

    resources: list[_FakeResource] = field(default_factory=list)
    contents: dict[str, Any] = field(default_factory=dict)
    reads: list[str] = field(default_factory=list)

    async def list_resources(self) -> list[_FakeResource]:
        return self.resources

    async def read_resource(self, uri: str) -> Any:
        self.reads.append(uri)
        return self.contents.get(uri, "")


@dataclass
class _UnreachableProvider(_FakeProvider):
    """A server that can't be reached — every call raises."""

    async def list_resources(self) -> list[_FakeResource]:
        raise ConnectionError("server down")

    async def read_resource(self, uri: str) -> Any:
        raise ConnectionError("server down")


@dataclass
class _ReadFailsProvider(_FakeProvider):
    """A server that lists fine but drops the connection on read."""

    async def read_resource(self, uri: str) -> Any:
        raise ConnectionError("read failed")


def _ctx() -> RunContext[Any]:
    return RunContext[Any](
        deps=None,
        model=TestModel(),
        usage=RunUsage(),
        retry=0,
        run_step=0,
        tool_name=None,
        tool_call_id=None,
    )


async def _call(toolset: FunctionToolset, name: str, args: dict[str, Any] | None = None) -> Any:
    ctx = _ctx()
    tools = await toolset.get_tools(ctx)
    return await toolset.call_tool(name, args or {}, ctx, tools[name])


class TestHelpers:
    def test_is_skill_doc_uri(self) -> None:
        assert _is_skill_doc_uri("skill://service-mcp/SKILL.md") is True
        assert _is_skill_doc_uri("skill://service-mcp/_manifest") is False
        assert _is_skill_doc_uri("file:///x/SKILL.md") is False

    def test_skill_id_from_uri_netloc(self) -> None:
        assert _skill_id_from_uri("skill://service-mcp/SKILL.md") == "service-mcp"

    def test_skill_id_from_uri_path_only(self) -> None:
        # No netloc → first path segment.
        assert _skill_id_from_uri("skill:///alpha/SKILL.md") == "alpha"

    def test_coerce_text_str(self) -> None:
        assert _coerce_text("hello") == "hello"

    def test_coerce_text_binary(self) -> None:
        out = _coerce_text(BinaryContent(data=b"1234", media_type="image/png"))
        assert "binary content" in out
        assert "image/png" in out

    def test_coerce_text_list_mixed(self) -> None:
        out = _coerce_text(["a", BinaryContent(data=b"x", media_type="text/plain"), "b"])
        assert out.startswith("a\n")
        assert out.endswith("\nb")
        assert "binary content" in out

    def test_coerce_text_other(self) -> None:
        assert _coerce_text(123) == "123"


class TestResourceTools:
    async def test_list_mcp_resources(self) -> None:
        provider = _FakeProvider(
            resources=[
                _FakeResource(
                    uri="skill://svc/SKILL.md",
                    name="svc",
                    description="d",
                    mime_type="text/markdown",
                ),
                _FakeResource(uri="res://svc/data.json", name="data"),
            ]
        )
        toolset = create_mcp_resources_toolset(provider, server_name="svc")
        result = await _call(toolset, "list_mcp_resources")
        assert result == [
            {
                "uri": "skill://svc/SKILL.md",
                "name": "svc",
                "description": "d",
                "mime_type": "text/markdown",
            },
            {"uri": "res://svc/data.json", "name": "data", "description": "", "mime_type": ""},
        ]

    async def test_read_mcp_resource(self) -> None:
        provider = _FakeProvider(contents={"skill://svc/SKILL.md": "# guidance"})
        toolset = create_mcp_resources_toolset(provider, server_name="svc")
        result = await _call(toolset, "read_mcp_resource", {"uri": "skill://svc/SKILL.md"})
        assert result == "# guidance"
        assert provider.reads == ["skill://svc/SKILL.md"]

    async def test_mime_type_camel_case_fallback(self) -> None:
        # A raw MCP SDK resource may expose `mimeType` rather than `mime_type`.
        class _CamelResource:
            uri = "res://svc/x"
            name = "x"
            description = ""
            mimeType = "application/json"

        toolset = create_mcp_resources_toolset(
            _FakeProvider(resources=[_CamelResource()]),
            server_name="svc",
        )
        result = await _call(toolset, "list_mcp_resources")
        assert result[0]["mime_type"] == "application/json"


class TestSkillTools:
    def _provider(self) -> _FakeProvider:
        return _FakeProvider(
            resources=[
                _FakeResource(uri="skill://svc/SKILL.md", description="Service guidance"),
                _FakeResource(uri="skill://svc/_manifest"),
                _FakeResource(uri="skill://other/SKILL.md"),
                _FakeResource(uri="res://svc/data.json"),
            ],
            contents={"skill://svc/SKILL.md": "# svc skill"},
        )

    async def test_list_mcp_skills_filters_skill_docs(self) -> None:
        toolset = create_mcp_resources_toolset(self._provider(), server_name="svc")
        result = await _call(toolset, "list_mcp_skills")
        assert result == [
            {"skill": "svc", "uri": "skill://svc/SKILL.md", "description": "Service guidance"},
            {"skill": "other", "uri": "skill://other/SKILL.md", "description": ""},
        ]

    async def test_load_mcp_skill_by_id(self) -> None:
        toolset = create_mcp_resources_toolset(self._provider(), server_name="svc")
        result = await _call(toolset, "load_mcp_skill", {"skill": "svc"})
        assert result == "# svc skill"

    async def test_load_mcp_skill_by_uri(self) -> None:
        toolset = create_mcp_resources_toolset(self._provider(), server_name="svc")
        result = await _call(toolset, "load_mcp_skill", {"skill": "skill://svc/SKILL.md"})
        assert result == "# svc skill"

    async def test_load_mcp_skill_not_found(self) -> None:
        toolset = create_mcp_resources_toolset(self._provider(), server_name="svc")
        result = await _call(toolset, "load_mcp_skill", {"skill": "missing"})
        assert "not found" in result
        assert "other" in result and "svc" in result

    async def test_load_mcp_skill_not_found_none_available(self) -> None:
        toolset = create_mcp_resources_toolset(_FakeProvider(), server_name="svc")
        result = await _call(toolset, "load_mcp_skill", {"skill": "x"})
        assert "Available: none" in result


class TestUnreachableServer:
    """A server that is down must degrade to an error string, never abort the run.

    ``make_resilient`` only guards listing a toolset's tools, so an exception raised
    inside one of these tools would propagate straight out of ``agent.run()``.
    """

    async def test_list_mcp_resources_reports_error(self) -> None:
        toolset = create_mcp_resources_toolset(_UnreachableProvider(), server_name="svc")
        result = await _call(toolset, "list_mcp_resources")
        assert result == "Error: could not list resources on MCP server 'svc': server down"

    async def test_read_mcp_resource_reports_error(self) -> None:
        toolset = create_mcp_resources_toolset(_UnreachableProvider(), server_name="svc")
        result = await _call(toolset, "read_mcp_resource", {"uri": "res://svc/x"})
        assert result == "Error: could not read 'res://svc/x' from MCP server 'svc': server down"

    async def test_list_mcp_skills_reports_error(self) -> None:
        toolset = create_mcp_resources_toolset(_UnreachableProvider(), server_name="svc")
        result = await _call(toolset, "list_mcp_skills")
        assert "could not list resources" in result

    async def test_load_mcp_skill_reports_list_error(self) -> None:
        toolset = create_mcp_resources_toolset(_UnreachableProvider(), server_name="svc")
        result = await _call(toolset, "load_mcp_skill", {"skill": "svc"})
        assert "could not list resources" in result

    async def test_load_mcp_skill_reports_read_error(self) -> None:
        provider = _ReadFailsProvider(resources=[_FakeResource(uri="skill://svc/SKILL.md")])
        toolset = create_mcp_resources_toolset(provider, server_name="svc")
        result = await _call(toolset, "load_mcp_skill", {"skill": "svc"})
        assert "could not read 'skill://svc/SKILL.md'" in result


class TestSkillsInstructions:
    """The skills must be announced up front, not only via a tool description."""

    async def test_announces_skills_with_descriptions(self) -> None:
        provider = _FakeProvider(
            resources=[
                _FakeResource(uri="skill://svc/SKILL.md", description="Service guidance"),
                _FakeResource(uri="skill://other/SKILL.md"),
                _FakeResource(uri="res://svc/data.json"),
            ]
        )
        toolset = create_mcp_resources_toolset(provider, server_name="svc")
        parts = await toolset.get_instructions(_ctx())
        assert parts is not None
        content = parts[0].content
        assert "`svc` MCP server publishes skills" in content
        assert "- `svc` — Service guidance" in content
        assert "- `other`\n" in content
        assert "data.json" not in content
        assert "`load_mcp_skill`" in content

    async def test_prefixed_instructions_name_the_prefixed_tool(self) -> None:
        provider = _FakeProvider(resources=[_FakeResource(uri="skill://svc/SKILL.md")])
        toolset = create_mcp_resources_toolset(provider, server_name="svc", tool_prefix="svc")
        parts = await toolset.get_instructions(_ctx())
        assert parts is not None
        assert "`svc_load_mcp_skill`" in parts[0].content

    async def test_no_skills_leaves_prompt_untouched(self) -> None:
        toolset = create_mcp_resources_toolset(
            _FakeProvider(resources=[_FakeResource(uri="res://svc/data.json")]),
            server_name="svc",
        )
        assert await toolset.get_instructions(_ctx()) is None

    async def test_unreachable_server_leaves_prompt_untouched(self) -> None:
        toolset = create_mcp_resources_toolset(_UnreachableProvider(), server_name="svc")
        assert await toolset.get_instructions(_ctx()) is None

    async def test_include_skills_false_announces_nothing(self) -> None:
        provider = _FakeProvider(resources=[_FakeResource(uri="skill://svc/SKILL.md")])
        toolset = create_mcp_resources_toolset(provider, server_name="svc", include_skills=False)
        assert await toolset.get_instructions(_ctx()) is None


class TestToolPrefix:
    async def test_prefix_renames_every_tool(self) -> None:
        toolset = create_mcp_resources_toolset(
            _FakeProvider(), server_name="svc", tool_prefix="svc"
        )
        tools = await toolset.get_tools(_ctx())
        assert set(tools) == {
            "svc_list_mcp_resources",
            "svc_read_mcp_resource",
            "svc_list_mcp_skills",
            "svc_load_mcp_skill",
        }

    async def test_descriptions_reference_the_prefixed_names(self) -> None:
        toolset = create_mcp_resources_toolset(
            _FakeProvider(), server_name="svc", tool_prefix="svc"
        )
        tools = await toolset.get_tools(_ctx())
        assert "`svc_read_mcp_resource`" in (
            tools["svc_list_mcp_resources"].tool_def.description or ""
        )
        assert "`svc_load_mcp_skill`" in (tools["svc_list_mcp_skills"].tool_def.description or "")

    async def test_prefixed_tools_still_call_through(self) -> None:
        provider = _FakeProvider(contents={"res://svc/x": "body"})
        toolset = create_mcp_resources_toolset(provider, server_name="svc", tool_prefix="svc")
        result = await _call(toolset, "svc_read_mcp_resource", {"uri": "res://svc/x"})
        assert result == "body"

    async def test_two_servers_do_not_collide(self) -> None:
        # Without a per-server prefix `CombinedToolset` raises `UserError` on the
        # duplicate tool names and the whole agent run fails.
        combined = CombinedToolset(
            [
                create_mcp_resources_toolset(
                    _FakeProvider(), server_name="alpha", tool_prefix="alpha"
                ),
                create_mcp_resources_toolset(
                    _FakeProvider(), server_name="beta", tool_prefix="beta"
                ),
            ]
        )
        tools = await combined.get_tools(_ctx())
        assert "alpha_list_mcp_resources" in tools
        assert "beta_list_mcp_resources" in tools


class TestToolRegistration:
    async def test_include_skills_false_omits_skill_tools(self) -> None:
        toolset = create_mcp_resources_toolset(
            _FakeProvider(), server_name="svc", include_skills=False
        )
        tools = await toolset.get_tools(_ctx())
        assert set(tools) == {"list_mcp_resources", "read_mcp_resource"}

    async def test_include_skills_true_adds_skill_tools(self) -> None:
        toolset = create_mcp_resources_toolset(_FakeProvider(), server_name="svc")
        tools = await toolset.get_tools(_ctx())
        assert set(tools) == {
            "list_mcp_resources",
            "read_mcp_resource",
            "list_mcp_skills",
            "load_mcp_skill",
        }

    def test_default_id(self) -> None:
        toolset = create_mcp_resources_toolset(_FakeProvider(), server_name="svc")
        assert toolset.id == "mcp-resources-svc"

    def test_explicit_id(self) -> None:
        toolset = create_mcp_resources_toolset(_FakeProvider(), server_name="svc", id="custom")
        assert toolset.id == "custom"

    def test_scheme_constant(self) -> None:
        assert SKILL_URI_SCHEME == "skill"


class TestConfigFlags:
    def test_defaults_false(self) -> None:
        from pydantic_deep.mcp import MCPServerConfig

        cfg = MCPServerConfig(name="x", transport="http", url="http://x/mcp")
        assert cfg.include_resources is False
        assert cfg.include_skills is False

    def test_roundtrip(self) -> None:
        from pydantic_deep.mcp import MCPServerConfig

        cfg = MCPServerConfig(
            name="svc",
            transport="http",
            url="http://x/mcp",
            include_resources=True,
            include_skills=True,
        )
        assert MCPServerConfig.from_dict(cfg.to_dict()) == cfg

    def test_loader_reads_flags_http(self) -> None:
        from pydantic_deep.mcp import parse_mcp_servers

        configs = parse_mcp_servers(
            {"svc": {"type": "http", "url": "http://x/mcp", "include_skills": True}}
        )
        assert configs[0].include_skills is True
        assert configs[0].include_resources is False

    def test_loader_reads_flags_stdio(self) -> None:
        from pydantic_deep.mcp import parse_mcp_servers

        configs = parse_mcp_servers({"svc": {"command": "run", "include_resources": True}})
        assert configs[0].include_resources is True


class TestBuildActiveWiring:
    def test_plain_server_yields_one_toolset(self) -> None:
        from pydantic_deep.mcp import MCPRegistry, MCPServerConfig

        reg = MCPRegistry(resolver=lambda _k: None)
        reg.add(MCPServerConfig(name="x", transport="http", url="http://x/mcp"))
        assert len(reg.build_active()) == 1

    def test_skills_server_adds_resources_toolset(self) -> None:
        from pydantic_deep.mcp import MCPRegistry, MCPServerConfig

        reg = MCPRegistry(resolver=lambda _k: None)
        reg.add(
            MCPServerConfig(name="svc", transport="http", url="http://x/mcp", include_skills=True)
        )
        active = reg.build_active()
        assert len(active) == 2
        # The second toolset is the resources bridge bound to the same server.
        assert active[1].wrapped.id == "mcp-resources-svc"  # type: ignore[attr-defined]

    async def test_resources_only_flag_omits_the_skill_tools(self) -> None:
        from pydantic_deep.mcp import MCPRegistry, MCPServerConfig

        reg = MCPRegistry(resolver=lambda _k: None)
        reg.add(
            MCPServerConfig(
                name="svc", transport="http", url="http://x/mcp", include_resources=True
            )
        )
        active = reg.build_active()
        assert len(active) == 2
        tools = await active[1].get_tools(_ctx())
        assert set(tools) == {"svc_list_mcp_resources", "svc_read_mcp_resource"}

    async def test_tools_are_prefixed_with_the_server_name(self) -> None:
        from pydantic_deep.mcp import MCPRegistry, MCPServerConfig

        reg = MCPRegistry(resolver=lambda _k: None)
        # A name that isn't a legal tool-name fragment is sanitised, not passed through.
        reg.add(
            MCPServerConfig(
                name="svc one.2", transport="http", url="http://x/mcp", include_skills=True
            )
        )
        tools = await reg.build_active()[1].get_tools(_ctx())
        assert "svc_one_2_load_mcp_skill" in tools

    async def test_explicit_tool_prefix_wins(self) -> None:
        from pydantic_deep.mcp import MCPRegistry, MCPServerConfig

        reg = MCPRegistry(resolver=lambda _k: None)
        reg.add(
            MCPServerConfig(
                name="svc",
                transport="http",
                url="http://x/mcp",
                tool_prefix="s",
                include_skills=True,
            )
        )
        tools = await reg.build_active()[1].get_tools(_ctx())
        assert "s_load_mcp_skill" in tools

    async def test_two_resource_servers_can_be_active_together(self) -> None:
        from pydantic_deep.mcp import MCPRegistry, MCPServerConfig

        reg = MCPRegistry(resolver=lambda _k: None)
        for name in ("alpha", "beta"):
            reg.add(
                MCPServerConfig(
                    name=name, transport="http", url=f"http://{name}/mcp", include_skills=True
                )
            )
        active = reg.build_active()
        assert len(active) == 4
        resource_tools = await CombinedToolset([active[1], active[3]]).get_tools(_ctx())
        assert "alpha_load_mcp_skill" in resource_tools
        assert "beta_load_mcp_skill" in resource_tools
