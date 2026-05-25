"""External diff tool detection and invocation.

Detects which diff tool is available on the user's machine and launches it
against the materialised parent + branch snapshots produced by
:class:`pydantic_deep.toolsets.forking.materializer.ForkMaterializer`.

Detection priority (per project memory):

1. ``PYDANTIC_DEEP_DIFFTOOL`` environment variable — explicit override.
   The value is passed verbatim to the shell and the kind becomes
   ``"custom"``; downstream callers (:mod:`apps.cli.commands`) format the
   command themselves so we don't try to second-guess the user's tool.
2. ``pycharm`` on ``PATH`` → native 3-way diff via a single
   ``subprocess.Popen(["pycharm", "diff", parent, a, b, c, ...])``.
3. ``code`` on ``PATH`` → VS Code pairwise — one ``Popen`` per branch,
   each ``["code", "--diff", parent, branch]``.
4. Otherwise the kind becomes ``"tui"`` and :meth:`EditorDetector.invoke`
   returns an empty list — the CLI dispatcher falls back to the
   :class:`MergePickerModal` in diff-explore mode.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

EditorKind = Literal["pycharm", "vscode", "tui", "custom"]


class EditorDetector:
    """Static utility — detection and invocation are stateless."""

    ENV_OVERRIDE = "PYDANTIC_DEEP_DIFFTOOL"

    @staticmethod
    def detect(env: Mapping[str, str] | None = None) -> EditorKind:
        """Return the kind of editor to use based on env + ``PATH``.

        Args:
            env: Optional mapping to read the override variable from; when
                ``None`` reads ``os.environ`` directly. Tests pass an
                explicit mapping so they don't have to manipulate the
                process env.
        """
        environment = env if env is not None else os.environ
        if environment.get(EditorDetector.ENV_OVERRIDE):
            return "custom"
        if shutil.which("pycharm"):
            return "pycharm"
        if shutil.which("code"):
            return "vscode"
        return "tui"

    @staticmethod
    def invoke(
        kind: EditorKind,
        parent: Path | None,
        branch_paths: list[Path],
        *,
        custom_cmd: str | None = None,
    ) -> list[subprocess.Popen[bytes]]:
        """Launch the detected editor against ``parent`` and ``branch_paths``.

        Returns:
            The list of spawned :class:`subprocess.Popen` handles — empty
            for the TUI fallback (caller opens the in-TUI explorer
            instead). For PyCharm the list always has length 1; for VS
            Code it has length ``len(branch_paths)`` (one ``Popen`` per
            branch, each diffing parent vs that one branch — VS Code only
            does 2-way diff).

        Args:
            kind: Editor kind from :meth:`detect`.
            parent: Path to the materialised parent snapshot, or ``None``
                to open a branch-only diff (branches compared directly,
                no parent file passed to the editor).
            branch_paths: One path per branch (materialised under
                ``branches/{label}/{path}``).
            custom_cmd: Command template used when ``kind == "custom"``.
                Tokens ``{parent}`` and ``{branches}`` are substituted
                with the parent path (empty string when ``parent`` is
                ``None``) and a space-separated list of branch paths
                respectively. When ``None`` and the kind is
                ``"custom"``, the environment variable
                ``PYDANTIC_DEEP_DIFFTOOL`` is read at invoke time.
        """
        if kind == "tui":
            return []
        if kind == "pycharm":
            if parent is not None and len(branch_paths) == 2:
                args: list[str] = [
                    "pycharm",
                    "diff",
                    str(branch_paths[0]),
                    str(parent),
                    str(branch_paths[1]),
                ]
            elif parent is not None:
                args = ["pycharm", "diff", str(parent), *[str(p) for p in branch_paths]]
            else:
                args = ["pycharm", "diff", *[str(p) for p in branch_paths]]
            return [subprocess.Popen(args)]
        if kind == "vscode":
            if parent is not None:
                handles: list[subprocess.Popen[bytes]] = []
                for branch in branch_paths:
                    handles.append(subprocess.Popen(["code", "--diff", str(parent), str(branch)]))
                return handles
            if not branch_paths:
                return []
            if len(branch_paths) == 1:
                return [subprocess.Popen(["code", str(branch_paths[0])])]
            handles = []
            first = branch_paths[0]
            for branch in branch_paths[1:]:
                handles.append(subprocess.Popen(["code", "--diff", str(first), str(branch)]))
            return handles
        # User-controlled template via PYDANTIC_DEEP_DIFFTOOL — shell=True is intentional.
        cmd_template = (
            custom_cmd
            if custom_cmd is not None
            else os.environ.get(EditorDetector.ENV_OVERRIDE, "")
        )
        if not cmd_template:  # pragma: no cover - guarded by detect()
            return []
        branches_str = " ".join(str(p) for p in branch_paths)
        parent_str = str(parent) if parent is not None else ""
        resolved = cmd_template.format(parent=parent_str, branches=branches_str)
        return [subprocess.Popen(resolved, shell=True)]  # nosec B602 noqa: S602


__all__ = ["EditorDetector", "EditorKind"]
