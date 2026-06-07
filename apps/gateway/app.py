"""FastAPI application factory for the pydantic-deep gateway.

REST for session/config management + a WebSocket per session that streams the
shared `pydantic_deep.session` event protocol. Cancellation is processed
concurrently with an in-flight turn by running the turn as a task.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import fields
from pathlib import Path
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from apps.gateway.auth import extract_bearer, generate_token, token_valid
from apps.gateway.schemas import (
    AgentBody,
    AgentSelect,
    ConfigUpdate,
    ControlsUpdate,
    CreateSessionRequest,
    CwdUpdate,
    KeyUpdate,
    ModelUpdate,
    PromptRequest,
    RenameRequest,
    SessionInfo,
    SkillBody,
    event_to_dict,
)
from apps.gateway.session_manager import SessionManager

# WebSocket close code for auth failure (application range).
WS_UNAUTHORIZED = 4401

# Built SPA location (apps/desktop/dist). Served when present so the gateway is
# a complete app on its own; absent in a source checkout before `npm run build`.
_DIST_DIR = Path(__file__).resolve().parent.parent / "desktop" / "dist"


def _session_info(session: Any) -> SessionInfo:
    return SessionInfo(
        id=session.id,
        model=session.model,
        cwd=session.cwd,
        name=session.name,
        created_at=session.created_at,
        message_count=session.message_count,
        thinking=session.controls.get("thinking"),
        temperature=session.controls.get("temperature"),
        agent_id=session.agent_id,
        agent_name=session.agent_name,
        agent_avatar=session.agent_avatar,
        agent_color=session.agent_color,
    )


def create_app(  # noqa: C901 - a FastAPI app factory naturally nests many route closures
    *,
    token: str | None = None,
    manager: SessionManager | None = None,
) -> FastAPI:
    """Build the gateway FastAPI app.

    Args:
        token: Bearer token clients must present. Generated if omitted.
        manager: Session manager (injected in tests). Created if omitted.
    """
    app = FastAPI(title="pydantic-deep gateway", version=_app_version())
    app.state.token = token or generate_token()
    if manager is None:
        from apps.gateway.models import default_model

        manager = SessionManager(default_model=default_model())
    app.state.manager = manager

    async def _auth(request: Request) -> None:
        provided = extract_bearer(request.headers.get("authorization"))
        if not token_valid(provided, request.app.state.token):
            raise HTTPException(status_code=401, detail="Invalid or missing token")

    auth = Depends(_auth)

    # --- meta ---------------------------------------------------------------

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/version")
    async def version() -> dict[str, str]:
        return {"version": _app_version()}

    # --- config -------------------------------------------------------------

    @app.get("/config", dependencies=[auth])
    async def get_config() -> dict[str, Any]:
        from apps.cli.config import load_config

        cfg = load_config()
        return {f.name: getattr(cfg, f.name) for f in fields(cfg)}

    @app.get("/config/schema", dependencies=[auth])
    async def config_schema() -> list[dict[str, Any]]:
        from apps.cli.config import CliConfig

        out: list[dict[str, Any]] = []
        for f in fields(CliConfig):
            out.append({"name": f.name, "type": str(f.type)})
        return out

    @app.get("/models", dependencies=[auth])
    async def list_models() -> dict[str, Any]:
        from apps.gateway.models import common_models, model_catalogue

        return {"models": common_models(), "providers": model_catalogue()}

    # --- agents -------------------------------------------------------------

    @app.get("/agents", dependencies=[auth])
    async def list_agents_ep() -> list[dict[str, Any]]:
        from apps.gateway.agents import list_agents

        return list_agents()

    @app.get("/agents/default-prompt", dependencies=[auth])
    async def agent_default_prompt() -> dict[str, str]:
        from apps.gateway.agents import default_prompt

        return {"prompt": default_prompt()}

    @app.post("/agents", dependencies=[auth])
    async def create_agent_ep(body: AgentBody) -> dict[str, Any]:
        from apps.gateway.agents import create_agent

        return create_agent(body.model_dump())

    @app.put("/agents/{agent_id}", dependencies=[auth])
    async def update_agent_ep(agent_id: str, body: AgentBody) -> dict[str, Any]:
        from apps.gateway.agents import update_agent

        updated = update_agent(agent_id, body.model_dump())
        if updated is None:
            raise HTTPException(status_code=404, detail="No such agent (or built-in)")
        return updated

    @app.delete("/agents/{agent_id}", dependencies=[auth])
    async def delete_agent_ep(agent_id: str) -> dict[str, str]:
        from apps.gateway.agents import delete_agent

        if not delete_agent(agent_id):
            raise HTTPException(status_code=400, detail="Cannot delete this agent")
        return {"status": "deleted"}

    @app.put("/sessions/{session_id}/agent", dependencies=[auth])
    async def set_session_agent(session_id: str, body: AgentSelect) -> SessionInfo:
        if not app.state.manager.set_agent(session_id, body.agent_id):
            raise HTTPException(status_code=404, detail="No such session")
        return _session_info(app.state.manager.get(session_id))

    @app.get("/keys", dependencies=[auth])
    async def get_keys() -> dict[str, bool]:
        from apps.gateway.keys import key_status

        return key_status()

    @app.put("/keys", dependencies=[auth])
    async def set_key(body: KeyUpdate) -> dict[str, str]:
        from apps.gateway.keys import set_key as _set_key

        if not _set_key(body.provider, body.key):
            raise HTTPException(status_code=400, detail="Unknown provider")
        # New key → let live sessions rebuild their agent with it.
        app.state.manager.reset_all_agents()
        return {"status": "ok"}

    @app.put("/config", dependencies=[auth])
    async def update_config(body: ConfigUpdate) -> dict[str, str]:
        from apps.cli.config import DEFAULT_CONFIG_PATH, set_config_value

        set_config_value(DEFAULT_CONFIG_PATH, body.key, str(body.value))
        return {"status": "ok"}

    # --- skills -------------------------------------------------------------

    @app.get("/skills", dependencies=[auth])
    async def list_skills() -> list[dict[str, Any]]:
        from apps.gateway.skills import discover_skills

        return discover_skills()

    @app.post("/skills", dependencies=[auth])
    async def create_skill_ep(body: SkillBody) -> dict[str, Any]:
        from apps.gateway.skills import create_skill

        return create_skill(body.name, body.description, body.content)

    @app.get("/skills/{name}", dependencies=[auth])
    async def get_skill(name: str) -> dict[str, str]:
        from apps.gateway.skills import read_skill

        content = read_skill(name)
        if content is None:
            raise HTTPException(status_code=404, detail="No such skill")
        return {"name": name, "content": content}

    # --- sessions -----------------------------------------------------------

    @app.get("/sessions", dependencies=[auth])
    async def list_sessions() -> list[SessionInfo]:
        return [_session_info(s) for s in app.state.manager.list()]

    @app.post("/sessions", dependencies=[auth])
    async def create_session(body: CreateSessionRequest) -> SessionInfo:
        session = app.state.manager.create(
            cwd=body.cwd, model=body.model, name=body.name, agent_id=body.agent_id
        )
        return _session_info(session)

    @app.get("/sessions/{session_id}", dependencies=[auth])
    async def get_session(session_id: str) -> SessionInfo:
        session = app.state.manager.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="No such session")
        return _session_info(session)

    @app.get("/sessions/{session_id}/messages", dependencies=[auth])
    async def get_messages(session_id: str) -> list[dict[str, Any]]:
        session = app.state.manager.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="No such session")
        from apps.gateway.transcript import history_to_items

        return history_to_items(session.history)

    @app.delete("/sessions/{session_id}", dependencies=[auth])
    async def delete_session(session_id: str) -> dict[str, str]:
        if not app.state.manager.delete(session_id):
            raise HTTPException(status_code=404, detail="No such session")
        return {"status": "deleted"}

    @app.put("/sessions/{session_id}/name", dependencies=[auth])
    async def rename_session(session_id: str, body: RenameRequest) -> dict[str, str]:
        if not app.state.manager.rename(session_id, body.name):
            raise HTTPException(status_code=404, detail="No such session")
        return {"status": "ok"}

    @app.put("/sessions/{session_id}/model", dependencies=[auth])
    async def set_model(session_id: str, body: ModelUpdate) -> SessionInfo:
        if not app.state.manager.set_model(session_id, body.model):
            raise HTTPException(status_code=404, detail="No such session")
        return _session_info(app.state.manager.get(session_id))

    @app.put("/sessions/{session_id}/cwd", dependencies=[auth])
    async def set_cwd(session_id: str, body: CwdUpdate) -> SessionInfo:
        if not app.state.manager.set_cwd(session_id, body.path):
            raise HTTPException(status_code=404, detail="No such session")
        return _session_info(app.state.manager.get(session_id))

    @app.get("/fs", dependencies=[auth])
    async def fs_browse(path: str = Query("")) -> dict[str, Any]:
        from apps.gateway.fsbrowse import browse

        return browse(path or None)

    @app.put("/sessions/{session_id}/settings", dependencies=[auth])
    async def set_controls(session_id: str, body: ControlsUpdate) -> SessionInfo:
        controls = {k: v for k, v in body.model_dump().items() if v is not None}
        if not app.state.manager.set_controls(session_id, controls):
            raise HTTPException(status_code=404, detail="No such session")
        return _session_info(app.state.manager.get(session_id))

    @app.post("/sessions/{session_id}/cancel", dependencies=[auth])
    async def cancel_session(session_id: str) -> dict[str, bool]:
        return {"cancelled": app.state.manager.cancel(session_id)}

    @app.post("/sessions/{session_id}/upload", dependencies=[auth])
    async def upload_file(
        session_id: str,
        file: UploadFile = File(...),  # noqa: B008 - FastAPI dependency-injection idiom
    ) -> dict[str, Any]:
        session = app.state.manager.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="No such session")
        from apps.gateway.uploads import save_upload

        return save_upload(session.cwd, file.filename, await file.read())

    @app.post("/sessions/{session_id}/screenshot", dependencies=[auth])
    async def screenshot(session_id: str) -> dict[str, Any]:
        session = app.state.manager.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="No such session")
        from apps.gateway.screenshot import take_screenshot

        try:
            return take_screenshot(session.cwd)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/sessions/{session_id}/files", dependencies=[auth])
    async def list_files(session_id: str) -> list[dict[str, Any]]:
        session = app.state.manager.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="No such session")
        from apps.gateway.uploads import list_uploads

        return list_uploads(session.cwd)

    @app.post("/sessions/{session_id}/prompt", dependencies=[auth])
    async def prompt_session(session_id: str, body: PromptRequest) -> dict[str, Any]:
        """Non-streaming helper: run a turn and return the final outcome."""
        manager: SessionManager = app.state.manager

        async def _sink(_event: Any) -> None:
            return None

        try:
            outcome = await manager.run(session_id, body.text, _sink)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="No such session") from exc
        return {
            "output": outcome.output,
            "error": outcome.error,
            "cancelled": outcome.cancelled,
            "message_count": len(outcome.messages),
        }

    # --- streaming ----------------------------------------------------------

    @app.websocket("/ws/{session_id}")
    async def session_ws(websocket: WebSocket, session_id: str, token: str = Query("")) -> None:
        if not token_valid(token, websocket.app.state.token):
            await websocket.close(code=WS_UNAUTHORIZED)
            return
        manager: SessionManager = websocket.app.state.manager
        if manager.get(session_id) is None:
            await websocket.close(code=WS_UNAUTHORIZED)
            return
        await websocket.accept()

        async def sink(event: Any) -> None:
            await websocket.send_json(event_to_dict(event))

        async def run_and_report(text: str) -> None:
            await manager.run(session_id, text, sink)
            session = manager.get(session_id)
            if session is not None:
                await websocket.send_json(session.stats())

        current: asyncio.Task[Any] | None = None
        try:
            while True:
                msg = await websocket.receive_json()
                action = msg.get("action")
                if action == "prompt":
                    text = str(msg.get("text", ""))
                    current = asyncio.create_task(run_and_report(text))
                elif action == "cancel":
                    manager.cancel(session_id)
        except WebSocketDisconnect:
            pass
        finally:
            if current is not None and not current.done():
                manager.cancel(session_id)
                with contextlib.suppress(Exception):
                    await current

    # --- static SPA (optional) ---------------------------------------------
    # Mounted last so explicit API routes always win. Present only after the
    # frontend is built (`apps/desktop` → `npm run build`).
    if _DIST_DIR.exists():
        app.mount(
            "/assets",
            StaticFiles(directory=_DIST_DIR / "assets"),
            name="assets",
        )

        @app.get("/", include_in_schema=False)
        async def spa_index() -> FileResponse:
            return FileResponse(_DIST_DIR / "index.html")

    return app


def _app_version() -> str:
    try:
        from pydantic_deep import __version__

        return __version__
    except Exception:  # pragma: no cover - defensive
        return "0.0.0"


__all__ = ["WS_UNAUTHORIZED", "create_app"]
