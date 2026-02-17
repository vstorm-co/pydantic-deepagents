"""Tests for Claude Code-style hooks system."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from pydantic_ai_backends import ExecuteResponse, SandboxProtocol, StateBackend

from pydantic_deep import DeepAgentDeps, create_deep_agent
from pydantic_deep.middleware.hooks import (
    EXIT_ALLOW,
    EXIT_DENY,
    Hook,
    HookEvent,
    HookInput,
    HookResult,
    HooksMiddleware,
    _build_hook_input,
    _execute_command_hook,
    _execute_handler_hook,
    _get_sandbox_backend,
    _match_hooks,
    _parse_command_result,
    _run_background_hook,
    _run_hook,
)

TEST_MODEL = TestModel()


# --- Fake SandboxProtocol for testing ---


@dataclass
class FakeSandboxBackend:
    """Minimal SandboxProtocol implementation for testing command hooks."""

    responses: dict[str, ExecuteResponse]
    """Map of command substring → response."""

    executed: list[str]
    """Log of executed commands."""

    def __init__(self, responses: dict[str, ExecuteResponse] | None = None) -> None:
        self.responses = responses or {}
        self.executed = []

    def execute(self, command: str, timeout: int | None = None) -> ExecuteResponse:
        self.executed.append(command)
        for key, response in self.responses.items():
            if key in command:
                return response
        return ExecuteResponse(output="", exit_code=0)

    # Stub BackendProtocol methods
    def list_files(self, path: str = "/") -> Any:
        return []  # pragma: no cover

    def read_bytes(self, path: str) -> bytes:
        return b""  # pragma: no cover

    def write(self, path: str, content: str) -> Any:
        return None  # pragma: no cover


# Register as SandboxProtocol
SandboxProtocol.register(FakeSandboxBackend)


# --- Tests: Hook dataclass validation ---


class TestHookValidation:
    def test_hook_requires_command_or_handler(self):
        with pytest.raises(ValueError, match="must have either"):
            Hook(event=HookEvent.PRE_TOOL_USE)

    def test_hook_cannot_have_both_command_and_handler(self):
        async def handler(hook_input: HookInput) -> HookResult:
            return HookResult()  # pragma: no cover

        with pytest.raises(ValueError, match="cannot have both"):
            Hook(
                event=HookEvent.PRE_TOOL_USE,
                command="echo test",
                handler=handler,
            )

    def test_hook_with_command(self):
        hook = Hook(event=HookEvent.PRE_TOOL_USE, command="echo test")
        assert hook.command == "echo test"
        assert hook.handler is None
        assert hook.matcher is None
        assert hook.timeout == 30
        assert hook.background is False

    def test_hook_with_handler(self):
        async def handler(hook_input: HookInput) -> HookResult:
            return HookResult()  # pragma: no cover

        hook = Hook(event=HookEvent.POST_TOOL_USE, handler=handler)
        assert hook.handler is handler
        assert hook.command is None

    def test_hook_with_all_params(self):
        hook = Hook(
            event=HookEvent.PRE_TOOL_USE,
            command="checker",
            matcher="execute|write_file",
            timeout=60,
            background=True,
        )
        assert hook.matcher == "execute|write_file"
        assert hook.timeout == 60
        assert hook.background is True


# --- Tests: HookEvent enum ---


class TestHookEvent:
    def test_values(self):
        assert HookEvent.PRE_TOOL_USE.value == "pre_tool_use"
        assert HookEvent.POST_TOOL_USE.value == "post_tool_use"
        assert HookEvent.POST_TOOL_USE_FAILURE.value == "post_tool_use_failure"

    def test_str_enum(self):
        assert isinstance(HookEvent.PRE_TOOL_USE, str)


# --- Tests: HookInput ---


class TestHookInput:
    def test_basic(self):
        hi = HookInput(
            event="pre_tool_use",
            tool_name="execute",
            tool_input={"command": "ls"},
        )
        assert hi.event == "pre_tool_use"
        assert hi.tool_name == "execute"
        assert hi.tool_input == {"command": "ls"}
        assert hi.tool_result is None
        assert hi.tool_error is None

    def test_with_result(self):
        hi = HookInput(
            event="post_tool_use",
            tool_name="read_file",
            tool_input={"path": "/foo.txt"},
            tool_result="file contents",
        )
        assert hi.tool_result == "file contents"

    def test_with_error(self):
        hi = HookInput(
            event="post_tool_use_failure",
            tool_name="execute",
            tool_input={"command": "bad"},
            tool_error="Command failed",
        )
        assert hi.tool_error == "Command failed"


# --- Tests: HookResult ---


class TestHookResult:
    def test_defaults(self):
        result = HookResult()
        assert result.allow is True
        assert result.reason is None
        assert result.modified_args is None
        assert result.modified_result is None

    def test_deny(self):
        result = HookResult(allow=False, reason="Not allowed")
        assert result.allow is False
        assert result.reason == "Not allowed"

    def test_modified_args(self):
        result = HookResult(modified_args={"command": "safe_command"})
        assert result.modified_args == {"command": "safe_command"}

    def test_modified_result(self):
        result = HookResult(modified_result="sanitized output")
        assert result.modified_result == "sanitized output"


# --- Tests: Exit code constants ---


class TestExitCodes:
    def test_constants(self):
        assert EXIT_ALLOW == 0
        assert EXIT_DENY == 2


# --- Tests: _match_hooks ---


class TestMatchHooks:
    def test_match_by_event(self):
        hooks = [
            Hook(event=HookEvent.PRE_TOOL_USE, command="pre"),
            Hook(event=HookEvent.POST_TOOL_USE, command="post"),
        ]
        matched = _match_hooks(hooks, HookEvent.PRE_TOOL_USE, "execute")
        assert len(matched) == 1
        assert matched[0].command == "pre"

    def test_none_matcher_matches_all(self):
        hook = Hook(event=HookEvent.PRE_TOOL_USE, command="check")
        matched = _match_hooks([hook], HookEvent.PRE_TOOL_USE, "anything")
        assert len(matched) == 1

    def test_regex_matcher_matches(self):
        hook = Hook(
            event=HookEvent.PRE_TOOL_USE,
            command="check",
            matcher="execute|write_file",
        )
        assert len(_match_hooks([hook], HookEvent.PRE_TOOL_USE, "execute")) == 1
        assert len(_match_hooks([hook], HookEvent.PRE_TOOL_USE, "write_file")) == 1
        assert len(_match_hooks([hook], HookEvent.PRE_TOOL_USE, "read_file")) == 0

    def test_regex_matcher_partial_match(self):
        hook = Hook(event=HookEvent.PRE_TOOL_USE, command="check", matcher="file")
        assert len(_match_hooks([hook], HookEvent.PRE_TOOL_USE, "write_file")) == 1
        assert len(_match_hooks([hook], HookEvent.PRE_TOOL_USE, "read_file")) == 1

    def test_no_match(self):
        hook = Hook(event=HookEvent.PRE_TOOL_USE, command="check", matcher="^execute$")
        assert len(_match_hooks([hook], HookEvent.PRE_TOOL_USE, "write_file")) == 0

    def test_multiple_hooks_matched(self):
        hooks = [
            Hook(event=HookEvent.PRE_TOOL_USE, command="check1"),
            Hook(event=HookEvent.PRE_TOOL_USE, command="check2"),
        ]
        matched = _match_hooks(hooks, HookEvent.PRE_TOOL_USE, "execute")
        assert len(matched) == 2

    def test_empty_hooks(self):
        assert _match_hooks([], HookEvent.PRE_TOOL_USE, "execute") == []


# --- Tests: _build_hook_input ---


class TestBuildHookInput:
    def test_pre_tool_use(self):
        hi = _build_hook_input(HookEvent.PRE_TOOL_USE, "execute", {"command": "ls"})
        assert hi.event == "pre_tool_use"
        assert hi.tool_name == "execute"
        assert hi.tool_input == {"command": "ls"}
        assert hi.tool_result is None
        assert hi.tool_error is None

    def test_post_tool_use(self):
        hi = _build_hook_input(
            HookEvent.POST_TOOL_USE,
            "read_file",
            {"path": "/foo"},
            tool_result="contents",
        )
        assert hi.tool_result == "contents"

    def test_post_tool_use_failure(self):
        error = ValueError("bad")
        hi = _build_hook_input(
            HookEvent.POST_TOOL_USE_FAILURE,
            "execute",
            {"command": "bad"},
            tool_error=error,
        )
        assert hi.tool_error == "bad"


# --- Tests: _parse_command_result ---


class TestParseCommandResult:
    def test_exit_0_allow(self):
        result = _parse_command_result(ExecuteResponse(output="", exit_code=0))
        assert result.allow is True

    def test_exit_2_deny(self):
        result = _parse_command_result(ExecuteResponse(output="Not allowed", exit_code=2))
        assert result.allow is False
        assert result.reason == "Not allowed"

    def test_exit_2_deny_empty_output(self):
        result = _parse_command_result(ExecuteResponse(output="", exit_code=2))
        assert result.allow is False
        assert result.reason == "Denied by hook"

    def test_json_output_modified_args(self):
        result = _parse_command_result(
            ExecuteResponse(
                output='{"modified_args": {"command": "safe"}}',
                exit_code=0,
            )
        )
        assert result.allow is True
        assert result.modified_args == {"command": "safe"}

    def test_json_output_modified_result(self):
        result = _parse_command_result(
            ExecuteResponse(
                output='{"modified_result": "sanitized"}',
                exit_code=0,
            )
        )
        assert result.modified_result == "sanitized"

    def test_json_output_with_reason(self):
        result = _parse_command_result(
            ExecuteResponse(
                output='{"reason": "checked OK"}',
                exit_code=0,
            )
        )
        assert result.reason == "checked OK"

    def test_non_json_output_ignored(self):
        result = _parse_command_result(ExecuteResponse(output="some plain text", exit_code=0))
        assert result.allow is True
        assert result.modified_args is None

    def test_non_dict_json_ignored(self):
        result = _parse_command_result(ExecuteResponse(output="[1, 2, 3]", exit_code=0))
        assert result.allow is True
        assert result.modified_args is None

    def test_other_exit_code_treated_as_allow(self):
        result = _parse_command_result(ExecuteResponse(output="", exit_code=1))
        assert result.allow is True


# --- Tests: _execute_command_hook ---


class TestExecuteCommandHook:
    async def test_basic_command(self):
        backend = FakeSandboxBackend({"checker": ExecuteResponse(output="", exit_code=0)})
        hook = Hook(event=HookEvent.PRE_TOOL_USE, command="checker")
        hook_input = HookInput(
            event="pre_tool_use",
            tool_name="execute",
            tool_input={"command": "ls"},
        )
        result = await _execute_command_hook(hook, hook_input, backend)
        assert result.allow is True
        assert len(backend.executed) == 1
        assert "checker" in backend.executed[0]

    async def test_command_receives_json_stdin(self):
        backend = FakeSandboxBackend()
        hook = Hook(event=HookEvent.PRE_TOOL_USE, command="my-checker")
        hook_input = HookInput(
            event="pre_tool_use",
            tool_name="execute",
            tool_input={"command": "ls"},
        )
        await _execute_command_hook(hook, hook_input, backend)
        cmd = backend.executed[0]
        assert "printf" in cmd
        assert "my-checker" in cmd
        assert "execute" in cmd  # tool_name in JSON

    async def test_command_deny(self):
        backend = FakeSandboxBackend({"blocker": ExecuteResponse(output="Blocked!", exit_code=2)})
        hook = Hook(event=HookEvent.PRE_TOOL_USE, command="blocker")
        hook_input = HookInput(
            event="pre_tool_use",
            tool_name="execute",
            tool_input={},
        )
        result = await _execute_command_hook(hook, hook_input, backend)
        assert result.allow is False
        assert result.reason == "Blocked!"

    async def test_command_with_timeout(self):
        backend = FakeSandboxBackend()
        hook = Hook(event=HookEvent.PRE_TOOL_USE, command="slow-check", timeout=60)
        hook_input = HookInput(event="pre_tool_use", tool_name="t", tool_input={})
        await _execute_command_hook(hook, hook_input, backend)
        assert len(backend.executed) == 1


# --- Tests: _execute_handler_hook ---


class TestExecuteHandlerHook:
    async def test_handler_called(self):
        calls: list[HookInput] = []

        async def handler(hi: HookInput) -> HookResult:
            calls.append(hi)
            return HookResult(allow=True, reason="OK")

        hook = Hook(event=HookEvent.PRE_TOOL_USE, handler=handler)
        hook_input = HookInput(event="pre_tool_use", tool_name="execute", tool_input={"cmd": "ls"})
        result = await _execute_handler_hook(hook, hook_input)
        assert result.allow is True
        assert result.reason == "OK"
        assert len(calls) == 1
        assert calls[0].tool_name == "execute"

    async def test_handler_deny(self):
        async def handler(hi: HookInput) -> HookResult:
            return HookResult(allow=False, reason="Denied by handler")

        hook = Hook(event=HookEvent.PRE_TOOL_USE, handler=handler)
        hook_input = HookInput(event="pre_tool_use", tool_name="t", tool_input={})
        result = await _execute_handler_hook(hook, hook_input)
        assert result.allow is False

    async def test_handler_modify_args(self):
        async def handler(hi: HookInput) -> HookResult:
            return HookResult(modified_args={"safe": True})

        hook = Hook(event=HookEvent.PRE_TOOL_USE, handler=handler)
        hook_input = HookInput(event="pre_tool_use", tool_name="t", tool_input={})
        result = await _execute_handler_hook(hook, hook_input)
        assert result.modified_args == {"safe": True}


# --- Tests: _run_hook ---


class TestRunHook:
    async def test_command_hook(self):
        backend = FakeSandboxBackend()
        hook = Hook(event=HookEvent.PRE_TOOL_USE, command="check")
        hook_input = HookInput(event="pre_tool_use", tool_name="t", tool_input={})
        result = await _run_hook(hook, hook_input, backend)
        assert result.allow is True

    async def test_handler_hook(self):
        async def handler(hi: HookInput) -> HookResult:
            return HookResult()

        hook = Hook(event=HookEvent.PRE_TOOL_USE, handler=handler)
        hook_input = HookInput(event="pre_tool_use", tool_name="t", tool_input={})
        result = await _run_hook(hook, hook_input, None)
        assert result.allow is True

    async def test_command_hook_no_sandbox_raises(self):
        hook = Hook(event=HookEvent.PRE_TOOL_USE, command="check")
        hook_input = HookInput(event="pre_tool_use", tool_name="t", tool_input={})
        with pytest.raises(RuntimeError, match="SandboxProtocol"):
            await _run_hook(hook, hook_input, None)

    async def test_command_hook_non_sandbox_backend_raises(self):
        hook = Hook(event=HookEvent.PRE_TOOL_USE, command="check")
        hook_input = HookInput(event="pre_tool_use", tool_name="t", tool_input={})
        # StateBackend is not a SandboxProtocol
        with pytest.raises(RuntimeError, match="SandboxProtocol"):
            await _run_hook(hook, hook_input, StateBackend())  # type: ignore[arg-type]


# --- Tests: _run_background_hook ---


class TestRunBackgroundHook:
    async def test_background_success(self):
        calls: list[str] = []

        async def handler(hi: HookInput) -> HookResult:
            calls.append(hi.tool_name)
            return HookResult()

        hook = Hook(event=HookEvent.POST_TOOL_USE, handler=handler)
        hook_input = HookInput(event="post_tool_use", tool_name="test", tool_input={})
        await _run_background_hook(hook, hook_input, None)
        assert calls == ["test"]

    async def test_background_error_suppressed(self):
        async def handler(hi: HookInput) -> HookResult:
            raise RuntimeError("oops")

        hook = Hook(event=HookEvent.POST_TOOL_USE, handler=handler)
        hook_input = HookInput(event="post_tool_use", tool_name="t", tool_input={})
        # Should not raise
        await _run_background_hook(hook, hook_input, None)


# --- Tests: _get_sandbox_backend ---


class TestGetSandboxBackend:
    def test_none_deps(self):
        assert _get_sandbox_backend(None) is None

    def test_state_backend(self):
        deps = DeepAgentDeps(backend=StateBackend())
        assert _get_sandbox_backend(deps) is None

    def test_sandbox_backend(self):
        backend = FakeSandboxBackend()
        deps = DeepAgentDeps(backend=backend)  # type: ignore[arg-type]
        assert _get_sandbox_backend(deps) is backend


# --- Tests: HooksMiddleware ---


class TestHooksMiddleware:
    def test_create(self):
        hook = Hook(event=HookEvent.PRE_TOOL_USE, command="check")
        mw = HooksMiddleware([hook])
        assert len(mw.hooks) == 1

    async def test_before_tool_call_no_matching_hooks(self):
        hook = Hook(event=HookEvent.POST_TOOL_USE, command="log")
        mw = HooksMiddleware([hook])
        result = await mw.before_tool_call("execute", {"cmd": "ls"}, None)
        assert result == {"cmd": "ls"}

    async def test_before_tool_call_handler_allow(self):
        async def handler(hi: HookInput) -> HookResult:
            return HookResult(allow=True)

        hook = Hook(event=HookEvent.PRE_TOOL_USE, handler=handler)
        mw = HooksMiddleware([hook])
        result = await mw.before_tool_call("execute", {"cmd": "ls"}, None)
        assert result == {"cmd": "ls"}

    async def test_before_tool_call_handler_deny(self):
        async def handler(hi: HookInput) -> HookResult:
            return HookResult(allow=False, reason="Blocked")

        hook = Hook(event=HookEvent.PRE_TOOL_USE, handler=handler)
        mw = HooksMiddleware([hook])
        result = await mw.before_tool_call("execute", {}, None)
        # Should return ToolPermissionResult with DENY
        from pydantic_ai_middleware import ToolDecision, ToolPermissionResult

        assert isinstance(result, ToolPermissionResult)
        assert result.decision == ToolDecision.DENY
        assert result.reason == "Blocked"

    async def test_before_tool_call_handler_modify_args(self):
        async def handler(hi: HookInput) -> HookResult:
            return HookResult(modified_args={"cmd": "safe_cmd"})

        hook = Hook(event=HookEvent.PRE_TOOL_USE, handler=handler)
        mw = HooksMiddleware([hook])
        result = await mw.before_tool_call("execute", {"cmd": "dangerous"}, None)
        assert result == {"cmd": "safe_cmd"}

    async def test_before_tool_call_first_deny_wins(self):
        async def allow_handler(hi: HookInput) -> HookResult:
            return HookResult(allow=True)

        async def deny_handler(hi: HookInput) -> HookResult:
            return HookResult(allow=False, reason="Blocked by second")

        mw = HooksMiddleware(
            [
                Hook(event=HookEvent.PRE_TOOL_USE, handler=allow_handler),
                Hook(event=HookEvent.PRE_TOOL_USE, handler=deny_handler),
            ]
        )
        result = await mw.before_tool_call("execute", {}, None)
        from pydantic_ai_middleware import ToolPermissionResult

        assert isinstance(result, ToolPermissionResult)

    async def test_before_tool_call_background_hook(self):
        calls: list[str] = []

        async def bg_handler(hi: HookInput) -> HookResult:
            calls.append("bg")
            return HookResult()

        hook = Hook(event=HookEvent.PRE_TOOL_USE, handler=bg_handler, background=True)
        mw = HooksMiddleware([hook])
        result = await mw.before_tool_call("execute", {"a": 1}, None)
        # Background hook is fire-and-forget
        assert result == {"a": 1}
        # Give task a moment to complete
        await asyncio.sleep(0.05)
        assert calls == ["bg"]

    async def test_before_tool_call_command_hook(self):
        backend = FakeSandboxBackend({"checker": ExecuteResponse(output="", exit_code=0)})
        deps = DeepAgentDeps(backend=backend)  # type: ignore[arg-type]
        hook = Hook(event=HookEvent.PRE_TOOL_USE, command="checker")
        mw = HooksMiddleware([hook])
        result = await mw.before_tool_call("execute", {"cmd": "ls"}, deps)
        assert result == {"cmd": "ls"}

    async def test_before_tool_call_command_deny(self):
        backend = FakeSandboxBackend({"blocker": ExecuteResponse(output="Nope", exit_code=2)})
        deps = DeepAgentDeps(backend=backend)  # type: ignore[arg-type]
        hook = Hook(event=HookEvent.PRE_TOOL_USE, command="blocker")
        mw = HooksMiddleware([hook])
        result = await mw.before_tool_call("execute", {}, deps)
        from pydantic_ai_middleware import ToolDecision, ToolPermissionResult

        assert isinstance(result, ToolPermissionResult)
        assert result.decision == ToolDecision.DENY

    async def test_after_tool_call_no_matching_hooks(self):
        hook = Hook(event=HookEvent.PRE_TOOL_USE, command="check")
        mw = HooksMiddleware([hook])
        result = await mw.after_tool_call("t", {}, "output", None)
        assert result == "output"

    async def test_after_tool_call_handler(self):
        async def handler(hi: HookInput) -> HookResult:
            return HookResult(modified_result="modified")

        hook = Hook(event=HookEvent.POST_TOOL_USE, handler=handler)
        mw = HooksMiddleware([hook])
        result = await mw.after_tool_call("t", {}, "original", None)
        assert result == "modified"

    async def test_after_tool_call_no_modification(self):
        async def handler(hi: HookInput) -> HookResult:
            return HookResult()

        hook = Hook(event=HookEvent.POST_TOOL_USE, handler=handler)
        mw = HooksMiddleware([hook])
        result = await mw.after_tool_call("t", {}, "original", None)
        assert result == "original"

    async def test_after_tool_call_background(self):
        calls: list[str] = []

        async def bg_handler(hi: HookInput) -> HookResult:
            calls.append("bg_post")
            return HookResult()

        hook = Hook(event=HookEvent.POST_TOOL_USE, handler=bg_handler, background=True)
        mw = HooksMiddleware([hook])
        result = await mw.after_tool_call("t", {}, "output", None)
        assert result == "output"
        await asyncio.sleep(0.05)
        assert calls == ["bg_post"]

    async def test_after_tool_call_command(self):
        backend = FakeSandboxBackend(
            {"logger": ExecuteResponse(output='{"modified_result": "logged"}', exit_code=0)}
        )
        deps = DeepAgentDeps(backend=backend)  # type: ignore[arg-type]
        hook = Hook(event=HookEvent.POST_TOOL_USE, command="logger")
        mw = HooksMiddleware([hook])
        result = await mw.after_tool_call("t", {}, "original", deps)
        assert result == "logged"

    async def test_on_tool_error_no_matching_hooks(self):
        hook = Hook(event=HookEvent.PRE_TOOL_USE, command="check")
        mw = HooksMiddleware([hook])
        result = await mw.on_tool_error("t", {}, RuntimeError("err"), None)
        assert result is None

    async def test_on_tool_error_handler(self):
        calls: list[str] = []

        async def handler(hi: HookInput) -> HookResult:
            calls.append(hi.tool_error or "")
            return HookResult()

        hook = Hook(event=HookEvent.POST_TOOL_USE_FAILURE, handler=handler)
        mw = HooksMiddleware([hook])
        result = await mw.on_tool_error("execute", {}, RuntimeError("boom"), None)
        assert result is None
        assert calls == ["boom"]

    async def test_on_tool_error_background(self):
        calls: list[str] = []

        async def bg_handler(hi: HookInput) -> HookResult:
            calls.append("bg_error")
            return HookResult()

        hook = Hook(
            event=HookEvent.POST_TOOL_USE_FAILURE,
            handler=bg_handler,
            background=True,
        )
        mw = HooksMiddleware([hook])
        await mw.on_tool_error("t", {}, RuntimeError("err"), None)
        await asyncio.sleep(0.05)
        assert calls == ["bg_error"]

    async def test_on_tool_error_command(self):
        backend = FakeSandboxBackend({"error-handler": ExecuteResponse(output="", exit_code=0)})
        deps = DeepAgentDeps(backend=backend)  # type: ignore[arg-type]
        hook = Hook(event=HookEvent.POST_TOOL_USE_FAILURE, command="error-handler")
        mw = HooksMiddleware([hook])
        await mw.on_tool_error("execute", {"cmd": "bad"}, RuntimeError("fail"), deps)
        assert len(backend.executed) == 1

    async def test_multiple_post_hooks_chain_modifications(self):
        async def handler1(hi: HookInput) -> HookResult:
            return HookResult(modified_result="step1")

        async def handler2(hi: HookInput) -> HookResult:
            # Should receive step1 result in hook_input
            assert hi.tool_result == "step1"
            return HookResult(modified_result="step2")

        mw = HooksMiddleware(
            [
                Hook(event=HookEvent.POST_TOOL_USE, handler=handler1),
                Hook(event=HookEvent.POST_TOOL_USE, handler=handler2),
            ]
        )
        result = await mw.after_tool_call("t", {}, "original", None)
        assert result == "step2"

    async def test_multiple_pre_hooks_chain_arg_modifications(self):
        async def handler1(hi: HookInput) -> HookResult:
            return HookResult(modified_args={"cmd": "step1"})

        async def handler2(hi: HookInput) -> HookResult:
            assert hi.tool_input == {"cmd": "step1"}
            return HookResult(modified_args={"cmd": "step2"})

        mw = HooksMiddleware(
            [
                Hook(event=HookEvent.PRE_TOOL_USE, handler=handler1),
                Hook(event=HookEvent.PRE_TOOL_USE, handler=handler2),
            ]
        )
        result = await mw.before_tool_call("execute", {"cmd": "original"}, None)
        assert result == {"cmd": "step2"}

    async def test_before_tool_call_deny_default_reason(self):
        async def handler(hi: HookInput) -> HookResult:
            return HookResult(allow=False)

        hook = Hook(event=HookEvent.PRE_TOOL_USE, handler=handler)
        mw = HooksMiddleware([hook])
        result = await mw.before_tool_call("execute", {}, None)
        from pydantic_ai_middleware import ToolPermissionResult

        assert isinstance(result, ToolPermissionResult)
        assert result.reason == "Denied by hook"


# --- Tests: Integration with create_deep_agent ---


class TestCreateDeepAgentWithHooks:
    def test_hooks_param_wraps_in_middleware_agent(self):
        from pydantic_ai_middleware import MiddlewareAgent

        async def handler(hi: HookInput) -> HookResult:
            return HookResult()  # pragma: no cover

        hook = Hook(event=HookEvent.PRE_TOOL_USE, handler=handler)
        agent = create_deep_agent(model=TEST_MODEL, hooks=[hook])
        assert isinstance(agent, MiddlewareAgent)

    def test_hooks_with_existing_middleware(self):
        from pydantic_ai_middleware import MiddlewareAgent

        # Define a simple middleware
        from pydantic_deep import AgentMiddleware

        class MyMiddleware(AgentMiddleware[DeepAgentDeps]):
            async def before_run(self, prompt, deps, ctx):
                return prompt

        async def handler(hi: HookInput) -> HookResult:
            return HookResult()  # pragma: no cover

        hook = Hook(event=HookEvent.PRE_TOOL_USE, handler=handler)
        agent = create_deep_agent(
            model=TEST_MODEL,
            hooks=[hook],
            middleware=[MyMiddleware()],
        )
        assert isinstance(agent, MiddlewareAgent)
        # Should have 4 middleware: MyMiddleware + HooksMiddleware + ContextManagerMiddleware + CostTrackingMiddleware
        assert len(agent.middleware) == 4

    def test_no_hooks_returns_plain_agent(self):
        agent = create_deep_agent(model=TEST_MODEL, cost_tracking=False)
        assert isinstance(agent, Agent)


# --- Tests: Exports ---


class TestHooksExports:
    def test_importable_from_pydantic_deep(self):
        from pydantic_deep import (
            EXIT_ALLOW,
            EXIT_DENY,
            Hook,
            HookEvent,
            HookInput,
            HookResult,
            HooksMiddleware,
        )

        assert Hook is not None
        assert HookEvent is not None
        assert HookInput is not None
        assert HookResult is not None
        assert HooksMiddleware is not None
        assert EXIT_ALLOW == 0
        assert EXIT_DENY == 2
