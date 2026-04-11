#!/usr/bin/env bash
# pydantic-deep installer
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/vstorm-co/pydantic-deep/main/install.sh | bash

set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
DIM='\033[2m'
RESET='\033[0m'

say()  { printf "${BOLD}  pydantic-deep${RESET}  %s\n" "$*"; }
ok()   { printf "${GREEN}  ✓${RESET}  %s\n" "$*"; }
warn() { printf "${YELLOW}  !${RESET}  %s\n" "$*"; }
fail() { printf "${RED}  ✗${RESET}  %s\n" "$*"; exit 1; }

echo ""
printf "${BOLD}  pydantic-deep — installer${RESET}\n"
printf "  ─────────────────────────────\n"
echo ""

# ── OS check ──────────────────────────────────────────────────────────────────
OS="$(uname -s 2>/dev/null || echo unknown)"
case "${OS}" in
    Linux* | Darwin*) ;;
    *) fail "Unsupported OS: ${OS}. Only macOS and Linux are supported." ;;
esac

# ── Step 1: ensure uv is available ────────────────────────────────────────────
if command -v uv &>/dev/null; then
    ok "uv found: $(uv --version)"
else
    say "Installing uv (fast Python package manager)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # Source newly installed uv into current session
    for _dir in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
        [ -d "$_dir" ] && export PATH="$_dir:$PATH"
    done
    [ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"

    if ! command -v uv &>/dev/null; then
        fail "uv installation failed. See: https://docs.astral.sh/uv/getting-started/installation/"
    fi
    ok "uv installed: $(uv --version)"
fi

echo ""

# ── Step 2: install pydantic-deep ─────────────────────────────────────────────
say "Installing pydantic-deep CLI..."
uv tool install "pydantic-deep[cli]" --upgrade

echo ""

# ── Step 3: verify ────────────────────────────────────────────────────────────
# uv tool executables land in ~/.local/bin — add it for immediate verification
export PATH="$HOME/.local/bin:$PATH"

if command -v pydantic-deep &>/dev/null; then
    VERSION="$(pydantic-deep --version 2>&1 | head -1)"
    ok "${VERSION} installed successfully!"
    echo ""
    printf "  ${BOLD}Get started:${RESET}\n"
    echo ""
    printf "    ${BOLD}pydantic-deep${RESET}          # launch interactive TUI\n"
    printf "    ${BOLD}pydantic-deep --help${RESET}   # see all commands\n"
    echo ""
else
    echo ""
    warn "pydantic-deep was installed but is not yet in your PATH."
    warn "Add this line to your shell config (~/.zshrc or ~/.bashrc):"
    echo ""
    printf "    export PATH=\"\$HOME/.local/bin:\$PATH\"\n"
    echo ""
    warn "Then run:  source ~/.zshrc   (or restart your terminal)"
    echo ""
fi
