#!/bin/bash
set -euo pipefail

# Install system dependencies
if command -v apk &> /dev/null; then
    apk add --no-cache curl bash git procps python3
elif command -v apt-get &> /dev/null; then
    apt-get update
    apt-get install -y curl git procps python3 python3-venv
fi

# Install uv (fast Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# Ensure a Python is available for uv
if ! command -v python3 &> /dev/null; then
    uv python install 3.12
fi

# Create a venv (Ubuntu 24.04 blocks --system installs via PEP 668)
uv venv /opt/pydantic-deep-venv
export PATH="/opt/pydantic-deep-venv/bin:$PATH"
export VIRTUAL_ENV="/opt/pydantic-deep-venv"

# Install pydantic-deep from git (CLI not yet published to PyPI)

uv pip install "pydantic-deep[cli] @ git+https://github.com/vstorm-co/pydantic-deep.git@feat/cli"


# Verify installation
pydantic-deep --help

# Create working directories
mkdir -p /logs/agent