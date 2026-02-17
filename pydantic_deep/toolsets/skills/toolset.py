"""Skills toolset implementation.

This module provides the main `SkillsToolset` class that integrates skill
discovery and management with Pydantic AI agents.

The toolset provides four main tools for agents:

- list_skills: List all available skills
- load_skill: Load full instructions for a specific skill
- read_skill_resource: Read skill resource files or invoke callable resources
- run_skill_script: Execute skill scripts
"""

from __future__ import annotations

import json
import warnings
from collections.abc import Callable
from inspect import signature as get_signature
from pathlib import Path
from typing import Any

from pydantic_ai._griffe import doc_descriptions
from pydantic_ai._run_context import RunContext
from pydantic_ai.toolsets import FunctionToolset

from .backend import BackendSkillsDirectory
from .directory import SkillsDirectory
from .exceptions import SkillNotFoundError, SkillValidationError
from .types import (
    SKILL_NAME_PATTERN,
    Skill,
    SkillResource,
    SkillScript,
    SkillWrapper,
    normalize_skill_name,
)

# Default instruction template for skills system prompt
_INSTRUCTION_SKILLS_HEADER = """\
You have access to a collection of skills containing domain-specific knowledge \
and capabilities.
Each skill provides specialized instructions, resources, and scripts for \
specific tasks.

<available_skills>
{skills_list}
</available_skills>

When a task falls within a skill's domain:
1. Use `load_skill` to read the complete skill instructions
2. Follow the skill's guidance to complete the task
3. Use any additional skill resources and scripts as needed

Use progressive disclosure: load only what you need, when you need it."""

# Template used by load_skill
LOAD_SKILL_TEMPLATE = """<skill>
<name>{skill_name}</name>
<description>{description}</description>
<uri>{uri}</uri>

<resources>
{resources_list}
</resources>

<scripts>
{scripts_list}
</scripts>

<instructions>
{content}
</instructions>
</skill>
"""


class SkillsToolset(FunctionToolset):
    """Pydantic AI toolset for automatic skill discovery and integration.

    This is the primary interface for integrating skills with Pydantic AI agents.
    It manages skills directly and provides tools for skill interaction.

    Provides the following tools to agents:

    - list_skills(): List all available skills
    - load_skill(skill_name): Load a specific skill's instructions
    - read_skill_resource(skill_name, resource_name): Read a skill resource file
    - run_skill_script(skill_name, script_name, args): Execute a skill script

    Example:
        ```python
        from pydantic_ai import Agent
        from pydantic_deep.toolsets.skills import SkillsToolset

        agent = Agent(
            model='openai:gpt-4.1',
            instructions="You are a helpful assistant.",
            toolsets=[SkillsToolset(directories=["./skills"])]
        )

        # Programmatic skills
        from pydantic_deep.toolsets.skills import Skill

        custom_skill = Skill(
            name="my-skill",
            description="Custom skill",
            content="Instructions here",
        )
        agent = Agent(
            model='openai:gpt-4.1',
            toolsets=[SkillsToolset(skills=[custom_skill])]
        )
        ```
    """

    def __init__(
        self,
        *,
        skills: list[Skill] | None = None,
        directories: list[str | Path | SkillsDirectory | BackendSkillsDirectory] | None = None,
        validate: bool = True,
        max_depth: int | None = 3,
        id: str | None = None,
        instruction_template: str | None = None,
        exclude_tools: set[str] | list[str] | None = None,
    ) -> None:
        """Initialize the skills toolset.

        Args:
            skills: List of pre-loaded Skill objects. Can be combined with ``directories``.
            directories: List of directories or SkillsDirectory instances to discover
                skills from. Can be combined with ``skills``. If both are None,
                defaults to ``["./skills"]``.
            validate: Validate skill structure during discovery.
            max_depth: Maximum depth for skill discovery (None for unlimited).
            id: Unique identifier for this toolset.
            instruction_template: Custom instruction template for skills system prompt.
                Must include ``{skills_list}`` placeholder.
            exclude_tools: Set or list of tool names to exclude from registration
                (e.g., ``['run_skill_script']``).
        """
        super().__init__(id=id)

        self._instruction_template = instruction_template

        # Validate and initialize exclude_tools
        valid_tools = {
            "list_skills",
            "load_skill",
            "read_skill_resource",
            "run_skill_script",
        }
        self._exclude_tools: set[str] = set(exclude_tools or [])
        invalid = self._exclude_tools - valid_tools
        if invalid:
            raise ValueError(f"Unknown tools: {invalid}. Valid: {valid_tools}")

        if "load_skill" in self._exclude_tools:
            warnings.warn(
                "'load_skill' is a critical tool for skills usage and has been excluded. "
                "Agents will not be able to load skill instructions, which severely "
                "limits skill functionality.",
                UserWarning,
                stacklevel=2,
            )

        # Initialize the skills dict and directories list
        self._skills: dict[str, Skill] = {}
        self._skill_directories: list[SkillsDirectory | BackendSkillsDirectory] = []
        self._validate = validate
        self._max_depth = max_depth

        # Load programmatic skills first
        if skills is not None:
            for skill in skills:
                self._register_skill(skill)

        # Load directory-based skills
        if directories is not None:
            self._load_directory_skills(directories)
        elif skills is None:
            # Default: ./skills directory (only if no skills provided)
            default_dir = Path("./skills")
            if not default_dir.exists():
                warnings.warn(
                    f"Default skills directory '{default_dir}' does not exist. "
                    "No skills will be loaded.",
                    UserWarning,
                    stacklevel=2,
                )
            else:
                self._load_directory_skills([default_dir])  # pragma: no cover

        # Register tools
        self._register_tools()

    @property
    def skills(self) -> dict[str, Skill]:
        """Get the dictionary of loaded skills."""
        return self._skills

    def get_skill(self, name: str) -> Skill:
        """Get a specific skill by name.

        Args:
            name: Name of the skill to get.

        Returns:
            The requested Skill object.

        Raises:
            SkillNotFoundError: If skill is not found.
        """
        if name not in self._skills:
            available = ", ".join(sorted(self._skills.keys())) or "none"
            raise SkillNotFoundError(f"Skill '{name}' not found. Available: {available}")
        return self._skills[name]

    def _load_directory_skills(
        self, directories: list[str | Path | SkillsDirectory | BackendSkillsDirectory]
    ) -> None:
        """Load skills from configured directories."""
        for directory in directories:
            if isinstance(directory, (SkillsDirectory, BackendSkillsDirectory)):
                skill_dir = directory
            else:
                skill_dir = SkillsDirectory(
                    path=directory,
                    validate=self._validate,
                    max_depth=self._max_depth,
                )

            self._skill_directories.append(skill_dir)

            for skill in skill_dir.get_skills().values():
                skill_name = skill.name
                if skill_name in self._skills:
                    warnings.warn(
                        f"Duplicate skill '{skill_name}' found. Overriding previous occurrence.",
                        UserWarning,
                        stacklevel=3,
                    )
                self._skills[skill_name] = skill

    def _build_resource_xml(self, resource: SkillResource) -> str:
        """Build XML representation of a resource."""
        res_xml = f'<resource name="{resource.name}"'
        if resource.description:
            res_xml += f' description="{resource.description}"'
        if resource.function and resource.function_schema:
            params_json = json.dumps(resource.function_schema.json_schema)
            res_xml += f" parameters={json.dumps(params_json)}"
        res_xml += " />"
        return res_xml

    def _build_script_xml(self, script: SkillScript) -> str:
        """Build XML representation of a script."""
        scr_xml = f'<script name="{script.name}"'
        if script.description:
            scr_xml += f' description="{script.description}"'
        if script.function and script.function_schema:
            params_json = json.dumps(script.function_schema.json_schema)
            scr_xml += f" parameters={json.dumps(params_json)}"
        scr_xml += " />"
        return scr_xml

    def _find_skill_resource(self, skill: Skill, resource_name: str) -> SkillResource | None:
        """Find a resource in a skill by name."""
        if not skill.resources:
            return None
        for r in skill.resources:
            if r.name == resource_name:
                return r
        return None

    def _find_skill_script(self, skill: Skill, script_name: str) -> SkillScript | None:
        """Find a script in a skill by name."""
        if not skill.scripts:
            return None
        for s in skill.scripts:
            if s.name == script_name:
                return s
        return None

    def _register_tools(self) -> None:  # pragma: no branch
        """Register skill management tools with the toolset."""
        if "list_skills" not in self._exclude_tools:
            self._register_list_skills()
        if "load_skill" not in self._exclude_tools:
            self._register_load_skill()
        if "read_skill_resource" not in self._exclude_tools:
            self._register_read_skill_resource()
        if "run_skill_script" not in self._exclude_tools:
            self._register_run_skill_script()

    def _register_list_skills(self) -> None:
        """Register the list_skills tool."""

        @self.tool
        async def list_skills(
            _ctx: RunContext[Any],
        ) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            """Get an overview of all available skills and what they do.

            Use this when you need to discover what skills exist or refresh your
            knowledge of available capabilities.

            Returns:
                Dictionary mapping skill names to their descriptions.
                Empty dictionary if no skills are available.
            """
            return {name: skill.description for name, skill in self._skills.items()}

    def _register_load_skill(self) -> None:
        """Register the load_skill tool."""

        @self.tool
        async def load_skill(  # pyright: ignore[reportUnusedFunction]
            ctx: RunContext[Any],
            skill_name: str,
        ) -> str:
            """Load complete instructions and capabilities for a specific skill.

            A skill contains detailed instructions, supplementary resources, and
            executable scripts. Load a skill when you need to perform a task
            within its domain.

            Args:
                skill_name: Exact name from your available skills list.

            Returns:
                Structured documentation with instructions, resources, and scripts.

            Important:
            - Read the entire instructions section before taking action
            - Resource and script names are authoritative - use exact names
            - Do NOT infer or guess resource/script names
            """
            _ = ctx
            if skill_name not in self._skills:
                available = ", ".join(sorted(self._skills.keys())) or "none"
                return f"Error: Skill '{skill_name}' not found. Available: {available}"

            skill = self._skills[skill_name]

            # Build resources list
            resources_parts: list[str] = []
            if skill.resources:
                for res in skill.resources:
                    resources_parts.append(self._build_resource_xml(res))
            resources_list = (
                "\n".join(resources_parts) if resources_parts else "<!-- No resources -->"
            )

            # Build scripts list
            scripts_parts: list[str] = []
            if skill.scripts:
                for scr in skill.scripts:
                    scripts_parts.append(self._build_script_xml(scr))
            scripts_list = "\n".join(scripts_parts) if scripts_parts else "<!-- No scripts -->"

            return LOAD_SKILL_TEMPLATE.format(
                skill_name=skill.name,
                description=skill.description,
                uri=skill.uri or "N/A",
                resources_list=resources_list,
                scripts_list=scripts_list,
                content=skill.content,
            )

    def _register_read_skill_resource(self) -> None:
        """Register the read_skill_resource tool."""

        @self.tool
        async def read_skill_resource(  # pyright: ignore[reportUnusedFunction]
            ctx: RunContext[Any],
            skill_name: str,
            resource_name: str,
            args: dict[str, Any] | None = None,
        ) -> str:
            """Access supplementary documentation, templates, or data from a skill.

            Resources are additional files that support skill execution. They can be
            static content (markdown docs, templates) or dynamic callables (functions
            that generate content based on parameters).

            Args:
                skill_name: Name of the skill containing the resource.
                resource_name: Exact name of the resource as listed in the skill.
                args: Arguments for callable resources (optional for static files).

            Returns:
                The resource content as a string.
            """
            if skill_name not in self._skills:
                return f"Error: Skill '{skill_name}' not found."

            skill = self._skills[skill_name]
            resource = self._find_skill_resource(skill, resource_name)

            if resource is None:
                available = [r.name for r in skill.resources] if skill.resources else []
                return (
                    f"Error: Resource '{resource_name}' not found in skill '{skill_name}'. "
                    f"Available: {available}"
                )

            return str(await resource.load(ctx=ctx, args=args))

    def _register_run_skill_script(self) -> None:
        """Register the run_skill_script tool."""

        @self.tool
        async def run_skill_script(  # pyright: ignore[reportUnusedFunction]
            ctx: RunContext[Any],
            skill_name: str,
            script_name: str,
            args: dict[str, Any] | None = None,
        ) -> str:
            """Execute a skill script that performs actions or computations.

            Scripts are executable programs provided by skills that can perform
            actions, process data, or generate outputs.

            Args:
                skill_name: Name of the skill containing the script.
                script_name: Exact name of the script as listed in the skill.
                args: Arguments required by the script.

            Returns:
                Script execution output including stdout and stderr.
            """
            if skill_name not in self._skills:
                return f"Error: Skill '{skill_name}' not found."

            skill = self._skills[skill_name]
            script = self._find_skill_script(skill, script_name)

            if script is None:
                available = [s.name for s in skill.scripts] if skill.scripts else []
                return (
                    f"Error: Script '{script_name}' not found in skill '{skill_name}'. "
                    f"Available: {available}"
                )

            return str(await script.run(ctx=ctx, args=args))

    async def get_instructions(self, ctx: RunContext[Any]) -> str | None:
        """Return instructions to inject into the agent's system prompt.

        Args:
            ctx: The run context for this agent run.

        Returns:
            The skills system prompt, or None if no skills are loaded.
        """
        if not self._skills:
            return None

        # Build skills list in XML format
        skills_list_lines: list[str] = []
        for skill in sorted(self._skills.values(), key=lambda s: s.name):
            skills_list_lines.append("<skill>")
            skills_list_lines.append(f"<name>{skill.name}</name>")
            skills_list_lines.append(f"<description>{skill.description}</description>")
            if skill.uri:
                skills_list_lines.append(f"<uri>{skill.uri}</uri>")
            skills_list_lines.append("</skill>")
        skills_list = "\n".join(skills_list_lines)

        if self._instruction_template:
            return self._instruction_template.format(skills_list=skills_list)

        return _INSTRUCTION_SKILLS_HEADER.format(skills_list=skills_list)

    def skill(
        self,
        func: Callable[[], str] | None = None,
        *,
        name: str | None = None,
        description: str | None = None,
        license: str | None = None,
        compatibility: str | None = None,
        metadata: dict[str, Any] | None = None,
        resources: list[SkillResource] | None = None,
        scripts: list[SkillScript] | None = None,
    ) -> Any:
        """Decorator to define a skill using a function.

        The decorated function should return a string containing the skill's
        instructions/content. The skill name is derived from the function name
        unless explicitly provided.

        Example:
            ```python
            from pydantic_ai import RunContext
            from pydantic_deep.toolsets.skills import SkillsToolset

            skills = SkillsToolset()

            @skills.skill(metadata={'version': '1.0'})
            def data_analyzer() -> str:
                '''Analyze data from various sources.'''
                return 'Use this skill for data analysis tasks.'

            @data_analyzer.resource
            async def get_schema(ctx: RunContext[MyDeps]) -> str:
                return await ctx.deps.database.get_schema()
            ```

        Args:
            func: The function that returns skill content (must return str).
            name: Skill name (defaults to normalized function name).
            description: Skill description (inferred from docstring if not provided).
            license: Optional license information.
            compatibility: Optional environment requirements.
            metadata: Additional metadata fields as a dictionary.
            resources: Initial list of resources to attach to the skill.
            scripts: Initial list of scripts to attach to the skill.

        Returns:
            A SkillWrapper instance that can be used to attach resources and scripts.
        """

        def decorator(f: Callable[[], str]) -> SkillWrapper[Any]:
            if name is not None:
                skill_name = name
                if not SKILL_NAME_PATTERN.match(skill_name):
                    raise SkillValidationError(
                        f"Skill name '{skill_name}' is invalid. "
                        "Skill names must contain only lowercase letters, numbers, "
                        "and hyphens (no consecutive hyphens)."
                    )
                if len(skill_name) > 64:
                    raise SkillValidationError(
                        f"Skill name '{skill_name}' exceeds 64 characters "
                        f"({len(skill_name)} chars)."
                    )
            else:
                skill_name = normalize_skill_name(f.__name__)

            # Extract description from docstring if not provided
            skill_description = description
            if skill_description is None:
                sig = get_signature(f)
                desc, _ = doc_descriptions(f, sig, docstring_format="auto")
                skill_description = desc

            wrapper: SkillWrapper[Any] = SkillWrapper(
                function=f,
                name=skill_name,
                description=skill_description,
                license=license,
                compatibility=compatibility,
                metadata=metadata,
                resources=list(resources) if resources else [],
                scripts=list(scripts) if scripts else [],
            )

            # Register the skill immediately
            self._register_skill(wrapper)

            return wrapper

        if func is None:
            return decorator
        else:
            return decorator(func)

    def _register_skill(self, skill: Skill | SkillWrapper[Any]) -> None:
        """Register a skill with the toolset.

        Converts SkillWrapper instances to Skill dataclasses before registering.

        Args:
            skill: Skill or SkillWrapper instance to register.
        """
        if isinstance(skill, SkillWrapper):
            skill = skill.to_skill()

        if skill.name in self._skills:
            warnings.warn(
                f"Duplicate skill '{skill.name}' found. Overriding previous occurrence.",
                UserWarning,
                stacklevel=3,
            )

        self._skills[skill.name] = skill
