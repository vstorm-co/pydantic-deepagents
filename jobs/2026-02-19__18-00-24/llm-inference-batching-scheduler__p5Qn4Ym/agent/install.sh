#!/bin/bash
set -euo pipefail

# Install system dependencies
if command -v apk &> /dev/null; then
    apk add --no-cache curl bash git procps
elif command -v apt-get &> /dev/null; then
    apt-get update
    apt-get install -y curl git procps
fi

# Install uv (fast Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# Install pydantic-deep with CLI extras into the system Python

uv pip install --system "pydantic-deep[cli]"


# Verify installation — try entry point first, fall back to module
if command -v pydantic-deep &> /dev/null; then
    pydantic-deep --help
else
    python3 -m pydantic_deep.cli.main --help
fi

# Create working directories
mkdir -p /logs/agent