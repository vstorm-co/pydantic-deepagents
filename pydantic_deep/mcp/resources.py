"""Expose an MCP server's resources — and ``skill://`` resources in particular — to the model.

An MCP server can publish *resources* (docs, templates, FastMCP skills) next to its
tools, but pydantic-ai only surfaces the tools to the model. A server that correctly
advertises ``skill://.../SKILL.md`` via FastMCP's ``SkillsDirectoryProvider`` is
therefore invisible to a delegated agent unless the application reimplements a bridge
by hand (see issue #178).

:func:`create_mcp_resources_toolset` closes that gap: given anything that can
``list_resources()`` / ``read_resource(uri)`` (pydantic-ai's ``MCPToolset`` does), it
returns a small ``FunctionToolset`` exposing model-visible tools to discover and read
those resources, with first-class handling for ``SKILL.md`` skill resources.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable
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


@runtime_checkable
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


def _coerce_text(content: Any) -> str:
    """Flatten ``read_resource``'s ``str | BinaryContent | list[...]`` into text.

    Binary parts can't be inlined, so they're rendered as a short placeholder note
    rather than dropped silently.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, BinaryContent):
        return f"[binary content: {content.media_type}, {len(content.data)} bytes]"
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


LIST_RESOURCES_DESCRIPTION = """\
List the resources published by this MCP server (docs, templates, skills).

Resources are read-only data the server exposes alongside its tools. Returns each \
resource's uri, name, description and mime type. Read one with `read_mcp_resource`."""

READ_RESOURCE_DESCRIPTION = """\
Read the contents of an MCP resource by its exact uri (from `list_mcp_resources`).

Returns the resource text. Binary resources are summarised as a short placeholder."""

LIST_SKILLS_DESCRIPTION = """\
List the skills this MCP server publishes as `skill://.../SKILL.md` resources.

Skills carry operational guidance and tool-usage patterns for the server. Load one \
with `load_mcp_skill` before using the server's operational tools."""

LOAD_SKILL_DESCRIPTION = """\
Load an MCP server skill's `SKILL.md` guidance by skill id or full uri.

Read the returned guidance before using the server's operational tools — it explains \
how the server expects them to be used."""


def create_mcp_resources_toolset(
    provider: MCPResourceProvider,
    *,
    server_name: str,
    id: str | None = None,
    include_skills: bool = True,
) -> FunctionToolset:
    """Build a toolset that exposes an MCP server's resources to the model.

    Args:
        provider: The connected MCP server (anything with ``list_resources`` /
            ``read_resource``). ``MCPToolset`` manages its own connection, so the
            tools work whether or not the toolset is currently entered.
        server_name: Server identifier, used in the toolset id and skill error text.
        id: Explicit toolset id (defaults to ``mcp-resources-<server_name>``).
        include_skills: Also register `list_mcp_skills` / `load_mcp_skill` for
            ``skill://`` resources.

    Returns:
        A ``FunctionToolset`` with `list_mcp_resources`, `read_mcp_resource`, and
        (when ``include_skills``) the two skill tools.
    """
    toolset = FunctionToolset(id=id or f"mcp-resources-{server_name}")

    @toolset.tool(description=LIST_RESOURCES_DESCRIPTION)
    async def list_mcp_resources(  # pyright: ignore[reportUnusedFunction]
        _ctx: RunContext[Any],
    ) -> list[dict[str, str]]:
        return [_resource_summary(r) for r in await provider.list_resources()]

    @toolset.tool(description=READ_RESOURCE_DESCRIPTION)
    async def read_mcp_resource(  # pyright: ignore[reportUnusedFunction]
        _ctx: RunContext[Any],
        uri: str,
    ) -> str:
        return _coerce_text(await provider.read_resource(uri))

    if include_skills:

        @toolset.tool(description=LIST_SKILLS_DESCRIPTION)
        async def list_mcp_skills(  # pyright: ignore[reportUnusedFunction]
            _ctx: RunContext[Any],
        ) -> list[dict[str, str]]:
            skills: list[dict[str, str]] = []
            for resource in await provider.list_resources():
                uri = _uri_str(resource)
                if _is_skill_doc_uri(uri):
                    skills.append(
                        {
                            "skill": _skill_id_from_uri(uri),
                            "uri": uri,
                            "description": getattr(resource, "description", "") or "",
                        }
                    )
            return skills

        @toolset.tool(description=LOAD_SKILL_DESCRIPTION)
        async def load_mcp_skill(  # pyright: ignore[reportUnusedFunction]
            _ctx: RunContext[Any],
            skill: str,
        ) -> str:
            resources = await provider.list_resources()
            skill_uris = [_uri_str(r) for r in resources if _is_skill_doc_uri(_uri_str(r))]
            target = next(
                (u for u in skill_uris if skill in (u, _skill_id_from_uri(u))),
                None,
            )
            if target is None:
                available = ", ".join(sorted(_skill_id_from_uri(u) for u in skill_uris)) or "none"
                return (
                    f"Error: MCP skill {skill!r} not found on server {server_name!r}. "
                    f"Available: {available}"
                )
            return _coerce_text(await provider.read_resource(target))

    return toolset
