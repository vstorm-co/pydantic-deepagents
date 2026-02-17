"""DeepResearch configuration — MCP servers, model, paths."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from pydantic_ai.mcp import MCPServerStdio, MCPServerStreamableHTTP
from pydantic_ai.toolsets import AbstractToolset

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

APP_DIR = Path(__file__).resolve().parent.parent.parent  # deepresearch/
SKILLS_DIR = APP_DIR / "skills"
WORKSPACE_DIR = APP_DIR / "workspace"
WORKSPACES_DIR = APP_DIR / "workspaces"
STATIC_DIR = APP_DIR / "static"

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

MODEL_NAME: str = os.getenv("MODEL_NAME", "openai:gpt-4.1")

# ---------------------------------------------------------------------------
# Excalidraw Canvas
# ---------------------------------------------------------------------------

EXCALIDRAW_CANVAS_URL: str = os.getenv("EXCALIDRAW_CANVAS_URL", "http://localhost:3000")

# ---------------------------------------------------------------------------
# MCP Servers
# ---------------------------------------------------------------------------


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


def create_mcp_servers() -> list[AbstractToolset]:
    """Create MCP server toolsets based on available API keys.

    Returns a list of MCP servers that can be passed as toolsets to the agent.
    Servers are started/stopped automatically by pydantic-ai when the agent
    enters/exits its async context manager.
    """
    servers: list[AbstractToolset] = []

    # Tavily — AI-optimized web search (requires TAVILY_API_KEY)
    tavily_key = os.getenv("TAVILY_API_KEY")
    if tavily_key:
        servers.append(
            MCPServerStdio(
                "npx",
                ["-y", "tavily-mcp@latest"],
                env={"TAVILY_API_KEY": tavily_key},
                tool_prefix="tavily",
                max_retries=3,
            )
        )

    # Brave Search — web search (requires BRAVE_API_KEY)
    brave_key = os.getenv("BRAVE_API_KEY")
    if brave_key:
        servers.append(
            MCPServerStdio(
                "npx",
                ["-y", "@anthropic-ai/brave-search-mcp@latest"],
                env={"BRAVE_API_KEY": brave_key},
                tool_prefix="brave",
                max_retries=3,
            )
        )

    # Jina AI Reader — converts any URL to readable markdown
    # Requires JINA_API_KEY (free tier available at https://jina.ai/)
    jina_key = os.getenv("JINA_API_KEY")
    if jina_key:
        servers.append(
            MCPServerStreamableHTTP(
                url="https://r.jina.ai/mcp",
                headers={"Authorization": f"Bearer {jina_key}"},
                tool_prefix="jina",
                max_retries=3,
            )
        )

    # Excalidraw — live canvas with real-time sync via mcp-excalidraw-server
    excalidraw_server_url = os.getenv("EXCALIDRAW_SERVER_URL", "http://host.docker.internal:3000")
    if os.getenv("EXCALIDRAW_ENABLED", "1") == "1" and _docker_available():
        servers.append(
            MCPServerStdio(
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
                tool_prefix="excalidraw",
            )
        )
    elif os.getenv("EXCALIDRAW_ENABLED", "1") == "1":
        logger.warning("Excalidraw enabled but Docker is not available — skipping")

    # Playwright — browser automation for JS-heavy pages (requires PLAYWRIGHT_MCP=1)
    if os.getenv("PLAYWRIGHT_MCP"):
        servers.append(
            MCPServerStdio(
                "npx",
                ["-y", "@playwright/mcp@latest", "--headless"],
                tool_prefix="playwright",
            )
        )

    # Firecrawl — advanced web scraping/crawling (requires FIRECRAWL_API_KEY)
    firecrawl_key = os.getenv("FIRECRAWL_API_KEY")
    if firecrawl_key:
        servers.append(
            MCPServerStdio(
                "npx",
                ["-y", "firecrawl-mcp@latest"],
                env={"FIRECRAWL_API_KEY": firecrawl_key},
                tool_prefix="firecrawl",
                max_retries=3,
            )
        )

    return servers
