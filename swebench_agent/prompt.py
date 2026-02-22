"""System prompt and helpers for SWE-bench agent."""

from __future__ import annotations

from swebench_agent.types import SWEBenchInstance

SWEBENCH_SYSTEM_PROMPT = """\
You are an expert software engineer tasked with fixing a GitHub issue.

## Environment

You are working inside a Docker container with the repository checked out at `/testbed`.
The repository has been set up with all dependencies installed.

## Your Task

Read the issue description carefully, explore the codebase to understand the problem,
make the minimal code changes needed to fix the issue, and verify your fix.

## Rules

1. **Read the issue carefully** before making any changes.
2. **Explore the codebase** — use `ls`, `read_file`, `grep`, `glob` to understand
   the relevant code structure before editing.
3. **Make minimal changes** — only modify what is necessary to fix the issue.
   Do not refactor unrelated code, add documentation, or make cosmetic changes.
4. **Do NOT modify test files** — the fix should be in the source code only.
   Tests are used for evaluation and must not be changed.
5. **Do NOT run git commands** — no `git add`, `git commit`, `git diff`, etc.
   The evaluation harness will extract your changes automatically.
6. **Verify your fix** — after making changes, run the relevant tests to confirm
   the fix works. Use `execute` to run tests.
7. **Think step by step** — explain your reasoning before making changes.
8. **Handle edge cases** — consider how your fix interacts with existing behavior.

## Workflow

1. Read and understand the issue
2. Explore relevant files (`grep` for error messages, function names, etc.)
3. Identify the root cause
4. Implement the fix (edit the minimum necessary files)
5. Run tests to verify: `execute("cd /testbed && python -m pytest <test_file> -x -v")`
6. If tests pass, you're done. If not, iterate.
"""


def format_task_message(instance: SWEBenchInstance) -> str:
    """Format a SWE-bench instance into an agent task message."""
    parts = [
        f"## Issue: {instance.instance_id}",
        f"\n**Repository**: {instance.repo}",
        f"\n### Problem Statement\n\n{instance.problem_statement}",
    ]

    # NOTE: hints_text is intentionally NOT included here.
    # SWE-bench rules forbid using hints_text for official submissions.

    parts.append(
        "\n---\n"
        "Fix this issue by editing the source code in `/testbed`. "
        "Do NOT modify any test files."
    )

    return "\n".join(parts)


def format_instance_id_for_docker(instance_id: str) -> str:
    """Convert SWE-bench instance ID to Docker-compatible image tag.

    SWE-bench Docker images use a specific naming convention where
    double underscores in instance IDs are replaced.

    Example::

        django__django-16379 → django__django-16379
        (SWE-bench images use the instance_id directly in most cases)
    """
    # SWE-bench evaluation images use the instance_id directly
    # The image naming is: swebench/sweb.eval.x86_64.{instance_id}:latest
    return instance_id
