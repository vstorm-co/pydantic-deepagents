"""DeepResearch — autonomous research agent powered by pydantic-deep + MCP."""

from .agent import create_research_agent
from .config import MODEL_NAME, create_mcp_servers
from .types import (
    Finding,
    ReportMetadata,
    ReportSection,
    ResearchReport,
    Source,
)

__all__ = [
    "create_research_agent",
    "create_mcp_servers",
    "MODEL_NAME",
    "Finding",
    "ReportMetadata",
    "ReportSection",
    "ResearchReport",
    "Source",
]
