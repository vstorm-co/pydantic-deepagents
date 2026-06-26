"""Tests for the standard mcpServers parser + env expansion (pydantic_deep.mcp.loader)."""

from __future__ import annotations

from typing import Any

import pytest

from pydantic_deep.mcp import expand_env_vars, parse_mcp_servers


def test_expand_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYVAR", "hello")
    assert expand_env_vars("${MYVAR}") == "hello"
    assert expand_env_vars("a-${MYVAR}-b") == "a-hello-b"
    # default used when unset
    monkeypatch.delenv("NOPE", raising=False)
    assert expand_env_vars("${NOPE:-fallback}") == "fallback"
    # unset, no default -> left as-is
    assert expand_env_vars("${NOPE}") == "${NOPE}"
    # non-template passes through
    assert expand_env_vars("plain") == "plain"


def test_parse_http_stdio_sse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOK", "secret")
    servers = parse_mcp_servers(
        {
            "github": {
                "type": "http",
                "url": "https://api.githubcopilot.com/mcp/",
                "headers": {"Authorization": "Bearer ${TOK}"},
            },
            "db": {"command": "npx", "args": ["-y", "pkg"], "env": {"K": "${TOK}"}},
            "legacy": {"type": "sse", "url": "https://x/sse"},
            "bare_url": {"url": "https://y/mcp"},
        }
    )
    by_name = {s.name: s for s in servers}
    assert by_name["github"].transport == "http"
    assert by_name["github"].headers["Authorization"] == "Bearer secret"
    assert by_name["db"].transport == "stdio"
    assert by_name["db"].command == "npx"
    assert by_name["db"].env["K"] == "secret"
    assert by_name["legacy"].transport == "sse"
    # A bare url with no type defaults to http.
    assert by_name["bare_url"].transport == "http"


def test_parse_skips_ws_and_malformed() -> None:
    raw: dict[str, Any] = {
        "ws1": {"type": "ws", "url": "wss://x/socket"},
        "notdict": "oops",
        "empty": {},
        "ok": {"url": "https://z/mcp"},
    }
    servers = parse_mcp_servers(raw)
    names = {s.name for s in servers}
    assert names == {"ok"}


def test_parse_skips_entry_that_raises() -> None:
    # 'args' is not iterable -> the list comprehension raises -> entry skipped,
    # but a valid sibling is still imported.
    servers = parse_mcp_servers(
        {
            "broken": {"command": "npx", "args": 123},
            "ok": {"command": "npx", "args": ["-y", "x"]},
        }
    )
    names = {s.name for s in servers}
    assert names == {"ok"}


def test_parse_coerces_non_string_args() -> None:
    # A numeric arg/env value must reach the `list[str]`/`dict[str, str]`
    # contract as a string, not an int (B13).
    servers = parse_mcp_servers(
        {"s": {"command": "npx", "args": ["-p", 8080], "env": {"PORT": 8080}}}
    )
    assert servers[0].args == ["-p", "8080"]
    assert servers[0].env == {"PORT": "8080"}


def test_parse_logs_skipped_entries(caplog: pytest.LogCaptureFixture) -> None:
    raw: dict[str, Any] = {
        "notdict": "oops",
        "ws1": {"type": "ws", "url": "wss://x/socket"},
        "broken": {"command": "npx", "args": 123},
    }
    with caplog.at_level("WARNING"):
        servers = parse_mcp_servers(raw)
    assert servers == []
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "notdict" in messages
    assert "ws1" in messages
    assert "broken" in messages


def test_parse_streamable_http_alias() -> None:
    servers = parse_mcp_servers({"s": {"type": "streamable-http", "url": "https://a/mcp"}})
    assert servers[0].transport == "http"


def test_parse_enabled_flag() -> None:
    on = parse_mcp_servers({"s": {"url": "https://a/mcp"}}, enabled=True)
    off = parse_mcp_servers({"s": {"url": "https://a/mcp"}}, enabled=False)
    assert on[0].enabled is True
    assert off[0].enabled is False
