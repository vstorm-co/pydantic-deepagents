"""Expose an MCP server's resources — and ``skill://`` resources in particular — to the model.

An MCP server can publish *resources* (docs, templates, FastMCP skills) next to its
tools, but pydantic-ai only surfaces the tools to the model. A server that correctly
advertises ``skill://.../SKILL.md`` via FastMCP's ``SkillsDirectoryProvider`` is
therefore invisible to a delegated agent unless the application reimplements a bridge
by hand (see issue #178).

:func:`create_mcp_resources_toolset` closes that gap: given anything that can
``list_resources()`` / ``read_resource(uri)`` (pydantic-ai's ``MCPToolset`` does), it
returns a small ``FunctionToolset`` exposing model-visible tools to discover and read
those resources, with first-class handling for ``SKILL.md`` skill resources. When the
server publishes skills, the toolset also announces them in the system prompt, so the
model knows the guidance exists before it reaches for the server's operational tools.
"""

from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import urlsplit

from pydantic_ai._run_context import RunContext
from pydantic_ai.messages import BinaryContent
from pydantic_ai.toolsets import FunctionToolset

__all__ = [
    "MCPResourceProvider",
    "SKILL_URI_SCHEME",
    "SKILL_DOC_NAME",
    "create_mcp_resources_toolset",
]

#: URI scheme FastMCP uses for skill resources, e.g. ``skill://service-mcp/SKILL.md``.
SKILL_URI_SCHEME = "skill"

#: Filename that marks a skill's entry document within a ``skill://`` resource.
SKILL_DOC_NAME = "SKILL.md"

LIST_RESOURCES_TOOL = "list_mcp_resources"
READ_RESOURCE_TOOL = "read_mcp_resource"
LIST_SKILLS_TOOL = "list_mcp_skills"
LOAD_SKILL_TOOL = "load_mcp_skill"


class MCPResourceProvider(Protocol):
    """The slice of ``MCPToolset`` this toolset needs — list and read resources."""

    async def list_resources(self) -> list[Any]: ...

    async def read_resource(self, uri: str) -> Any: ...


def _uri_str(resource: Any) -> str:
    uri = getattr(resource, "uri", None)
    return str(uri) if uri is not None else ""


def _is_skill_doc_uri(uri: str) -> bool:
    parts = urlsplit(uri)
    return parts.scheme == SKILL_URI_SCHEME and parts.path.rsplit("/", 1)[-1] == SKILL_DOC_NAME


def _skill_id_from_uri(uri: str) -> str:
    """``skill://service-mcp/SKILL.md`` → ``service-mcp``."""
    parts = urlsplit(uri)
    return parts.netloc or parts.path.strip("/").split("/", 1)[0]


def _prefixed(name: str, tool_prefix: str | None) -> str:
    return f"{tool_prefix}_{name}" if tool_prefix else name


def _coerce_text(content: Any) -> str:
    """Flatten ``read_resource``'s ``str | BinaryContent | list[...]`` into text.

    Binary parts can't be inlined, so they're rendered as a short placeholder note
    rather than dropped silently.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, BinaryContent):
        # BinaryContent's fields are invisible to pyright but present at runtime
        # (upstream type-info gap); mypy's pydantic plugin sees them.
        media_type = content.media_type  # type: ignore[attr-defined, unused-ignore]
        size = len(content.data)  # type: ignore[attr-defined, unused-ignore]
        return f"[binary content: {media_type}, {size} bytes]"
    if isinstance(content, list):
        return "\n".join(_coerce_text(part) for part in content)
    return str(content)


def _resource_summary(resource: Any) -> dict[str, str]:
    return {
        "uri": _uri_str(resource),
        "name": getattr(resource, "name", "") or "",
        "description": getattr(resource, "description", "") or "",
        "mime_type": getattr(resource, "mime_type", None)
        or getattr(resource, "mimeType", "")
        or "",
    }


def _skill_summary(resource: Any) -> dict[str, str]:
    uri = _uri_str(resource)
    return {
        "skill": _skill_id_from_uri(uri),
        "uri": uri,
        "description": getattr(resource, "description", "") or "",
    }


LIST_RESOURCES_DESCRIPTION = """\
List the resources published by the `{server}` MCP server (docs, templates, skills).

Resources are read-only data the server exposes alongside its tools. Returns each \
resource's uri, name, description and mime type. Read one with `{read_resource}`."""

READ_RESOURCE_DESCRIPTION = """\
Read a resource on the `{server}` MCP server by its exact uri (from `{list_resources}`).

Returns the resource text. Binary resources are summarised as a short placeholder."""

LIST_SKILLS_DESCRIPTION = """\
List the skills the `{server}` MCP server publishes as `skill://.../SKILL.md` resources.

Skills carry operational guidance and tool-usage patterns for the server. Load one \
with `{load_skill}` before using the server's operational tools."""

LOAD_SKILL_DESCRIPTION = """\
Load a skill's `SKILL.md` guidance from the `{server}` MCP server, by skill id or uri.

Read the returned guidance before using the server's operational tools — it explains \
how the server expects them to be used."""

SKILLS_INSTRUCTIONS = """\
The `{server}` MCP server publishes skills carrying operational guidance for its tools:

{skills}

Load the relevant one with `{load_skill}` before using that server's tools."""


# An unreachable server must not abort the run: `make_resilient` guards listing a
# toolset's tools, not calling them, so failures below are handed back to the model
# as text instead of propagating out of `agent.run()`.
async def _list_resources(
    provider: MCPResourceProvider, server_name: str
) -> tuple[list[Any], str | None]:
    try:
        return list(await provider.list_resources()), None
    except Exception as exc:
        return [], f"Error: could not list resources on MCP server {server_name!r}: {exc}"


async def _read_resource(provider: MCPResourceProvider, server_name: str, uri: str) -> str:
    try:
        return _coerce_text(await provider.read_resource(uri))
    except Exception as exc:
        return f"Error: could not read {uri!r} from MCP server {server_name!r}: {exc}"


async def _list_skills(
    provider: MCPResourceProvider, server_name: str
) -> tuple[list[dict[str, str]], str | None]:
    resources, error = await _list_resources(provider, server_name)
    if error is not None:
        return [], error
    return [_skill_summary(r) for r in resources if _is_skill_doc_uri(_uri_str(r))], None


def _register_skill_tools(
    toolset: FunctionToolset[Any],
    provider: MCPResourceProvider,
    server_name: str,
    *,
    list_skills_tool: str,
    load_skill_tool: str,
) -> None:
    """Register the `skill://` tools and announce the server's skills up front."""

    @toolset.tool(
        name=list_skills_tool,
        description=LIST_SKILLS_DESCRIPTION.format(server=server_name, load_skill=load_skill_tool),
    )
    async def list_mcp_skills(  # pyright: ignore[reportUnusedFunction]
        _ctx: RunContext[Any],
    ) -> list[dict[str, str]] | str:
        skills, error = await _list_skills(provider, server_name)
        return error if error is not None else skills

    @toolset.tool(
        name=load_skill_tool,
        description=LOAD_SKILL_DESCRIPTION.format(server=server_name),
    )
    async def load_mcp_skill(  # pyright: ignore[reportUnusedFunction]
        _ctx: RunContext[Any],
        skill: str,
    ) -> str:
        skills, error = await _list_skills(provider, server_name)
        if error is not None:
            return error
        target = next((s["uri"] for s in skills if skill in (s["uri"], s["skill"])), None)
        if target is None:
            available = ", ".join(sorted(s["skill"] for s in skills)) or "none"
            return (
                f"Error: MCP skill {skill!r} not found on server {server_name!r}. "
                f"Available: {available}"
            )
        return await _read_resource(provider, server_name, target)

    @toolset.instructions
    async def skills_instructions(  # pyright: ignore[reportUnusedFunction]
        _ctx: RunContext[Any],
    ) -> str:
        """Announce the server's skills so the model knows they exist up front.

        Issue #178 asks for the guidance to reach the model *before* it starts using
        the server's operational tools; a tool description alone only helps if the
        model happens to go looking. An empty string leaves the system prompt
        untouched, which is what we want when the server publishes no skills or
        can't be reached.
        """
        skills, error = await _list_skills(provider, server_name)
        if error is not None or not skills:
            return ""
        listing = "\n".join(
            f"- `{s['skill']}`" + (f" \u2014 {s['description']}" if s["description"] else "")
            for s in skills
        )
        return SKILLS_INSTRUCTIONS.format(
            server=server_name, skills=listing, load_skill=load_skill_tool
        )


def create_mcp_resources_toolset(
    provider: MCPResourceProvider,
    *,
    server_name: str,
    id: str | None = None,
    include_skills: bool = True,
    tool_prefix: str | None = None,
) -> FunctionToolset[Any]:
    """Build a toolset that exposes an MCP server's resources to the model.

    Args:
        provider: The connected MCP server (anything with ``list_resources`` /
            ``read_resource``). ``MCPToolset`` manages its own connection, so the
            tools work whether or not the toolset is currently entered.
        server_name: Server identifier, used in the toolset id, the tool descriptions
            and the skill error text.
        id: Explicit toolset id (defaults to ``mcp-resources-<server_name>``).
        include_skills: Also register `list_mcp_skills` / `load_mcp_skill` for
            ``skill://`` resources, and announce the server's skills in the system
            prompt so the model knows they exist before using the server's tools.
        tool_prefix: Prepended to every tool name as ``<prefix>_<name>``. Needed when
            more than one server exposes its resources — the tool names are otherwise
            identical and pydantic-ai rejects the collision, failing the whole run.
            :meth:`MCPRegistry.build_active` always passes one.

    Returns:
        A ``FunctionToolset`` with `list_mcp_resources`, `read_mcp_resource`, and
        (when ``include_skills``) the two skill tools.
    """
    list_resources_tool = _prefixed(LIST_RESOURCES_TOOL, tool_prefix)
    read_resource_tool = _prefixed(READ_RESOURCE_TOOL, tool_prefix)

    toolset = FunctionToolset[Any](id=id or f"mcp-resources-{server_name}")

    @toolset.tool(
        name=list_resources_tool,
        description=LIST_RESOURCES_DESCRIPTION.format(
            server=server_name, read_resource=read_resource_tool
        ),
    )
    async def list_mcp_resources(  # pyright: ignore[reportUnusedFunction]
        _ctx: RunContext[Any],
    ) -> list[dict[str, str]] | str:
        resources, error = await _list_resources(provider, server_name)
        if error is not None:
            return error
        return [_resource_summary(r) for r in resources]

    @toolset.tool(
        name=read_resource_tool,
        description=READ_RESOURCE_DESCRIPTION.format(
            server=server_name, list_resources=list_resources_tool
        ),
    )
    async def read_mcp_resource(  # pyright: ignore[reportUnusedFunction]
        _ctx: RunContext[Any],
        uri: str,
    ) -> str:
        return await _read_resource(provider, server_name, uri)

    if include_skills:
        _register_skill_tools(
            toolset,
            provider,
            server_name,
            list_skills_tool=_prefixed(LIST_SKILLS_TOOL, tool_prefix),
            load_skill_tool=_prefixed(LOAD_SKILL_TOOL, tool_prefix),
        )

    return toolset
