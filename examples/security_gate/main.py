"""Built-in security hook preset — enable/extend recipe.

This example exercises `default_security_hook` directly against synthetic
`HookInput` payloads so it runs offline and deterministically. The same hook
list plugs into `create_deep_agent(hooks=...)` in real deployments.
"""

from __future__ import annotations

import asyncio

from pydantic_deep import default_security_hook
from pydantic_deep.features.hooks import DEFAULT_BLOCKED_COMMANDS, HookEvent, HookInput


def _pre_input(tool_name: str, args: dict[str, object]) -> HookInput:
    return HookInput(
        event=HookEvent.PRE_TOOL_USE.value,
        tool_name=tool_name,
        tool_input=args,
    )


def _post_input(tool_name: str, result: str) -> HookInput:
    return HookInput(
        event=HookEvent.POST_TOOL_USE.value,
        tool_name=tool_name,
        tool_input={},
        tool_result=result,
    )


async def _run_pre(hooks: list, tool_name: str, args: dict[str, object]) -> None:
    """Invoke the PRE_TOOL_USE handler from the preset and print the verdict."""
    pre = next(h for h in hooks if h.event == HookEvent.PRE_TOOL_USE)
    assert pre.handler is not None
    result = await pre.handler(_pre_input(tool_name, args))
    verdict = "ALLOW" if result.allow else "DENY "
    reason = f"  ({result.reason})" if result.reason else ""
    print(f"  [{verdict}] {tool_name}({args}){reason}")


async def _run_post(hooks: list, tool_name: str, output: str) -> None:
    """Invoke the POST_TOOL_USE redactor and show before/after."""
    post = next(h for h in hooks if h.event == HookEvent.POST_TOOL_USE)
    assert post.handler is not None
    result = await post.handler(_post_input(tool_name, output))
    after = result.modified_result if result.modified_result is not None else output
    print(f"  before: {output}")
    print(f"  after:  {after}")


async def demo_defaults() -> None:
    print("\n== 1. Out-of-the-box defaults ==")
    hooks = default_security_hook()

    await _run_pre(hooks, "execute", {"command": "rm -rf /"})
    await _run_pre(hooks, "execute", {"command": "ls -la"})
    await _run_pre(hooks, "read_file", {"path": "/home/me/.ssh/id_rsa"})
    await _run_pre(hooks, "read_file", {"path": "src/main.py"})
    await _run_pre(hooks, "write_file", {"path": "../../etc/passwd"})


async def demo_extend_blocklist() -> None:
    print("\n== 2. Extending the blocklist (keep defaults + add sudo) ==")
    hooks = default_security_hook(
        blocked_commands=[*DEFAULT_BLOCKED_COMMANDS, r"\bsudo\b"],
    )
    await _run_pre(hooks, "execute", {"command": "sudo apt install"})
    await _run_pre(hooks, "execute", {"command": "rm -rf /"})  # default still fires


async def demo_write_roots(tmp_root: str) -> None:
    print(f"\n== 3. allowed_write_roots=[{tmp_root!r}] ==")
    hooks = default_security_hook(allowed_write_roots=[tmp_root])
    await _run_pre(hooks, "write_file", {"path": f"{tmp_root}/output.txt"})
    await _run_pre(hooks, "write_file", {"path": "/etc/hosts"})


async def demo_redaction() -> None:
    print("\n== 4. Secret redaction in tool output ==")
    hooks = default_security_hook()
    await _run_post(
        hooks,
        "execute",
        "Connecting with AWS_KEY=AKIAIOSFODNN7EXAMPLE and token sk-abcdef0123456789abcdef",
    )


async def main() -> None:
    print("default_security_hook() — built-in safety preset for create_deep_agent")
    print("To use in an agent:")
    print("    agent = create_deep_agent(hooks=default_security_hook())")

    await demo_defaults()
    await demo_extend_blocklist()
    await demo_write_roots("/tmp/agent_workspace")
    await demo_redaction()


if __name__ == "__main__":
    asyncio.run(main())
