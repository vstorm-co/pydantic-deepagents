"""Regression tests for model selection through the stock ACP entry point."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from acp import text_block
from acp.schema import SessionConfigOptionSelect, SessionConfigSelectOption
from pydantic_ai import Agent

from apps.acp import __main__ as acp_main
from apps.acp.server import DeepAgentACP
from tests.workspaces import state_workspace


@pytest.mark.parametrize(
    ("cli_model", "env", "model", "name"),
    [
        (
            "openai-chat:deepseek-chat",
            {"PYDANTIC_DEEP_MODEL": "openai:gpt-4.1", "ANTHROPIC_API_KEY": "test"},
            "openai-chat:deepseek-chat",
            "openai-chat:deepseek-chat",
        ),
        ("openai:gpt-4.1", {}, "openai:gpt-4.1", "GPT-4.1"),
        (
            None,
            {"PYDANTIC_DEEP_MODEL": "openai-chat:deepseek-chat", "ANTHROPIC_API_KEY": "test"},
            "openai-chat:deepseek-chat",
            "openai-chat:deepseek-chat",
        ),
        (
            None,
            {"PYDANTIC_DEEP_MODEL": "anthropic:claude-opus-4-6"},
            "anthropic:claude-opus-4-6",
            "Claude Opus 4.6",
        ),
        (
            None,
            {"ANTHROPIC_API_KEY": "test", "OPENROUTER_API_KEY": "test"},
            "anthropic:claude-sonnet-4-6",
            "Claude Sonnet 4.6",
        ),
        (
            None,
            {"OPENROUTER_API_KEY": "test", "OPENAI_API_KEY": "test"},
            "openrouter:anthropic/claude-sonnet-4",
            "Claude Sonnet 4 (OpenRouter)",
        ),
        (
            None,
            {"OPENAI_API_KEY": "test", "GOOGLE_API_KEY": "test"},
            "openai:gpt-4.1",
            "GPT-4.1",
        ),
        (None, {"GOOGLE_API_KEY": "test"}, "google:gemini-2.5-pro", "Gemini 2.5 Pro"),
        (None, {}, "anthropic:claude-sonnet-4-6", "Claude Sonnet 4.6"),
    ],
    ids=[
        "cli-custom",
        "cli-built-in",
        "env-custom",
        "env-built-in",
        "anthropic",
        "openrouter",
        "openai",
        "google",
        "fallback",
    ],
)
def test_new_sessions_use_configured_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cli_model: str | None,
    env: dict[str, str],
    model: str,
    name: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for key in (
        "PYDANTIC_DEEP_MODEL",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    args = ["pydantic-deep-acp"]
    if cli_model:
        args.extend(["--model", cli_model])
    monkeypatch.setattr("sys.argv", args)
    create_agent = MagicMock(return_value=Agent("test"))
    monkeypatch.setattr("pydantic_deep.create_deep_agent", create_agent)
    monkeypatch.setattr("pydantic_deep.LocalWorkspace", MagicMock())

    async def run_agent(server: DeepAgentACP) -> None:
        server.on_connect(AsyncMock())
        monkeypatch.setattr(server, "_workspace_for", lambda _: state_workspace())
        for _ in range(2):
            session = await server.new_session(cwd=str(tmp_path))
            assert session.config_options is not None
            selector = session.config_options[0]
            assert isinstance(selector, SessionConfigOptionSelect)
            assert selector.current_value == model
            options = [o for o in selector.options if isinstance(o, SessionConfigSelectOption)]
            assert len({option.value for option in options}) == len(options)
            assert next(option.name for option in options if option.value == model) == name
            result = await server.prompt([text_block("Hello")], session.session_id)
            assert result.stop_reason == "end_turn"
            assert create_agent.call_args.kwargs["model"] == model
            switched = await server.set_config_option("model", session.session_id, "google:test")
            assert switched.config_options[0].current_value == "google:test"

    monkeypatch.setattr(acp_main, "run_agent", run_agent)
    acp_main.main()
