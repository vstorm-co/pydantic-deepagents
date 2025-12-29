"""Paper analysis tools for research assistant agent."""

from __future__ import annotations

import re
from io import BytesIO

import fitz
import pymupdf4llm
import pypdf
from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from pydantic_deep.deps import DeepAgentDeps


def _citation(path: str, quote: str) -> str:
    quote_clean = quote.replace("\n", " ").strip()
    return f"[[citation:{path}|{quote_clean}]]"


def create_paper_toolset(id: str | None = None) -> FunctionToolset[DeepAgentDeps]:
    """Create a toolset with paper analysis operations.

    Args:
        id: Optional unique ID for the toolset.

    Returns:
        FunctionToolset with paper analysis tools.
    """
    toolset: FunctionToolset[DeepAgentDeps] = FunctionToolset(id=id)

    @toolset.tool
    async def paper_extract_metadata(
        ctx: RunContext[DeepAgentDeps],
        file_path: str,
    ) -> str:
        """Extract metadata from the paper (title, authors, abstract, etc.).

        Args:
            file_path: Path to the paper file.
        """
        # Read raw bytes from file
        file_bytes = ctx.deps.backend._read_bytes(file_path)

        # Read PDF metadata
        try:
            pdf_file = BytesIO(file_bytes)
            pdf_reader = pypdf.PdfReader(pdf_file)

            metadata = pdf_reader.metadata
            if metadata:
                title = metadata.get("/Title") or "Unknown Title"
                authors = metadata.get("/Author") or "Unknown Authors"
                abstract = metadata.get("/Abstract") or "Unknown Abstract"
                keywords = metadata.get("/Keywords") or "Unknown Keywords"
                affiliations = metadata.get("/Affiliations") or "Unknown Affiliations"
                publication_date = metadata.get("/PublicationDate") or "Unknown Publication Date"
                journal = metadata.get("/Journal") or "Unknown Journal"
                doi = metadata.get("/DOI") or "Unknown DOI"
            else:
                title = "Unknown Title"
                authors = "Unknown Authors"
                abstract = "Unknown Abstract"
                keywords = "Unknown Keywords"
                affiliations = "Unknown Affiliations"
                publication_date = "Unknown Publication Date"
                journal = "Unknown Journal"
                doi = "Unknown DOI"

            return (
                f"Title: {title}\n"
                f"  Authors: {authors}\n"
                f"  Abstract: {abstract}\n"
                f"  Keywords: {keywords}\n"
                f"  Affiliations: {affiliations}\n"
                f"  Publication Date: {publication_date}\n"
                f"  Journal: {journal}\n"
                f"  DOI: {doi}\n"
                f"Source: {_citation(file_path, title or 'paper')}\n"
            )
        except Exception as e:
            return f"[Error extracting metadata: {e}]"

    @toolset.tool
    async def paper_extract_references(
        ctx: RunContext[DeepAgentDeps],
        file_path: str,
    ) -> str:
        """Extract references section of the paper.

        Args:
            file_path: Path to the paper file.
        """
        try:
            file_bytes = ctx.deps.backend._read_bytes(file_path)

            with fitz.open(stream=file_bytes, filetype="pdf") as doc:
                # Convert entire PDF to Markdown
                md_text = pymupdf4llm.to_markdown(doc, ignore_images=True, remove_page_breaks=True)

            # Find References Section in the Markdown

            # Regex explanation:
            # ^           : Start of a line
            # (?:\#+|\*\*)?: Optional markdown header markers (# or **)
            # \s* : Optional space
            # References  : The target word (case insensitive)
            # ...         : Optional punctuation/trailing formatting
            ref_header_pattern = re.compile(
                r"(?:^|\n)\s*(?:#+|\*\*|__)?\s*(?:\d+\.|[IVX]+\.)?\s*(references|bibliography|literature)\s*(?:#+|\*\*|__|:)?\s*$",
                re.IGNORECASE | re.MULTILINE,
            )

            match = ref_header_pattern.search(md_text)

            if match:
                # Slice text from the end of the header
                ref_content = md_text[match.end() :]

                # Check for Stop Sections (Appendix, etc.)
                stop_pattern = re.compile(
                    r"(?:^|\n)\s*(?:#+|\*\*|__)?\s*(?:\d+\.|[IVX]+\.)?\s*"
                    r"(appendix|supplementary|acknowledg|about the author)",
                    re.IGNORECASE | re.MULTILINE,
                )
                stop_match = stop_pattern.search(ref_content)

                if stop_match:
                    ref_content = ref_content[: stop_match.start()]

                return (
                    f"References:\n{ref_content.strip()}\n"
                    f"Source: {_citation(file_path, 'references section')}"
                )

            # Fallback if Header is Missing, return last 20% of text
            token_estimate = len(md_text)
            tail_start = int(token_estimate * 0.8)  # Last 20%
            tail_text = md_text[tail_start:]

            return (
                "[Warning: Could not detect explicit 'References' header. "
                "Returning the last 20% of the document content:]\n\n"
                + tail_text
                + f"\nSource: {_citation(file_path, 'references section')}"
            )

        except Exception as e:
            return f"[Error extracting references: {str(e)}]"

    return toolset


# System prompt for Paper Analysis tools
PAPER_ANALYSIS_SYSTEM_PROMPT = """
## Paper Analysis Tools

You have access to Paper Analysis tools:

- `paper_extract_metadata`: Extract metadata from a research paper PDF file,
  including title, authors, abstract, keywords, affiliations, publication date,
  journal, and DOI.

- `paper_extract_references`: Extract the references section from a research
  paper PDF file.
"""
