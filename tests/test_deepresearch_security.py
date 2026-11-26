"""The DeepResearch app enforces operator access and session path boundaries."""

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from apps.deepresearch.src.deepresearch import app as research
from apps.deepresearch.src.deepresearch import config


def test_http_and_websocket_require_operator_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPRESEARCH_PASSWORD", "test-password")
    monkeypatch.setattr(research, "agent", None)
    client = TestClient(research.app)
    assert client.get("/sessions").status_code == 401
    assert client.post("/session/new").status_code == 401
    with (
        pytest.raises(WebSocketDisconnect) as unauthenticated,
        client.websocket_connect("/ws/chat"),
    ):
        pass
    assert unauthenticated.value.code == 1008

    login = client.get("/", auth=("deepresearch", "test-password"))
    assert login.is_success
    assert "HttpOnly" in login.headers["set-cookie"]
    assert "SameSite=strict" in login.headers["set-cookie"]
    assert client.get("/sessions").is_success
    assert (
        client.post(
            "/reset?session_id=unknown", headers={"Origin": "https://elsewhere.test"}
        ).status_code
        == 403
    )

    with (
        pytest.raises(WebSocketDisconnect) as cross_origin,
        client.websocket_connect("/ws/chat", headers={"Origin": "https://elsewhere.test"}),
    ):
        pass
    assert cross_origin.value.code == 1008
    with client.websocket_connect("/ws/chat", headers={"Origin": "http://testserver"}) as socket:
        assert socket.receive_json()["content"] == "Agent not initialized"


def test_unconfigured_service_never_serves_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPRESEARCH_PASSWORD", raising=False)
    assert TestClient(research.app).get("/sessions").status_code == 503


def test_session_paths_use_only_canonical_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sessions"
    root.mkdir()
    monkeypatch.setattr(research, "WORKSPACES_DIR", root)

    session_id = str(uuid4())
    assert research._session_host_dir(session_id) == root / session_id / "workspace"
    with pytest.raises(HTTPException, match="Invalid session id"):
        research._session_directory(session_id.upper())

    alias = str(uuid4())
    (root / alias).symlink_to(root / session_id, target_is_directory=True)
    with pytest.raises(HTTPException, match="Invalid session id"):
        research._session_directory(alias)


@pytest.mark.parametrize(
    ("enabled", "key", "expected"),
    [(None, None, False), ("1", None, True), (None, "test", True), ("0", "test", False)],
)
def test_you_mcp_is_opt_in(
    monkeypatch: pytest.MonkeyPatch, enabled: str | None, key: str | None, expected: bool
) -> None:
    for name in (
        "YDC_ENABLED",
        "YDC_API_KEY",
        "TAVILY_API_KEY",
        "BRAVE_API_KEY",
        "JINA_API_KEY",
        "FIRECRAWL_API_KEY",
        "PLAYWRIGHT_MCP",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("EXCALIDRAW_ENABLED", "0")
    if enabled is not None:
        monkeypatch.setenv("YDC_ENABLED", enabled)
    if key is not None:
        monkeypatch.setenv("YDC_API_KEY", key)
    assert [server.prefix for server in config.create_mcp_servers()] == (
        ["you"] if expected else []
    )
