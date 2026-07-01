"""Backend-aware skill resources, scripts, and discovery.

This module provides backend-integrated implementations that parallel
the local filesystem implementations in `local.py`:

- `BackendSkillResource`: Load resources via `BackendProtocol.read_bytes()`
- `BackendSkillScriptExecutor`: Execute scripts via `SandboxProtocol.execute()`
- `BackendSkillScript`: File-based script delegating to backend executor
- `BackendSkillsDirectory`: Discover skills from a backend filesystem
- Factory functions for creating backend-based resources and scripts
"""

from __future__ import annotations

import json
import posixpath
import shlex
import warnings
from dataclasses import dataclass, field
from typing import Any, cast

from pydantic_ai_backends import (
    AsyncBackendProtocol,
    AsyncSandboxProtocol,
    BackendProtocol,
    SandboxProtocol,
    ensure_async,
)
from pydantic_ai_backends.types import ExecuteResponse

from .directory import _extract_skill_fields, _parse_skill_md
from .exceptions import (
    SkillResourceLoadError,
    SkillScriptExecutionError,
    SkillValidationError,
)
from .types import SKILL_RESOURCE_EXTENSIONS, Skill, SkillResource, SkillScript

try:
    import yaml

    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


@dataclass
class BackendSkillResource(SkillResource):
    """A backend-based skill resource that loads content via BackendProtocol.

    The uri attribute points to the file path within the backend's filesystem.
    JSON and YAML files are automatically parsed when loaded.

    Attributes:
        backend: Backend instance used for reading the resource.
    """

    backend: AsyncBackendProtocol = field(default=None, repr=False)  # pyright: ignore[reportAssignmentType]

    async def load(self, ctx: Any, args: dict[str, Any] | None = None) -> Any:
        """Load resource content from the backend.

        JSON and YAML files are parsed; falls back to text if parsing fails.
        Other file types are returned as UTF-8 text.

        Args:
            ctx: RunContext for accessing dependencies (unused, backend captured at creation).
            args: Named arguments (unused for file-based resources).

        Returns:
            Parsed dict (JSON/YAML) or UTF-8 text string.

        Raises:
            SkillResourceLoadError: If file cannot be read from the backend.
        """
        if not self.uri:
            raise SkillResourceLoadError(f"Resource '{self.name}' has no URI")

        if self.backend is None:
            raise SkillResourceLoadError(f"Resource '{self.name}' has no backend configured")

        try:
            content_bytes = await self.backend.read_bytes(self.uri)
            content = content_bytes.decode("utf-8")
        except Exception as e:
            raise SkillResourceLoadError(
                f"Failed to read resource '{self.name}' from backend: {e}"
            ) from e

        # Auto-parse based on file extension
        suffix = self.name.rsplit(".", 1)[-1].lower() if "." in self.name else ""

        if suffix == "json":
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return content

        if suffix in ("yaml", "yml"):
            if _HAS_YAML:
                try:
                    return yaml.safe_load(content)
                except yaml.YAMLError:
                    return content
            return content

        return content


class BackendSkillScriptExecutor:
    """Execute skill scripts via SandboxProtocol.execute().

    Uses the backend's execute() method to run scripts inside the backend
    environment (e.g., Docker container, local sandbox).

    Attributes:
        timeout: Execution timeout in seconds.
    """

    def __init__(
        self,
        backend: AsyncSandboxProtocol,
        timeout: int = 30,
    ) -> None:
        """Initialize the backend script executor.

        Args:
            backend: Async sandbox backend with execute() support.
            timeout: Execution timeout in seconds (default: 30).
        """
        self._backend = backend
        self.timeout = timeout

    async def run(
        self,
        script: SkillScript,
        args: dict[str, Any] | None = None,
    ) -> Any:
        """Run a skill script via backend.execute().

        Args:
            script: The script to run.
            args: Named arguments as a dictionary.
                Boolean True emits flag only, False/None omits it,
                lists repeat the flag for each item, other types convert to string.

        Returns:
            Script output from the backend.

        Raises:
            SkillScriptExecutionError: If execution fails.
        """
        if script.uri is None:
            raise SkillScriptExecutionError(
                f"Script '{script.name}' has no URI for backend execution"
            )

        cmd_parts = ["python", shlex.quote(script.uri)]

        if args:
            for key, value in args.items():
                if isinstance(value, bool):
                    if value:
                        cmd_parts.append(f"--{key}")
                elif isinstance(value, list):
                    for item in value:
                        cmd_parts.append(f"--{key}")
                        cmd_parts.append(shlex.quote(str(item)))
                elif value is not None:
                    cmd_parts.append(f"--{key}")
                    cmd_parts.append(shlex.quote(str(value)))

        command = " ".join(cmd_parts)

        try:
            result: ExecuteResponse = await self._backend.execute(command, self.timeout)
        except Exception as e:
            raise SkillScriptExecutionError(
                f"Failed to execute script '{script.name}' via backend: {e}"
            ) from e

        output = result.output

        if result.exit_code is not None and result.exit_code != 0:
            output += f"\n\nScript exited with code {result.exit_code}"

        if result.truncated:
            output += "\n\n(output was truncated)"

        return output.strip() or "(no output)"


@dataclass
class BackendSkillScript(SkillScript):
    """A backend-based skill script that executes via SandboxProtocol.

    The uri attribute points to the Python script file within the backend.

    Attributes:
        executor: Backend executor for running the script.
    """

    executor: BackendSkillScriptExecutor = None  # type: ignore[assignment]

    async def run(self, ctx: Any, args: dict[str, Any] | None = None) -> Any:
        """Execute script via backend.

        Args:
            ctx: RunContext for accessing dependencies (unused, backend captured at creation).
            args: Named arguments passed to the script.

        Returns:
            Script execution output.

        Raises:
            SkillScriptExecutionError: If execution fails.
        """
        if not self.uri:
            raise SkillScriptExecutionError(f"Script '{self.name}' has no URI")

        if self.executor is None:
            raise SkillScriptExecutionError(
                f"Script '{self.name}' has no backend executor configured"
            )

        return await self.executor.run(self, args)


def create_backend_resource(
    name: str,
    uri: str,
    backend: AsyncBackendProtocol,
    description: str | None = None,
) -> BackendSkillResource:
    """Create a backend-based resource.

    Args:
        name: Resource name (e.g., "FORMS.md", "data.json").
        uri: Path to the resource file within the backend.
        backend: Async backend instance for reading the resource.
        description: Optional resource description.

    Returns:
        BackendSkillResource instance.
    """
    return BackendSkillResource(
        name=name,
        uri=uri,
        backend=backend,
        description=description,
    )


def create_backend_script(
    name: str,
    uri: str,
    skill_name: str,
    executor: BackendSkillScriptExecutor,
    description: str | None = None,
) -> BackendSkillScript:
    """Create a backend-based script.

    Args:
        name: Script name (includes .py extension).
        uri: Path to the script file within the backend.
        skill_name: Name of the parent skill.
        executor: Backend executor for running the script.
        description: Optional script description.

    Returns:
        BackendSkillScript instance.
    """
    return BackendSkillScript(
        name=name,
        uri=uri,
        skill_name=skill_name,
        description=description,
        executor=executor,
    )


def _get_skill_dir(skill_file_path: str) -> str:
    """Extract skill directory from a SKILL.md file path.

    Args:
        skill_file_path: Full path to SKILL.md (e.g., "/skills/my-skill/SKILL.md").

    Returns:
        Directory path (e.g., "/skills/my-skill").
    """
    parts = skill_file_path.rsplit("/", 1)
    return parts[0] if len(parts) > 1 else "/"


def _get_relative_path(file_path: str, base_dir: str) -> str:
    """Get path relative to base directory.

    Args:
        file_path: Full file path.
        base_dir: Base directory to make path relative to.

    Returns:
        Relative path string.
    """
    if file_path == base_dir:
        return file_path.rsplit("/", 1)[-1]
    prefix = base_dir.rstrip("/") + "/"
    if file_path.startswith(prefix):
        rel = file_path[len(prefix) :].lstrip("/")
        return rel if rel else file_path.rsplit("/", 1)[-1]
    return file_path.rsplit("/", 1)[-1]


def _is_within(file_path: str, base_dir: str) -> bool:
    """Logical containment check: is `file_path` inside `base_dir`?

    Mirrors (at the logical-path level) the symlink-escape guard the filesystem
    discovery enforces, so a discovered resource/script that resolves outside the
    skill directory is rejected rather than read/executed (B2). `..` segments are
    normalised away first.
    """
    base = posixpath.normpath(base_dir)
    target = posixpath.normpath(file_path)
    return target == base or target.startswith(base.rstrip("/") + "/")


def _discover_backend_resources(
    sync_backend: BackendProtocol,
    async_backend: AsyncBackendProtocol,
    skill_dir: str,
) -> list[BackendSkillResource]:
    """Discover resource files in a skill directory via backend.

    Args:
        sync_backend: Raw sync backend used for ``glob_info`` discovery.
        async_backend: Async-wrapped backend stored on resources for ``read_bytes`` at load time.
        skill_dir: Skill directory path in the backend.

    Returns:
        List of discovered BackendSkillResource objects.
    """
    resources: list[BackendSkillResource] = []

    for ext in sorted(SKILL_RESOURCE_EXTENSIONS):
        try:
            matches = sync_backend.glob_info(f"**/*{ext}", skill_dir)
        except Exception:
            continue

        for file_info in matches:
            name_upper = file_info["name"].upper()
            if name_upper == "SKILL.MD":
                continue
            if not _is_within(file_info["path"], skill_dir):
                warnings.warn(
                    f"Resource '{file_info['path']}' resolves outside skill directory "
                    f"'{skill_dir}'. Skipping.",
                    UserWarning,
                    stacklevel=2,
                )
                continue

            rel_path = _get_relative_path(file_info["path"], skill_dir)
            resources.append(
                create_backend_resource(
                    name=rel_path,
                    uri=file_info["path"],
                    backend=async_backend,
                )
            )

    return resources


def _discover_backend_scripts(
    backend: SandboxProtocol,
    skill_dir: str,
    skill_name: str,
    executor: BackendSkillScriptExecutor,
) -> list[BackendSkillScript]:
    """Discover executable scripts in a skill directory via backend.

    Looks for Python scripts in the root and scripts/ subdirectory.

    Args:
        backend: Sandbox backend with execute() support.
        skill_dir: Skill directory path in the backend.
        skill_name: Name of the parent skill.
        executor: Backend executor for running discovered scripts.

    Returns:
        List of discovered BackendSkillScript objects.
    """
    scripts: list[BackendSkillScript] = []
    seen_paths: set[str] = set()

    for pattern in ["*.py", "scripts/*.py"]:
        try:
            matches = backend.glob_info(pattern, skill_dir)
        except Exception:
            continue

        for file_info in matches:
            if file_info["name"] == "__init__.py":
                continue

            if file_info["path"] in seen_paths:
                continue
            seen_paths.add(file_info["path"])
            if not _is_within(file_info["path"], skill_dir):
                warnings.warn(
                    f"Script '{file_info['path']}' resolves outside skill directory "
                    f"'{skill_dir}'. Skipping.",
                    UserWarning,
                    stacklevel=2,
                )
                continue

            rel_path = _get_relative_path(file_info["path"], skill_dir)
            scripts.append(
                create_backend_script(
                    name=rel_path,
                    uri=file_info["path"],
                    skill_name=skill_name,
                    executor=executor,
                )
            )

    return scripts


class BackendSkillsDirectory:
    """Discover and load skills from a backend filesystem.

    Uses `BackendProtocol` methods (`glob_info`, `read_bytes`) for
    skill discovery and resource loading. Script execution requires
    `SandboxProtocol` (with `execute()`).

    Example:
        ```python
        from pydantic_ai_backends import StateBackend
        from pydantic_deep.features.skills import BackendSkillsDirectory, SkillsToolset

        backend = StateBackend()
        # Write skill files to backend...
        backend.write("/skills/my-skill/SKILL.md", skill_content)

        # Discover skills from backend
        directory = BackendSkillsDirectory(backend=backend, path="/skills")
        toolset = SkillsToolset(directories=[directory])
        ```
    """

    def __init__(
        self,
        *,
        backend: BackendProtocol,
        path: str = "/skills",
        validate: bool = True,
        max_depth: int | None = 3,
        script_timeout: int = 30,
    ) -> None:
        """Initialize the backend skills directory.

        Args:
            backend: Backend to discover skills from.
            path: Base path to search for skills within the backend.
            validate: Validate skill structure on discovery.
            max_depth: Maximum depth for skill discovery (None for unlimited).
            script_timeout: Timeout for script execution in seconds.
        """
        # Unwrap adapter if needed — discovery calls sync backend methods
        # directly because __init__ cannot be async. Imported lazily to avoid a
        # deps -> types -> skills -> deps import cycle.
        from pydantic_deep.deps import unwrap_backend

        raw = unwrap_backend(backend)
        self._backend = raw
        self._path = path
        self._validate = validate
        self._max_depth = max_depth
        self._script_timeout = script_timeout

        # Discover skills from backend (sync — raw backend is always sync)
        self._skills: dict[str, Skill] = self.get_skills()

    def get_skills(self) -> dict[str, Skill]:
        """Discover and load all skills from the backend."""
        skills: dict[str, Skill] = {}

        # Find all SKILL.md files
        try:
            if self._max_depth is not None:
                skill_files = []
                for depth in range(self._max_depth + 1):
                    pattern = "SKILL.md" if depth == 0 else "/".join(["*"] * depth) + "/SKILL.md"
                    skill_files.extend(self._backend.glob_info(pattern, self._path))
            else:
                skill_files = self._backend.glob_info("**/SKILL.md", self._path)
        except Exception:
            return skills

        # Deduplicate by path
        seen_paths: set[str] = set()
        unique_files = []
        for f in skill_files:
            if f["path"] not in seen_paths:
                seen_paths.add(f["path"])
                unique_files.append(f)

        for skill_file in unique_files:
            try:
                skill = self._load_skill_from_file(skill_file["path"])
                if skill is not None:
                    skills[skill.name] = skill
            except SkillValidationError:
                if self._validate:
                    raise
                warnings.warn(
                    f"Skipping invalid skill at {skill_file['path']}",
                    UserWarning,
                    stacklevel=2,
                )
            except Exception as e:
                raise SkillValidationError(
                    f"Failed to load skill from {skill_file['path']}: {e}"
                ) from e

        return skills

    def _load_skill_from_file(self, skill_file_path: str) -> Skill | None:
        """Load a single skill from a SKILL.md file in the backend.

        Args:
            skill_file_path: Path to the SKILL.md file within the backend.

        Returns:
            Loaded Skill object, or None if skill should be skipped.
        """
        content_bytes = self._backend.read_bytes(skill_file_path)
        content = content_bytes.decode("utf-8")

        frontmatter, instructions = _parse_skill_md(content)
        skill_dir = _get_skill_dir(skill_file_path)

        fields = _extract_skill_fields(
            frontmatter,
            instructions,
            validate=self._validate,
            name_fallback=skill_dir.rsplit("/", 1)[-1],
            skill_file_label=skill_file_path,
            stacklevel=3,
        )
        if fields is None:
            return None

        # Discover resources — sync backend for glob_info, async for resource loading
        async_backend = ensure_async(self._backend)
        resources = _discover_backend_resources(self._backend, async_backend, skill_dir)

        # Discover scripts (only if backend supports execution)
        scripts: list[BackendSkillScript] = []
        if isinstance(self._backend, SandboxProtocol):
            executor = BackendSkillScriptExecutor(
                backend=cast("AsyncSandboxProtocol", async_backend),
                timeout=self._script_timeout,
            )
            scripts = _discover_backend_scripts(self._backend, skill_dir, fields["name"], executor)

        return Skill(
            **fields,
            uri=skill_dir,
            resources=resources,  # type: ignore[arg-type]
            scripts=scripts,  # type: ignore[arg-type]
        )

    @property
    def skills(self) -> dict[str, Skill]:
        """Get the dictionary of loaded skills."""
        return self._skills
