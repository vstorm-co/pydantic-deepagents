# Contributing to pydantic-deep

Thanks for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/vstorm-co/pydantic-deepagents.git
cd pydantic-deepagents
make install
```

## Running Tests

```bash
make test        # Run tests with coverage
make all         # Run lint + typecheck + test
```

## Requirements

All PRs must meet these requirements:

- **100% test coverage** — no exceptions
- **Pass Pyright** — `make typecheck`
- **Pass MyPy** — `make typecheck-mypy`
- **Pass Ruff** — `make lint`

## Quick Commands

| Command | Description |
|---------|-------------|
| `make install` | Install dependencies |
| `make test` | Run tests with coverage |
| `make lint` | Run Ruff linter |
| `make typecheck` | Run Pyright |
| `make typecheck-mypy` | Run MyPy |
| `make all` | Run all checks |
| `make docs-serve` | Serve docs locally |

## Running Specific Tests

```bash
# Single test
uv run pytest tests/test_agent.py::test_function_name -v

# Single file
uv run pytest tests/test_agent.py -v

# With debug output
uv run pytest tests/test_agent.py -v -s
```

## Code Style

- We use [Ruff](https://github.com/astral-sh/ruff) for linting and formatting
- Run `make lint` to check and `uv run ruff format .` to auto-format
- Follow existing patterns in the codebase

## Pull Request Process

1. Fork the repo and create your branch from `main`
2. Make your changes
3. Ensure `make all` passes
4. Submit a PR with a clear description

## Questions?

Open an issue on [GitHub](https://github.com/vstorm-co/pydantic-deepagents/issues).
