"""DeepResearch configuration — MCP servers, model, paths."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from fastmcp.client.transports import StdioTransport
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.toolsets import PrefixedToolset

logger = logging.getLogger(__name__)


APP_DIR = Path(__file__).resolve().parent.parent.parent  # deepresearch/
SKILLS_DIR = APP_DIR / "skills"
WORKSPACE_DIR = APP_DIR / "workspace"
WORKSPACES_DIR = APP_DIR / "workspaces"
STATIC_DIR = APP_DIR / "static"


MODEL_NAME: str = os.getenv("MODEL_NAME", "anthropic:claude-sonnet-4-6")


EXCALIDRAW_CANVAS_URL: str = os.getenv("EXCALIDRAW_CANVAS_URL", "http://localhost:3000")


def _docker_available() -> bool:
    """Check if Docker daemon is running."""
    if not shutil.which("docker"):
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _stdio(
    name: str, command: str, args: list[str], env: dict[str, str] | None = None
) -> PrefixedToolset[object]:
    transport = StdioTransport(command, args, env=env)
    return PrefixedToolset(MCPToolset(transport, id=name, max_retries=3), name)


def _http(name: str, url: str, headers: dict[str, str]) -> PrefixedToolset[object]:
    return PrefixedToolset(MCPToolset(url, headers=headers, id=name, max_retries=3), name)


def create_mcp_servers() -> list[PrefixedToolset[object]]:
    """Create MCP server toolsets based on available API keys.

    Returns a list of MCP servers that can be passed as toolsets to the agent.
    Servers are started/stopped automatically by pydantic-ai when the agent
    enters/exits its async context manager.
    """
    servers: list[PrefixedToolset[object]] = []

    # Tavily — AI-optimized web search (requires TAVILY_API_KEY)
    tavily_key = os.getenv("TAVILY_API_KEY")
    if tavily_key:
        servers.append(
            _stdio(
                "tavily",
                "npx",
                ["-y", "tavily-mcp@latest"],
                env={"TAVILY_API_KEY": tavily_key},
            )
        )

    # Brave Search — web search (requires BRAVE_API_KEY)
    brave_key = os.getenv("BRAVE_API_KEY")
    if brave_key:
        servers.append(
            _stdio(
                "brave",
                "npx",
                ["-y", "@anthropic-ai/brave-search-mcp@latest"],
                env={"BRAVE_API_KEY": brave_key},
            )
        )

    # Jina AI Reader — converts any URL to readable markdown
    # Requires JINA_API_KEY (free tier available at https://jina.ai/)
    jina_key = os.getenv("JINA_API_KEY")
    if jina_key:
        servers.append(
            _http("jina", "https://r.jina.ai/mcp", {"Authorization": f"Bearer {jina_key}"})
        )

    you_key = os.getenv("YDC_API_KEY")
    if os.getenv("YDC_ENABLED", "1" if you_key else "0") == "1":
        if you_key:
            servers.append(
                _http("you", "https://api.you.com/mcp", {"Authorization": f"Bearer {you_key}"})
            )
        else:
            servers.append(_http("you", "https://api.you.com/mcp?profile=free", {}))

    # Excalidraw — live canvas with real-time sync via mcp-excalidraw-server
    excalidraw_server_url = os.getenv("EXCALIDRAW_SERVER_URL", "http://host.docker.internal:3000")
    if os.getenv("EXCALIDRAW_ENABLED", "1") == "1" and _docker_available():
        servers.append(
            _stdio(
                "excalidraw",
                "docker",
                [
                    "run",
                    "-i",
                    "--rm",
                    "-e",
                    f"EXPRESS_SERVER_URL={excalidraw_server_url}",
                    "-e",
                    "ENABLE_CANVAS_SYNC=true",
                    "ghcr.io/yctimlin/mcp_excalidraw:latest",
                ],
            )
        )
    elif os.getenv("EXCALIDRAW_ENABLED", "1") == "1":
        logger.warning("Excalidraw enabled but Docker is not available — skipping")

    # Playwright — browser automation for JS-heavy pages (requires PLAYWRIGHT_MCP=1)
    if os.getenv("PLAYWRIGHT_MCP"):
        servers.append(
            _stdio(
                "playwright",
                "npx",
                ["-y", "@playwright/mcp@latest", "--headless"],
            )
        )

    # Firecrawl — advanced web scraping/crawling (requires FIRECRAWL_API_KEY)
    firecrawl_key = os.getenv("FIRECRAWL_API_KEY")
    if firecrawl_key:
        servers.append(
            _stdio(
                "firecrawl",
                "npx",
                ["-y", "firecrawl-mcp@latest"],
                env={"FIRECRAWL_API_KEY": firecrawl_key},
            )
        )

    return servers
