"""Skills that live in the run's workspace.

`skill_directories` reads skills from the machine the agent is built on. A
skill can also live where the agent works - a `skills/` folder inside its
Docker container, its sandbox session, its state document - and that is only
reachable once a run has a workspace. `WorkspaceSkillsDirectory` names such a
folder; `SkillsToolset` discovers it through `ctx.workspace` on first use in
each workspace.

- `WorkspaceSkillResource`: a resource file, read through the run's workspace
- `WorkspaceSkillScript`: a Python script, run in the run's workspace
- `WorkspaceSkillsDirectory`: where to look, and how to discover what is there
"""

from __future__ import annotations

import json
import posixpath
import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic_ai.workspaces import SupportsCommands

from .directory import _extract_skill_fields, _parse_skill_md
from .exceptions import SkillResourceLoadError, SkillScriptExecutionError, SkillValidationError
from .types import SKILL_RESOURCE_EXTENSIONS, Skill, SkillResource, SkillScript

if TYPE_CHECKING:
    from pydantic_ai.workspaces import FileEntry, Workspace

try:
    import yaml

    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

SKILL_FILE = "SKILL.md"


@dataclass
class WorkspaceSkillResource(SkillResource):
    """A skill resource read through the run's workspace.

    The `uri` is the file's path in the workspace. JSON and YAML files are
    parsed when loaded.
    """

    async def load(self, ctx: Any, args: dict[str, Any] | None = None) -> Any:
        """Load the resource from `ctx.workspace`.

        JSON and YAML files are parsed; falls back to text if parsing fails.
        Other file types are returned as UTF-8 text.

        Args:
            ctx: The run context whose workspace holds the file.
            args: Named arguments (unused for file-based resources).

        Returns:
            Parsed dict (JSON/YAML) or UTF-8 text string.

        Raises:
            SkillResourceLoadError: If the file cannot be read.
        """
        if not self.uri:
            raise SkillResourceLoadError(f"Resource '{self.name}' has no URI")
        try:
            content = (await ctx.workspace.read_bytes(self.uri)).decode("utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise SkillResourceLoadError(
                f"Failed to read resource '{self.name}' from the workspace: {e}"
            ) from e

        suffix = self.name.rsplit(".", 1)[-1].lower() if "." in self.name else ""
        if suffix == "json":
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return content
        if suffix in ("yaml", "yml") and _HAS_YAML:
            try:
                return yaml.safe_load(content)
            except yaml.YAMLError:
                return content
        return content


@dataclass
class WorkspaceSkillScript(SkillScript):
    """A skill's Python script, run in the run's workspace.

    The `uri` is the script's path in the workspace.

    Attributes:
        timeout: Seconds the script may run.
    """

    timeout: int = 30

    async def run(self, ctx: Any, args: dict[str, Any] | None = None) -> Any:
        """Run the script with `python` in `ctx.workspace`.

        Args:
            ctx: The run context whose workspace runs the script.
            args: Named arguments. `True` emits the flag alone, `False`/`None`
                omit it, a list repeats the flag per item, and any other value
                is passed as text.

        Returns:
            The script's output, with its exit code when that is not zero.

        Raises:
            SkillScriptExecutionError: If the script cannot be run.
        """
        if not self.uri:
            raise SkillScriptExecutionError(f"Script '{self.name}' has no URI")
        try:
            result = await ctx.workspace.run(
                ["python", self.uri, *_script_arguments(args)], timeout=self.timeout
            )
        except OSError as e:
            raise SkillScriptExecutionError(
                f"Failed to run script '{self.name}' in the workspace: {e}"
            ) from e
        output = result.stdout + result.stderr
        if result.exit_code != 0:
            output += f"\n\nScript exited with code {result.exit_code}"
        return output.strip() or "(no output)"


def _script_arguments(args: dict[str, Any] | None) -> list[str]:
    """`args` as command-line flags, in argv form so nothing needs quoting."""
    argv: list[str] = []
    for key, value in (args or {}).items():
        if isinstance(value, bool):
            if value:
                argv.append(f"--{key}")
        elif isinstance(value, list):
            for item in value:
                argv.extend([f"--{key}", str(item)])
        elif value is not None:
            argv.extend([f"--{key}", str(value)])
    return argv


class WorkspaceSkillsDirectory:
    """A folder of skills in the run's workspace, discovered on first use.

    Example:
        ```python
        from pydantic_deep import create_deep_agent
        from pydantic_deep.features.skills import WorkspaceSkillsDirectory

        agent = create_deep_agent(
            skill_directories=[WorkspaceSkillsDirectory(path="skills")],
        )
        ```
    """

    def __init__(
        self,
        *,
        path: str = "skills",
        validate: bool = True,
        max_depth: int | None = 3,
        script_timeout: int = 30,
    ) -> None:
        """Name the folder to discover skills from.

        Args:
            path: Folder in the workspace, relative to its working directory.
            validate: Raise on an invalid skill rather than skip it with a warning.
            max_depth: How deep below `path` a `SKILL.md` may sit (`None` for any depth).
            script_timeout: Seconds a skill's script may run.
        """
        self.path = path
        self._validate = validate
        self._max_depth = max_depth
        self._script_timeout = script_timeout

    async def discover(self, workspace: Workspace) -> dict[str, Skill]:
        """Every skill under `path` in `workspace`, by name.

        A folder that does not exist holds no skills. A workspace that cannot
        answer raises.
        """
        skills: dict[str, Skill] = {}
        for skill_file in await self._skill_files(workspace, self.path, depth=0):
            try:
                skill = await self._load_skill(workspace, skill_file)
            except SkillValidationError:
                if self._validate:
                    raise
                warnings.warn(f"Skipping invalid skill at {skill_file}", UserWarning, stacklevel=2)
                continue
            if skill is not None:
                skills[skill.name] = skill
        return skills

    async def _skill_files(self, workspace: Workspace, folder: str, *, depth: int) -> list[str]:
        """The `SKILL.md` paths at or below `folder`, within `max_depth`."""
        entries = await _entries(workspace, folder)
        found = [entry.path for entry in entries if not entry.is_dir and entry.name == SKILL_FILE]
        if self._max_depth is None or depth < self._max_depth:
            for entry in entries:
                if entry.is_dir:
                    found.extend(await self._skill_files(workspace, entry.path, depth=depth + 1))
        return found

    async def _load_skill(self, workspace: Workspace, skill_file: str) -> Skill | None:
        try:
            content = (await workspace.read_bytes(skill_file)).decode("utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise SkillValidationError(f"Failed to load skill from {skill_file}: {e}") from e
        frontmatter, instructions = _parse_skill_md(content)
        skill_dir = posixpath.dirname(skill_file)
        fields = _extract_skill_fields(
            frontmatter,
            instructions,
            validate=self._validate,
            name_fallback=posixpath.basename(skill_dir),
            skill_file_label=skill_file,
            stacklevel=4,
        )
        if fields is None:
            return None
        files = await _files_under(workspace, skill_dir)
        # A workspace that runs no commands cannot run a script - and reports
        # trying as misuse, not as a failed script - so it offers none.
        runs_scripts = isinstance(workspace.backend, SupportsCommands)
        scripts = (
            _scripts(files, skill_dir, fields["name"], self._script_timeout) if runs_scripts else []
        )
        return Skill(
            **fields,
            uri=skill_dir,
            resources=_resources(files, skill_dir),  # type: ignore[arg-type]
            scripts=scripts,  # type: ignore[arg-type]
        )


async def _entries(workspace: Workspace, folder: str) -> tuple[FileEntry, ...]:
    """`folder`'s entries, or none when it is not a folder that can be listed."""
    try:
        return tuple(await workspace.list_dir(folder))
    except (FileNotFoundError, NotADirectoryError):
        return ()


async def _files_under(workspace: Workspace, folder: str) -> list[str]:
    """Every file path below `folder`."""
    files: list[str] = []
    for entry in await _entries(workspace, folder):
        if entry.is_dir:
            files.extend(await _files_under(workspace, entry.path))
        else:
            files.append(entry.path)
    return sorted(files)


def _relative(path: str, skill_dir: str) -> str:
    return posixpath.relpath(path, skill_dir)


def _resources(files: list[str], skill_dir: str) -> list[WorkspaceSkillResource]:
    return [
        WorkspaceSkillResource(name=_relative(path, skill_dir), uri=path)
        for path in files
        if posixpath.basename(path).upper() != SKILL_FILE.upper()
        and any(path.endswith(ext) for ext in SKILL_RESOURCE_EXTENSIONS)
    ]


def _scripts(
    files: list[str], skill_dir: str, skill_name: str, timeout: int
) -> list[WorkspaceSkillScript]:
    """The skill's Python scripts: in its folder, or in its `scripts/` subfolder."""
    return [
        WorkspaceSkillScript(
            name=_relative(path, skill_dir), uri=path, skill_name=skill_name, timeout=timeout
        )
        for path in files
        if path.endswith(".py")
        and posixpath.basename(path) != "__init__.py"
        and posixpath.dirname(_relative(path, skill_dir)) in ("", "scripts")
    ]
