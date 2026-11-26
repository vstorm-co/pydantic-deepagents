FROM python:3.12-slim

# System deps: Node.js (npx MCP servers) + Docker CLI (per-session sandbox containers)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gnupg ca-certificates libpango-1.0-0 libpangoft2-1.0-0 \
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

# Copy application source
COPY src/ src/
COPY static/ static/
COPY skills/ skills/
COPY workspace/ workspace/
COPY pyproject.toml ./

# Install the app with the same dependencies as a native deployment.
RUN uv pip install --system -e ".[export]"

RUN mkdir -p workspaces

ENV DEEPRESEARCH_HOST=0.0.0.0
EXPOSE 8080

CMD ["python", "-m", "deepresearch.app"]
