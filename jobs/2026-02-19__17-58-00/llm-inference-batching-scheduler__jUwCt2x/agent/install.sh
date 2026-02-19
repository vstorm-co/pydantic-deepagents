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

# Install pydantic-deep with CLI extras

uv tool install "pydantic-deep[cli]"


# Verify installation
pydantic-deep --help

# Create working directories
mkdir -p /logs/agent