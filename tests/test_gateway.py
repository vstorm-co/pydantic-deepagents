"""Tests for the pydantic-deep gateway (REST + WebSocket)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from starlette.websockets import WebSocketDisconnect

from apps.gateway.app import create_app
from apps.gateway.auth import extract_bearer, generate_token, token_valid
from apps.gateway.session_manager import SessionManager

TOKEN = "test-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _factory(
    model: str | None,
    cwd: str | None,
    session_id: str,
    on_cost: Any,
    on_context: Any,
    controls: dict[str, Any],
) -> tuple[Any, Any]:
    agent: Agent[None, str] = Agent(model=TestModel())
    return agent, None


@pytest.fixture
def client() -> TestClient:
    manager = SessionManager(agent_factory=_factory)
    app = create_app(token=TOKEN, manager=manager)
    return TestClient(app)


# --- auth helpers ----------------------------------------------------------


class TestAuthHelpers:
    def test_generate_token_unique(self) -> None:
        assert generate_token() != generate_token()

    def test_extract_bearer(self) -> None:
        assert extract_bearer("Bearer abc") == "abc"
        assert extract_bearer("abc") == "abc"
        assert extract_bearer(None) == ""

    def test_token_valid(self) -> None:
        assert token_valid("x", "x") is True
        assert token_valid("x", "y") is False
        assert token_valid(None, "y") is False
        assert token_valid("x", "") is False


# --- meta + auth gating ----------------------------------------------------


class TestMeta:
    def test_health_no_auth(self, client: TestClient) -> None:
        assert client.get("/health").json() == {"status": "ok"}

    def test_version(self, client: TestClient) -> None:
        assert "version" in client.get("/version").json()

    def test_missing_token_rejected(self, client: TestClient) -> None:
        assert client.get("/sessions").status_code == 401

    def test_bad_token_rejected(self, client: TestClient) -> None:
        r = client.get("/sessions", headers={"Authorization": "Bearer nope"})
        assert r.status_code == 401

    def test_spa_served(self, client: TestClient) -> None:
        # The built frontend (apps/desktop/dist) is served at "/".
        r = client.get("/")
        assert r.status_code == 200
        assert '<div id="root">' in r.text or "<title>" in r.text


# --- config ----------------------------------------------------------------


class TestConfig:
    def test_get_config(self, client: TestClient) -> None:
        cfg = client.get("/config", headers=AUTH).json()
        assert "model" in cfg

    def test_config_schema(self, client: TestClient) -> None:
        schema = client.get("/config/schema", headers=AUTH).json()
        names = {f["name"] for f in schema}
        assert "model" in names and "sandbox" in names


class TestModels:
    def test_list_models(self, client: TestClient) -> None:
        body = client.get("/models", headers=AUTH).json()
        assert any("anthropic:" in m for m in body["models"])
        # Grouped by provider for the picker.
        labels = {g["label"] for g in body["providers"]}
        assert {"Anthropic", "OpenAI", "Google", "OpenRouter"} <= labels
        anthro = next(g for g in body["providers"] if g["id"] == "anthropic")
        assert any("opus" in m for m in anthro["models"])

    def test_set_model_switches(self, client: TestClient) -> None:
        sid = client.post("/sessions", json={"model": "test"}, headers=AUTH).json()["id"]
        r = client.put(
            f"/sessions/{sid}/model",
            json={"model": "anthropic:claude-haiku-4-5"},
            headers=AUTH,
        )
        assert r.status_code == 200
        assert r.json()["model"] == "anthropic:claude-haiku-4-5"
        # The change is reflected on subsequent reads.
        assert client.get(f"/sessions/{sid}", headers=AUTH).json()["model"] == (
            "anthropic:claude-haiku-4-5"
        )

    def test_set_model_unknown_session(self, client: TestClient) -> None:
        r = client.put("/sessions/nope/model", json={"model": "x"}, headers=AUTH)
        assert r.status_code == 404

    def test_set_controls(self, client: TestClient) -> None:
        sid = client.post("/sessions", json={}, headers=AUTH).json()["id"]
        r = client.put(
            f"/sessions/{sid}/settings",
            json={"thinking": "medium", "temperature": 0.7},
            headers=AUTH,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["thinking"] == "medium"
        assert body["temperature"] == 0.7

    def test_set_controls_unknown_session(self, client: TestClient) -> None:
        r = client.put("/sessions/nope/settings", json={"thinking": "low"}, headers=AUTH)
        assert r.status_code == 404


class TestKeys:
    def test_status_and_set(
        self, client: TestClient, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import os

        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("CO_API_KEY", raising=False)
        try:
            status = client.get("/keys", headers=AUTH).json()
            assert status["cohere"] is False

            r = client.put("/keys", json={"provider": "cohere", "key": "sk-test"}, headers=AUTH)
            assert r.status_code == 200
            assert os.environ["CO_API_KEY"] == "sk-test"
            env_text = (tmp_path / ".pydantic-deep" / ".env").read_text().strip()
            assert env_text == "CO_API_KEY=sk-test"
            assert client.get("/keys", headers=AUTH).json()["cohere"] is True
        finally:
            os.environ.pop("CO_API_KEY", None)

    def test_unknown_provider(self, client: TestClient) -> None:
        r = client.put("/keys", json={"provider": "nope", "key": "x"}, headers=AUTH)
        assert r.status_code == 400


class TestAgents:
    def test_list_includes_default(self, client: TestClient) -> None:
        agents = client.get("/agents", headers=AUTH).json()
        assert any(a["id"] == "default" and a["builtin"] for a in agents)

    def test_default_prompt(self, client: TestClient) -> None:
        body = client.get("/agents/default-prompt", headers=AUTH).json()
        assert len(body["prompt"]) > 100  # the framework BASE_PROMPT

    def test_crud_and_session_assignment(
        self, client: TestClient, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        created = client.post(
            "/agents",
            json={"name": "Reviewer", "avatar": "🔍", "color": "#f00", "prompt": "Be picky."},
            headers=AUTH,
        ).json()
        aid = created["id"]
        assert created["name"] == "Reviewer" and not created["builtin"]

        # Assign to a new session — name/avatar/prompt flow through.
        sess = client.post("/sessions", json={"agent_id": aid}, headers=AUTH).json()
        assert sess["agent_name"] == "Reviewer"
        assert sess["agent_avatar"] == "🔍"

        # Switch an existing session's agent back to default.
        switched = client.put(
            f"/sessions/{sess['id']}/agent", json={"agent_id": "default"}, headers=AUTH
        ).json()
        assert switched["agent_id"] == "default"

        # Update + delete.
        upd = client.put(
            f"/agents/{aid}",
            json={"name": "Reviewer 2", "avatar": "🧐", "color": "#0f0", "prompt": "x"},
            headers=AUTH,
        ).json()
        assert upd["name"] == "Reviewer 2"
        assert client.delete(f"/agents/{aid}", headers=AUTH).status_code == 200

    def test_cannot_delete_default(self, client: TestClient) -> None:
        assert client.delete("/agents/default", headers=AUTH).status_code == 400

    def test_update_unknown_agent(
        self, client: TestClient, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        r = client.put("/agents/nope", json={"name": "x"}, headers=AUTH)
        assert r.status_code == 404

    def test_set_agent_unknown_session(self, client: TestClient) -> None:
        r = client.put("/sessions/nope/agent", json={"agent_id": "default"}, headers=AUTH)
        assert r.status_code == 404


class TestAutoNaming:
    def test_name_from_user_message(self, client: TestClient) -> None:
        sid = client.post("/sessions", json={}, headers=AUTH).json()["id"]
        client.post(f"/sessions/{sid}/prompt", json={"text": "Fix the login bug"}, headers=AUTH)
        assert client.get(f"/sessions/{sid}", headers=AUTH).json()["name"] == "Fix the login bug"

    def test_manual_rename_sticks(self, client: TestClient) -> None:
        sid = client.post("/sessions", json={}, headers=AUTH).json()["id"]
        client.put(f"/sessions/{sid}/name", json={"name": "Custom"}, headers=AUTH)
        client.post(f"/sessions/{sid}/prompt", json={"text": "another message"}, headers=AUTH)
        assert client.get(f"/sessions/{sid}", headers=AUTH).json()["name"] == "Custom"


class TestSkills:
    def test_list_skills(self, client: TestClient) -> None:
        skills = client.get("/skills", headers=AUTH).json()
        names = {s["name"] for s in skills}
        # Bundled skills ship with the repo.
        assert "code-review" in names

    def test_get_skill(self, client: TestClient) -> None:
        body = client.get("/skills/code-review", headers=AUTH).json()
        assert body["name"] == "code-review"
        assert len(body["content"]) > 0

    def test_get_unknown_skill(self, client: TestClient) -> None:
        assert client.get("/skills/nope-nope", headers=AUTH).status_code == 404

    def test_create_skill(
        self, client: TestClient, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        r = client.post(
            "/skills",
            json={"name": "My Deploy", "description": "Ship it", "content": "# Steps\n1. go"},
            headers=AUTH,
        ).json()
        assert r["name"] == "my-deploy"
        md = (tmp_path / ".pydantic-deep" / "skills" / "my-deploy" / "SKILL.md").read_text()
        assert "name: My Deploy" in md and "# Steps" in md


class TestUpload:
    def test_upload_writes_file(self, client: TestClient, tmp_path: Any) -> None:
        sid = client.post("/sessions", json={"cwd": str(tmp_path)}, headers=AUTH).json()["id"]
        files = {"file": ("note.txt", b"hello upload", "text/plain")}
        r = client.post(f"/sessions/{sid}/upload", files=files, headers=AUTH).json()
        assert r["path"] == "uploads/note.txt"
        assert r["size"] == 12
        assert (tmp_path / "uploads" / "note.txt").read_bytes() == b"hello upload"

    def test_upload_sanitizes_name(self, client: TestClient, tmp_path: Any) -> None:
        sid = client.post("/sessions", json={"cwd": str(tmp_path)}, headers=AUTH).json()["id"]
        files = {"file": ("../../evil.txt", b"x", "text/plain")}
        r = client.post(f"/sessions/{sid}/upload", files=files, headers=AUTH).json()
        assert r["name"] == "evil.txt"
        assert (tmp_path / "uploads" / "evil.txt").exists()

    def test_upload_unknown_session(self, client: TestClient) -> None:
        files = {"file": ("x.txt", b"x", "text/plain")}
        assert client.post("/sessions/nope/upload", files=files, headers=AUTH).status_code == 404

    def test_list_files(self, client: TestClient, tmp_path: Any) -> None:
        sid = client.post("/sessions", json={"cwd": str(tmp_path)}, headers=AUTH).json()["id"]
        assert client.get(f"/sessions/{sid}/files", headers=AUTH).json() == []
        client.post(
            f"/sessions/{sid}/upload",
            files={"file": ("a.txt", b"hi", "text/plain")},
            headers=AUTH,
        )
        listed = client.get(f"/sessions/{sid}/files", headers=AUTH).json()
        assert listed[0]["name"] == "a.txt" and listed[0]["size"] == 2

    def test_list_files_unknown_session(self, client: TestClient) -> None:
        assert client.get("/sessions/nope/files", headers=AUTH).status_code == 404


class TestFilesystem:
    def test_browse(self, client: TestClient, tmp_path: Any) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "a.txt").write_text("x")
        body = client.get("/fs", params={"path": str(tmp_path)}, headers=AUTH).json()
        assert body["path"] == str(tmp_path)
        names = {e["name"]: e["is_dir"] for e in body["entries"]}
        assert names["sub"] is True and names["a.txt"] is False
        # Directories sort before files.
        assert body["entries"][0]["name"] == "sub"

    def test_browse_defaults_home(self, client: TestClient) -> None:
        body = client.get("/fs", headers=AUTH).json()
        assert "entries" in body and "path" in body

    def test_set_cwd(self, client: TestClient, tmp_path: Any) -> None:
        sid = client.post("/sessions", json={}, headers=AUTH).json()["id"]
        r = client.put(f"/sessions/{sid}/cwd", json={"path": str(tmp_path)}, headers=AUTH)
        assert r.status_code == 200
        assert r.json()["cwd"] == str(tmp_path)

    def test_set_cwd_unknown(self, client: TestClient) -> None:
        r = client.put("/sessions/nope/cwd", json={"path": "/tmp"}, headers=AUTH)
        assert r.status_code == 404

    def test_screenshot_unknown_session(self, client: TestClient) -> None:
        assert client.post("/sessions/nope/screenshot", headers=AUTH).status_code == 404


# --- session lifecycle -----------------------------------------------------


class TestSessions:
    def test_crud_flow(self, client: TestClient) -> None:
        created = client.post("/sessions", json={"model": "test"}, headers=AUTH).json()
        sid = created["id"]
        assert created["model"] == "test"

        listed = client.get("/sessions", headers=AUTH).json()
        assert any(s["id"] == sid for s in listed)

        got = client.get(f"/sessions/{sid}", headers=AUTH).json()
        assert got["id"] == sid

        ren = client.put(f"/sessions/{sid}/name", json={"name": "My session"}, headers=AUTH)
        assert ren.status_code == 200
        assert client.get(f"/sessions/{sid}", headers=AUTH).json()["name"] == "My session"

        deleted = client.delete(f"/sessions/{sid}", headers=AUTH)
        assert deleted.status_code == 200
        assert client.get(f"/sessions/{sid}", headers=AUTH).status_code == 404

    def test_unknown_session_404s(self, client: TestClient) -> None:
        assert client.get("/sessions/nope", headers=AUTH).status_code == 404
        assert client.delete("/sessions/nope", headers=AUTH).status_code == 404
        assert (
            client.put("/sessions/nope/name", json={"name": "x"}, headers=AUTH).status_code == 404
        )

    def test_cancel_unknown(self, client: TestClient) -> None:
        r = client.post("/sessions/nope/cancel", headers=AUTH)
        assert r.json() == {"cancelled": False}

    def test_prompt_helper(self, client: TestClient) -> None:
        sid = client.post("/sessions", json={}, headers=AUTH).json()["id"]
        r = client.post(f"/sessions/{sid}/prompt", json={"text": "hi"}, headers=AUTH).json()
        assert r["error"] is None
        assert r["cancelled"] is False
        assert r["message_count"] > 0

    def test_prompt_unknown_session(self, client: TestClient) -> None:
        r = client.post("/sessions/nope/prompt", json={"text": "hi"}, headers=AUTH)
        assert r.status_code == 404


class TestLazyAgentBuild:
    def test_create_succeeds_then_prompt_surfaces_key_error(self) -> None:
        # Simulate a missing API key: the agent factory raises only at build
        # time. Creating a session must still succeed (lazy build); the error
        # surfaces on the first prompt as a friendly message.
        def _failing(
            model: str | None,
            cwd: str | None,
            sid: str,
            on_cost: Any,
            on_context: Any,
            controls: dict[str, Any],
        ) -> tuple[Any, Any]:
            raise RuntimeError("Set the `ANTHROPIC_API_KEY` environment variable")

        manager = SessionManager(agent_factory=_failing)
        client = TestClient(create_app(token=TOKEN, manager=manager))

        sid = client.post("/sessions", json={}, headers=AUTH).json()["id"]
        r = client.post(f"/sessions/{sid}/prompt", json={"text": "hi"}, headers=AUTH).json()
        assert r["error"] is not None
        assert "API key" in r["error"]

    def test_messages_after_prompt(self, client: TestClient) -> None:
        sid = client.post("/sessions", json={}, headers=AUTH).json()["id"]
        client.post(f"/sessions/{sid}/prompt", json={"text": "hello there"}, headers=AUTH)
        items = client.get(f"/sessions/{sid}/messages", headers=AUTH).json()
        assert any(i["kind"] == "user" and i["text"] == "hello there" for i in items)
        assert any(i["kind"] == "assistant" for i in items)

    def test_messages_unknown_session(self, client: TestClient) -> None:
        assert client.get("/sessions/nope/messages", headers=AUTH).status_code == 404


# --- websocket -------------------------------------------------------------


class TestWebSocket:
    def test_stream_prompt(self, client: TestClient) -> None:
        sid = client.post("/sessions", json={}, headers=AUTH).json()["id"]
        with client.websocket_connect(f"/ws/{sid}?token={TOKEN}") as ws:
            ws.send_json({"action": "prompt", "text": "hello"})
            types: list[str] = []
            for _ in range(50):
                event = ws.receive_json()
                types.append(event["type"])
                if event["type"] in ("run_completed", "run_error"):
                    break
            assert types[0] == "run_started"
            assert "run_completed" in types
            # A session_stats event follows the completed turn.
            stats = ws.receive_json()
            assert stats["type"] == "session_stats"
            assert "message_count" in stats

    def test_bad_token_closes(self, client: TestClient) -> None:
        sid = client.post("/sessions", json={}, headers=AUTH).json()["id"]
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(f"/ws/{sid}?token=wrong") as ws,
        ):
            ws.receive_json()

    def test_unknown_session_closes(self, client: TestClient) -> None:
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(f"/ws/nope?token={TOKEN}") as ws,
        ):
            ws.receive_json()
