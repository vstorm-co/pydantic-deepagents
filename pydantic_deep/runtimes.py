"""Built-in runtime configurations for DockerSandbox.

This module provides pre-configured runtime environments that can be used
with DockerSandbox to provide ready-to-use environments without manual
package installation.

Example:
    ```python
    from pydantic_deep import DockerSandbox
    from pydantic_deep.runtimes import BUILTIN_RUNTIMES

    # Use a built-in runtime
    sandbox = DockerSandbox(runtime=BUILTIN_RUNTIMES["python-datascience"])

    # Or use by name (string)
    sandbox = DockerSandbox(runtime="python-datascience")
    ```
"""

from __future__ import annotations

from pydantic_deep.types import RuntimeConfig

BUILTIN_RUNTIMES: dict[str, RuntimeConfig] = {
    "python-minimal": RuntimeConfig(
        name="python-minimal",
        description="Python 3.12 - clean, no extra packages",
        image="python:3.12-slim",
    ),
    "python-datascience": RuntimeConfig(
        name="python-datascience",
        description="Python with pandas, numpy, matplotlib, scikit-learn, seaborn",
        base_image="python:3.12-slim",
        packages=["pandas", "numpy", "matplotlib", "scikit-learn", "seaborn"],
    ),
    "python-web": RuntimeConfig(
        name="python-web",
        description="Python with FastAPI, SQLAlchemy, httpx",
        base_image="python:3.12-slim",
        packages=["fastapi", "uvicorn", "sqlalchemy", "httpx"],
    ),
    "node-minimal": RuntimeConfig(
        name="node-minimal",
        description="Node.js 20 - clean, no extra packages",
        image="node:20-slim",
        work_dir="/app",
    ),
    "node-react": RuntimeConfig(
        name="node-react",
        description="Node.js 20 with TypeScript, Vite, React",
        base_image="node:20-slim",
        packages=["typescript", "vite", "react", "react-dom", "@types/react"],
        package_manager="npm",
        work_dir="/app",
    ),
}


def get_runtime(name: str) -> RuntimeConfig:
    """Get a built-in runtime by name.

    Args:
        name: Name of the runtime (e.g., "python-datascience").

    Returns:
        The RuntimeConfig for the requested runtime.

    Raises:
        KeyError: If the runtime name is not found.
    """
    if name not in BUILTIN_RUNTIMES:
        available = ", ".join(BUILTIN_RUNTIMES.keys())
        raise KeyError(f"Unknown runtime '{name}'. Available: {available}")
    return BUILTIN_RUNTIMES[name]
