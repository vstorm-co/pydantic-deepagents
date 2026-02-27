---
name: build-and-compile
description: "Building, compiling, and resolving dependency issues across languages"
tags: [build, compile, dependencies, benchmark]
version: "1.0.0"
---

# Build & Compile

Strategies for building code and resolving dependency issues.

## Build System Detection

Check for build files in order:
- `Makefile` → `make` (read it first to understand targets)
- `CMakeLists.txt` → `cmake -B build && cmake --build build`
- `pyproject.toml` / `setup.py` → `pip install -e .`
- `package.json` → `npm install && npm run build`
- `Cargo.toml` → `cargo build --release`
- `go.mod` → `go build ./...`
- No build system → compile directly (`gcc`, `g++`, `rustc`, etc.)

## Compilation Strategies

### C/C++
- Always read the Makefile/CMakeLists first
- Common flags: `-O2 -Wall -lm -lpthread`
- Missing headers → `apt-get install lib<name>-dev`
- Linking errors → check library order (dependencies last: `-lfoo -lbar -lm`)

### Python
- Use virtual environments when possible
- `pip install -e .` for editable installs
- Missing modules → check `requirements.txt`, `pyproject.toml`
- Version conflicts → read the actual error, pin versions

### Multi-language projects
- Build dependencies first (C libraries before Python bindings)
- Check for Cython, SWIG, or FFI bridges
- Environment variables often needed: `LD_LIBRARY_PATH`, `PYTHONPATH`

## Dependency Resolution

1. Read the FULL error message — the missing dependency is usually named
2. Search for the package: `apt-cache search <name>`, `pip search <name>`
3. Install the minimum needed — don't install everything
4. If a package is unavailable, check for alternatives or build from source

## Common Build Failures

| Error | Likely Cause | Fix |
|-------|-------------|-----|
| `fatal error: foo.h: No such file` | Missing dev headers | `apt-get install libfoo-dev` |
| `undefined reference to` | Missing library at link time | Add `-lfoo` flag |
| `No module named 'foo'` | Missing Python package | `pip install foo` |
| `command not found: make` | Build tools missing | `apt-get install build-essential` |
| `version 'GLIBC_X.Y' not found` | Binary built for newer system | Rebuild from source |
