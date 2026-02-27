FROM python:3.12-slim

# System deps: Node.js (npx MCP servers) + Docker CLI (SessionManager sandbox containers)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gnupg ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
        | gpg --dearmor -o /usr/share/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker.gpg] \
        https://download.docker.com/linux/debian bookworm stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends \
        nodejs docker-ce-cli \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Install from PyPI (no local editable deps)
RUN uv pip install --system \
    "pydantic-deep[web]" \
    "pydantic-ai[mcp]" \
    "pydantic-ai-middleware" \
    "pydantic-ai-backend[docker]" \
    "summarization-pydantic-ai" \
    "subagents-pydantic-ai" \
    "pydantic-ai-todo" \
    "python-dotenv>=1.0" \
    "markdown>=3.5" \
    "weasyprint>=60.0"

# Copy application source
COPY src/ src/
COPY static/ static/
COPY skills/ skills/
COPY workspace/ workspace/
COPY pyproject.toml ./

# Install deepresearch itself
RUN uv pip install --system --no-deps -e .

RUN mkdir -p workspaces

EXPOSE 8080

CMD ["python", "-m", "deepresearch.app"]
