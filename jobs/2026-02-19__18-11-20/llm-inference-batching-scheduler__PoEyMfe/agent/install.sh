#!/bin/bash
set -euo pipefail

# Install system dependencies
if command -v apk &> /dev/null; then
    apk add --no-cache curl bash git procps python3
elif command -v apt-get &> /dev/null; then
    apt-get update
    apt-get install -y curl git procps python3 python3-pip python3-venv
fi

# Install uv (fast Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# Ensure a Python is available for uv
if ! command -v python3 &> /dev/null; then
    uv python install 3.12
fi

# Install pydantic-deep from git (CLI not yet published to PyPI)

uv pip install --system "pydantic-deep[cli] @ git+https://github.com/vstorm-co/pydantic-deep.git@feat/cli"


# Verify installation — try entry point first, fall back to module
if command -v pydantic-deep &> /dev/null; then
    pydantic-deep --help
else
    python3 -m pydantic_deep.cli.main --help
fi

# Create working directories
mkdir -p /logs/agent