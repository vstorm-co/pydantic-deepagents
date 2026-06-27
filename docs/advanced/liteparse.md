# Document parsing (liteparse)

Hand your agent a PDF, a Word doc, a spreadsheet, a slide deck, or a scanned image — and let it read.

The `liteparse` feature gives your agent two tools: one that pulls the **text** out of a document, and one that renders each page to a **PNG screenshot**. It all runs locally. No cloud service, no upload, no API key.

## Turn it on

Flip a single flag on [`create_deep_agent`][pydantic_deep.agent.create_deep_agent]:

```python hl_lines="7"
from pydantic_deep import create_deep_agent, create_default_deps
from pydantic_ai_backends import LocalBackend

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    include_liteparse=True,
)

deps = create_default_deps(LocalBackend(root_dir="."))
result = await agent.run(
    "Parse report.pdf and summarize the key findings.",
    deps=deps,
)
print(result.output)
```

The agent now has `parse_document` and `screenshot_document` alongside its usual files and shell. When the prompt mentions `report.pdf`, it reaches for `parse_document`, gets the text back, and writes you a summary — no plumbing on your side.

!!! info "Use a real backend"
    Document parsing reads files from the agent's backend. Use a `LocalBackend`
    (or any backend with real bytes behind it), not the in-memory `StateBackend`,
    so the files you want to parse are actually there.

## The two tools

| Tool | What it does |
|------|--------------|
| `parse_document` | Extracts the full text of a document, layout preserved, with OCR for scanned pages. Returns the text (prefixed with the page count). |
| `screenshot_document` | Renders pages to PNG images, saves them to the backend, and returns the saved paths. Great for visual inspection or handing pages to a multimodal model. |

You don't call these yourself — the agent does, when the task calls for it. Ask it to "read", "summarize", or "extract" and it parses; ask it to "show me page 3" or "screenshot the cover" and it renders.

`parse_document` takes a single `path` into the backend filesystem. `screenshot_document` takes a `path`, an optional `output_dir` (defaults to `/screenshots`), and an optional `target_pages` like `"1-5"` or `"1,3,5"` (omit it for every page).

## Supported formats

- **PDF** — native text extraction, with OCR falling in for scanned pages.
- **Microsoft Office** — DOCX, XLSX, PPTX (needs LibreOffice on the system).
- **OpenDocument** — ODT, ODS, ODP (needs LibreOffice).
- **Images** — PNG, JPG, TIFF, and more (needs ImageMagick).

`parse_document` handles all of the above. `screenshot_document` renders PDFs and images.

## Requirements

Parsing is powered by [LiteParse](https://github.com/run-llama/liteparse), a Node.js CLI that the Python wrapper drives via subprocess. So you need three things:

- **Node.js >= 18** on the system.
- **The LiteParse CLI** — `npm install -g @llamaindex/liteparse`.
- **The Python extra** — `pip install pydantic-deep[liteparse]`.

!!! tip "First run auto-installs the CLI"
    If the CLI is missing but `npm` is on the `PATH`, LiteParse installs it for
    you on first use (`install_if_not_available=True`, the default). Handy
    locally, but for Docker and production, pre-install it in your image so the
    first request isn't waiting on `npm`.

### Docker

```dockerfile
FROM python:3.12-slim

# Node.js
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs

# LiteParse CLI, pre-installed so the first request is fast
RUN npm install -g @llamaindex/liteparse

COPY . .
RUN pip install pydantic-deep[liteparse]
```

## Tuning it: use the toolset directly

`include_liteparse=True` is the easy path with sensible defaults. When you want to set the OCR language, bump the DPI, or point at a custom OCR server, build [`LiteparseToolset`][pydantic_deep.LiteparseToolset] yourself and pass it as a toolset:

```python hl_lines="6 7 8 9 10"
from pydantic_ai import Agent
from pydantic_deep import DeepAgentDeps
from pydantic_deep.features.liteparse import LiteparseToolset

toolset = LiteparseToolset(
    ocr_enabled=True,
    ocr_language="en",
    dpi=300,
)

agent = Agent(
    "anthropic:claude-sonnet-4-6",
    deps_type=DeepAgentDeps,
    toolsets=[toolset],
)
```

Every knob, with its default:

| Parameter | Default | What it controls |
|-----------|---------|------------------|
| `ocr_enabled` | `True` | Run OCR on scanned / image-based pages. |
| `ocr_language` | `"en"` | OCR language code (`"en"`, `"fr"`, `"de"`, …). |
| `ocr_server_url` | `None` | HTTP OCR server URL. Falls back to built-in Tesseract when unset. |
| `dpi` | `150` | Render resolution. Higher means better OCR, but slower. |
| `max_pages` | `10000` | Cap on pages parsed per document. |
| `install_if_not_available` | `True` | Auto-install the CLI via npm on first use. |
| `descriptions` | `None` | Override tool descriptions (`parse_document`, `screenshot_document`). |

### A higher-accuracy OCR server

Built-in Tesseract is fine for clean scans. For tougher documents, point `ocr_server_url` at a PaddleOCR or EasyOCR server:

```python
LiteparseToolset(
    ocr_server_url="http://localhost:8828/ocr",
    ocr_language="en",
    dpi=200,
)
```

The LiteParse repo ships [reference OCR servers](https://github.com/run-llama/liteparse/tree/main/ocr) for EasyOCR and PaddleOCR you can run as-is.

## Good to know

- `parse_document` streams the file's bytes to the CLI over stdin — no temp file is written for PDFs.
- `screenshot_document` writes a temp file, renders it, then copies the PNGs into your backend under `output_dir`.
- The first call in a process can be slow — Node.js plus the PDF engine has a cold start. Later calls reuse the same parser instance and are quick.
- Missing the extra or the CLI? The tools return a clear message telling the agent (and you) exactly what to install, rather than crashing the run.

## Recap

- `include_liteparse=True` hands your agent `parse_document` and `screenshot_document` — local document parsing, no cloud.
- `parse_document` extracts text (with OCR) from PDF, DOCX, XLSX, PPTX, ODF, and images; `screenshot_document` renders PDFs and images to PNGs in the backend.
- It needs Node.js >= 18, the `@llamaindex/liteparse` CLI, and the `pydantic-deep[liteparse]` extra — pre-install the CLI in Docker.
- For OCR language, DPI, or a custom OCR server, build [`LiteparseToolset`][pydantic_deep.LiteparseToolset] directly instead of the flag.

Where to go next:

- [Files & the shell →](../learn/files-and-shell.md) — where the documents your agent parses actually live.
- [Structured output →](../learn/structured-output.md) — turn a parsed document into a typed result.
