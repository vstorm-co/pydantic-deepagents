# Document Parsing (LiteParse)

`LiteparseToolset` gives the agent the ability to extract text and generate page screenshots
from PDFs, Word documents, spreadsheets, and other document formats — locally, with no cloud
services required.

Parsing is powered by [LiteParse](https://github.com/run-llama/liteparse), a Node.js library
with optional OCR. The Python package wraps its CLI via subprocess.

## Requirements

- **Node.js >= 18** installed on the system
- **LiteParse CLI**: `npm install -g @llamaindex/liteparse`
- **Python extra**: `pip install pydantic-deep[liteparse]`

The CLI is auto-installed via npm on first use if `npm` is in PATH (controlled by
`install_if_not_available`, default `True`). For production/Docker deployments,
pre-install the CLI in your `Dockerfile` instead.

### Docker

```dockerfile
FROM python:3.12-slim

# Install Node.js
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs

# Pre-install LiteParse CLI
RUN npm install -g @llamaindex/liteparse

COPY . .
RUN pip install pydantic-deep[liteparse]
```

## Quick Start

Enable with `include_liteparse=True` in [`create_deep_agent`][pydantic_deep.agent.create_deep_agent]:

```python
from pydantic_deep import create_deep_agent, create_default_deps
from pydantic_ai_backends import LocalBackend

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    include_liteparse=True,
)

deps = create_default_deps(LocalBackend(root_dir="."))
result = await agent.run("Parse report.pdf and summarize the key findings", deps=deps)
```

## Standalone Usage

Use [`LiteparseToolset`][pydantic_deep.LiteparseToolset] directly for fine-grained control:

```python
from pydantic_ai import Agent
from pydantic_deep import DeepAgentDeps
from pydantic_deep.toolsets.liteparse import LiteparseToolset

agent = Agent(
    "anthropic:claude-sonnet-4-6",
    deps_type=DeepAgentDeps,
    toolsets=[
        LiteparseToolset(
            ocr_enabled=True,
            ocr_language="en",
            dpi=300,
        )
    ],
)
```

## Available Tools

| Tool | Description |
|------|-------------|
| `parse_document` | Extract full text from a document (PDF, DOCX, XLSX, images, …) |
| `screenshot_document` | Generate per-page PNG screenshots saved to the backend |

## Configuration Options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `ocr_enabled` | `True` | Enable OCR for scanned/image-based documents |
| `ocr_language` | `"en"` | OCR language code (`"en"`, `"fr"`, `"de"`, …) |
| `ocr_server_url` | `None` | HTTP OCR server URL. Uses built-in Tesseract when not set |
| `dpi` | `150` | Rendering DPI — higher is better for OCR but slower |
| `max_pages` | `10000` | Maximum pages to parse per document |
| `install_if_not_available` | `True` | Auto-install CLI via npm on first use |
| `descriptions` | `None` | Dict to override tool descriptions (`parse_document`, `screenshot_document`) |

## Supported Formats

- **PDF** — native text extraction + OCR for scanned pages
- **Microsoft Office** — DOCX, XLSX, PPTX (requires LibreOffice on the system)
- **OpenDocument** — ODT, ODS, ODP (requires LibreOffice)
- **Images** — PNG, JPG, TIFF and more (requires ImageMagick)

## Custom OCR Server

Point to a PaddleOCR or EasyOCR server for higher accuracy:

```python
LiteparseToolset(
    ocr_server_url="http://localhost:8828/ocr",
    ocr_language="en",
    dpi=200,
)
```

See the [OCR server examples](https://github.com/run-llama/liteparse/tree/main/ocr)
in the LiteParse repository for EasyOCR and PaddleOCR server implementations.

## Notes

- `parse_document` passes file contents as bytes to the CLI via stdin — no temp files written for PDFs.
- `screenshot_document` writes the file to a temp directory, calls the CLI, then copies images to the backend.
- Large documents may be slow on first call due to Node.js + PDF engine cold start. Subsequent calls within the same process reuse the parser instance.
