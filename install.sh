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

# ── Step 2: ask about optional features ──────────────────────────────────────
echo ""
printf "  ${BOLD}Optional features${RESET}\n"
printf "  ─────────────────────────────\n"
echo ""

# LiteParse document parsing
INSTALL_LITEPARSE=false
printf "  Install document parsing support via ${BOLD}LiteParse${RESET}?\n"
printf "  Parses PDFs, DOCX, XLSX and more — runs locally with optional OCR.\n"
printf "  Requires ${BOLD}Node.js >= 18${RESET} on your system.\n"
printf "  [Y/n] "
read -r _lp_answer </dev/tty
case "${_lp_answer:-Y}" in
    [Yy]*) INSTALL_LITEPARSE=true ;;
    *)     ok "Skipping LiteParse — enable later with: pydantic-deep run --liteparse" ;;
esac

echo ""

# ── Step 3: install pydantic-deep ─────────────────────────────────────────────
if $INSTALL_LITEPARSE; then
    say "Installing pydantic-deep CLI (with browser and liteparse support)..."
    uv tool install "pydantic-deep[cli,browser,liteparse]" --upgrade
else
    say "Installing pydantic-deep CLI (with browser support)..."
    uv tool install "pydantic-deep[cli,browser]" --upgrade
fi

echo ""

# ── Step 4: install Chromium for browser automation ───────────────────────────
say "Installing Chromium for browser automation..."
# uv tool executables land in ~/.local/bin — ensure it's in PATH
export PATH="$HOME/.local/bin:$PATH"

# playwright entry-point is installed alongside pydantic-deep in the same tool env
if playwright install chromium 2>/dev/null; then
    ok "Chromium installed."
else
    warn "Chromium install failed — run 'playwright install chromium' manually."
fi

echo ""

# ── Step 5: install LiteParse CLI (Node.js) ───────────────────────────────────
if $INSTALL_LITEPARSE; then
    say "Setting up LiteParse document parsing..."

    # Check for Node.js
    if command -v node &>/dev/null; then
        NODE_VERSION="$(node --version 2>/dev/null | sed 's/v//')"
        NODE_MAJOR="$(echo "$NODE_VERSION" | cut -d. -f1)"
        if [ "$NODE_MAJOR" -ge 18 ] 2>/dev/null; then
            ok "Node.js ${NODE_VERSION} found."
        else
            warn "Node.js ${NODE_VERSION} is too old (need >= 18). Installing a newer version..."
            if command -v nvm &>/dev/null; then
                nvm install 20 && nvm use 20 || warn "nvm install failed — install Node.js 20 manually from https://nodejs.org/"
            else
                warn "Please install Node.js >= 18 from https://nodejs.org/ and re-run:"
                warn "  npm install -g @llamaindex/liteparse"
            fi
        fi
    else
        warn "Node.js not found. Install Node.js >= 18 from https://nodejs.org/ and then run:"
        warn "  npm install -g @llamaindex/liteparse"
    fi

    # Install the LiteParse CLI if npm is available and Node.js >= 18
    if command -v npm &>/dev/null && command -v node &>/dev/null; then
        NODE_MAJOR="$(node --version 2>/dev/null | sed 's/v//' | cut -d. -f1)"
        if [ "${NODE_MAJOR:-0}" -ge 18 ] 2>/dev/null; then
            if npm install -g @llamaindex/liteparse 2>/dev/null; then
                ok "LiteParse CLI installed."
            else
                warn "LiteParse CLI install failed — run 'npm install -g @llamaindex/liteparse' manually."
            fi
        fi
    fi

    echo ""
fi

# ── Step 6: verify ────────────────────────────────────────────────────────────
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
