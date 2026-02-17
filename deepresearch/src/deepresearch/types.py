"""Structured types for DeepResearch source tracking and reports."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Source(BaseModel):
    """A referenced source used in research."""

    id: int = Field(description="Unique source ID for inline citations [1], [2], etc.")
    title: str = Field(description="Title of the source (article, paper, page)")
    url: str = Field(description="Full URL to the source")
    author: str | None = Field(default=None, description="Author or organization name")
    date: str | None = Field(default=None, description="Publication or access date (YYYY-MM-DD)")
    source_type: str = Field(
        default="web",
        description="Type of source: 'web', 'paper', 'book', 'docs', 'forum'",
    )


class Finding(BaseModel):
    """A research finding with supporting evidence and citations."""

    claim: str = Field(description="The factual claim or finding")
    evidence: str = Field(description="Supporting evidence or quote")
    source_ids: list[int] = Field(description="IDs of sources that support this finding")
    confidence: str = Field(
        default="medium",
        description="Confidence level: 'high', 'medium', 'low'",
    )


class ReportSection(BaseModel):
    """A section of the research report."""

    title: str = Field(description="Section title")
    content: str = Field(description="Markdown content with inline citations [1][2]")
    findings: list[Finding] = Field(
        default_factory=list,
        description="Key findings in this section",
    )


class ReportMetadata(BaseModel):
    """Metadata about the research process."""

    total_sources: int = Field(default=0, description="Number of sources consulted")
    search_queries_used: int = Field(default=0, description="Number of search queries executed")
    pages_read: int = Field(default=0, description="Number of full pages read")
    research_duration_seconds: float = Field(
        default=0.0, description="Total research duration in seconds"
    )
    diagrams_generated: int = Field(default=0, description="Number of diagrams created")


class ResearchReport(BaseModel):
    """Structured research report with citations and metadata."""

    title: str = Field(description="Descriptive report title")
    question: str = Field(description="Original research question")
    executive_summary: str = Field(description="2-3 paragraph overview of key findings")
    sections: list[ReportSection] = Field(
        description="Report body sections with content and findings"
    )
    conclusions: list[str] = Field(description="Key takeaways and implications")
    sources: list[Source] = Field(description="All referenced sources")
    metadata: ReportMetadata = Field(
        default_factory=ReportMetadata,
        description="Research process metadata",
    )
