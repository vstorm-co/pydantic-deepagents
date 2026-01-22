# Installation

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Install with uv (recommended)

```bash
uv add pydantic-deep
```

## Install with pip

```bash
pip install pydantic-deep
```

## Optional Dependencies

pydantic-deep offers several optional dependency groups:

| Extra | Description | Use Case |
|-------|-------------|----------|
| `sandbox` | Docker container support | Isolated code execution |
| `cli` | CLI tools (typer, rich) | Interactive terminal apps |
| `web` | Web server (FastAPI, uvicorn) | Web-based agent interfaces |
| `dev` | Development tools | Testing and documentation |
| `all` | All optional dependencies | Everything |

### Docker Sandbox

For isolated code execution in Docker containers:

```bash
uv add pydantic-deep[sandbox]
# or
pip install pydantic-deep[sandbox]
```

!!! tip "Standalone Usage"
    Backends are also available separately as [`pydantic-ai-backend`](https://github.com/vstorm-co/pydantic-ai-backend) for use with any pydantic-ai agent.

### CLI Tools

For building interactive terminal applications:

```bash
uv add pydantic-deep[cli]
# or
pip install pydantic-deep[cli]
```

Includes: typer, rich, prompt-toolkit

### Web Server

For web-based agent interfaces:

```bash
uv add pydantic-deep[web]
# or
pip install pydantic-deep[web]
```

Includes: FastAPI, uvicorn

### All Dependencies

Install everything:

```bash
uv add pydantic-deep[all]
# or
pip install pydantic-deep[all]
```

### Development

For running tests and building documentation:

```bash
uv add pydantic-deep[dev]
# or
pip install pydantic-deep[dev]
```

## Environment Setup

### API Key

pydantic-deep uses Pydantic AI which supports multiple model providers. Set your API key:

=== "Anthropic"

    ```bash
    export ANTHROPIC_API_KEY=your-api-key
    ```

=== "OpenAI"

    ```bash
    export OPENAI_API_KEY=your-api-key
    ```

=== "Google"

    ```bash
    export GOOGLE_API_KEY=your-api-key
    ```

### Docker (optional)

For using `DockerSandbox`:

1. Install Docker: [Get Docker](https://docs.docker.com/get-docker/)
2. Ensure Docker daemon is running
3. Pull the Python image:

```bash
docker pull python:3.12-slim
```

## Verify Installation

```python
import asyncio
from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend

async def main():
    agent = create_deep_agent()
    deps = DeepAgentDeps(backend=StateBackend())

    result = await agent.run("Say hello!", deps=deps)
    print(result.output)

asyncio.run(main())
```

## Troubleshooting

### Import Errors

If you get import errors, ensure you have the correct Python version:

```bash
python --version  # Should be 3.10+
```

### API Key Not Found

Make sure your API key is set in the environment:

```bash
echo $ANTHROPIC_API_KEY
```

### Docker Permission Denied

On Linux, you may need to add your user to the docker group:

```bash
sudo usermod -aG docker $USER
```

Then log out and back in.

## Next Steps

- [Core Concepts](concepts/index.md) - Learn the fundamentals
- [Basic Usage Example](examples/basic-usage.md) - Your first deep agent
- [API Reference](api/index.md) - Complete API documentation
