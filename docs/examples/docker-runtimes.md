# Docker Runtimes

This guide shows how to use `RuntimeConfig` and `SessionManager` for Docker-based code execution with pre-configured environments.

## Quick Start

```python
from pydantic_deep import DockerSandbox, DeepAgentDeps, create_deep_agent

# Use a built-in runtime with pre-installed packages
sandbox = DockerSandbox(runtime="python-datascience")
deps = DeepAgentDeps(backend=sandbox)

agent = create_deep_agent()
result = await agent.run(
    "Load /uploads/data.csv and create a visualization",
    deps=deps,
)

sandbox.stop()
```

## RuntimeConfig

The [`RuntimeConfig`][pydantic_deep.types.RuntimeConfig] class defines a pre-configured execution environment.

### Using Built-in Runtimes

pydantic-deep provides several built-in runtimes:

| Runtime | Description | Packages |
|---------|-------------|----------|
| `python-minimal` | Clean Python 3.12 | None |
| `python-datascience` | Data science stack | pandas, numpy, matplotlib, scikit-learn, seaborn |
| `python-web` | Web development | FastAPI, SQLAlchemy, httpx, uvicorn |
| `node-minimal` | Clean Node.js 20 | None |
| `node-react` | React development | TypeScript, Vite, React |

```python
from pydantic_deep import DockerSandbox, BUILTIN_RUNTIMES

# Option 1: Use runtime name (string)
sandbox = DockerSandbox(runtime="python-datascience")

# Option 2: Use RuntimeConfig directly
sandbox = DockerSandbox(runtime=BUILTIN_RUNTIMES["python-datascience"])
```

### Creating Custom Runtimes

```python
from pydantic_deep import RuntimeConfig, DockerSandbox

# Custom ML runtime
ml_runtime = RuntimeConfig(
    name="ml-env",
    description="Machine learning environment with PyTorch",
    base_image="python:3.12-slim",
    packages=["torch", "transformers", "datasets", "accelerate"],
    setup_commands=["apt-get update", "apt-get install -y git"],
    env_vars={"TOKENIZERS_PARALLELISM": "false"},
    work_dir="/workspace",
)

sandbox = DockerSandbox(runtime=ml_runtime)
```

### Runtime Configuration Options

```python
RuntimeConfig(
    name="my-runtime",           # Unique identifier
    description="...",           # Human-readable description

    # Image source (choose one):
    image="my-registry/image:v1",  # Pre-built image
    # OR
    base_image="python:3.12",      # Base image to build upon

    # Packages (only with base_image):
    packages=["pandas", "numpy"],
    package_manager="pip",  # pip, npm, apt, cargo

    # Additional setup:
    setup_commands=["apt-get update"],
    env_vars={"DEBUG": "true"},
    work_dir="/workspace",

    # Caching:
    cache_image=True,  # Cache built images locally
)
```

## SessionManager

For multi-user applications, use [`SessionManager`][pydantic_deep.session.SessionManager] to manage isolated containers per user.

### Basic Usage

```python
from pydantic_deep import SessionManager, DeepAgentDeps, create_deep_agent

# Create manager with default runtime
manager = SessionManager(default_runtime="python-datascience")

async def handle_user_request(user_id: str, query: str):
    # Get or create sandbox for this user
    sandbox = await manager.get_or_create(user_id)

    deps = DeepAgentDeps(backend=sandbox)
    agent = create_deep_agent()

    result = await agent.run(query, deps=deps)
    return result.output

# Clean up idle sessions periodically
await manager.cleanup_idle(max_idle=1800)  # 30 minutes

# Shutdown all sessions when done
await manager.shutdown()
```

### Session Persistence

Sessions persist between requests for the same user:

```python
# Request 1: Create a file
sandbox = await manager.get_or_create("user-123")
sandbox.execute("echo 'hello' > /workspace/greeting.txt")

# Request 2: File still exists!
sandbox = await manager.get_or_create("user-123")  # Same container
result = sandbox.execute("cat /workspace/greeting.txt")
print(result.output)  # "hello"
```

### Automatic Cleanup

```python
# Start background cleanup loop
manager.start_cleanup_loop(interval=300)  # Check every 5 minutes

# ... your application runs ...

# Stop cleanup when shutting down
manager.stop_cleanup_loop()
await manager.shutdown()
```

### Configuration Options

```python
SessionManager(
    default_runtime="python-datascience",  # Default for new sessions
    default_idle_timeout=3600,             # 1 hour idle timeout
)
```

## Complete Example

```python
import asyncio
from pydantic_deep import (
    create_deep_agent,
    DeepAgentDeps,
    SessionManager,
    RuntimeConfig,
)

async def main():
    # Custom runtime for data analysis
    runtime = RuntimeConfig(
        name="analysis-env",
        description="Data analysis environment",
        base_image="python:3.12-slim",
        packages=["pandas", "numpy", "matplotlib", "seaborn"],
    )

    # Session manager for multiple users
    manager = SessionManager(
        default_runtime=runtime,
        default_idle_timeout=1800,  # 30 minutes
    )

    try:
        # Simulate multiple users
        for user_id in ["alice", "bob", "charlie"]:
            sandbox = await manager.get_or_create(user_id)
            deps = DeepAgentDeps(backend=sandbox)

            # Upload user-specific data
            with open(f"{user_id}_data.csv", "rb") as f:
                deps.upload_file("data.csv", f.read())

            agent = create_deep_agent()
            result = await agent.run(
                "Analyze /uploads/data.csv and create a summary",
                deps=deps,
            )
            print(f"{user_id}: {result.output[:100]}...")

        # Check active sessions
        print(f"Active sessions: {manager.session_count}")

    finally:
        # Clean up all sessions
        count = await manager.shutdown()
        print(f"Cleaned up {count} sessions")

if __name__ == "__main__":
    asyncio.run(main())
```

## System Prompt Integration

When using a runtime with DockerSandbox, the agent automatically receives information about the available packages:

```
## Runtime Environment

**Name:** python-datascience
**Description:** Python with pandas, numpy, matplotlib, scikit-learn, seaborn
**Working directory:** /workspace

**Pre-installed packages** (use directly without installation):
- pandas
- numpy
- matplotlib
- scikit-learn
- seaborn
```

This helps the agent understand what tools are available without needing to install packages.

## Best Practices

1. **Use built-in runtimes when possible** - They're tested and optimized.

2. **Enable image caching** - Set `cache_image=True` (default) to avoid rebuilding images.

3. **Set appropriate idle timeouts** - Balance resource usage vs user experience.

4. **Always clean up** - Use `sandbox.stop()` or `manager.shutdown()` to release resources.

5. **Consider pre-warming** - For latency-sensitive apps, pre-create containers:
   ```python
   sandbox = DockerSandbox(runtime="python-datascience")
   sandbox.start()  # Start container immediately
   ```
