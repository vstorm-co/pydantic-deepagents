# pydantic-deep Gateway

A local **HTTP + WebSocket** service that exposes the pydantic-deep agent to any
web/desktop frontend. It drives the *same* agent core the CLI and ACP adapter
use, through the shared [`pydantic_deep.session`](../../pydantic_deep/session)
streaming layer.

```bash
pip install 'pydantic-deep[gateway]'
python -m apps.gateway --port 0        # 0 = OS-assigned free port
```

On start it prints a single JSON line so a parent process can connect:

```json
{"port": 62963, "token": "…"}
```

## Security

- Binds to **127.0.0.1 only**.
- Every REST call needs `Authorization: Bearer <token>`; the WebSocket needs
  `?token=<token>`. The token is generated at launch (or passed via
  `PYDANTIC_DEEP_GATEWAY_TOKEN`).
- The built SPA (`apps/desktop/dist`) is served at `/` when present.

## REST API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | liveness (no auth) |
| `GET` | `/version` | version (no auth) |
| `GET` | `/config` | current `CliConfig` values |
| `GET` | `/config/schema` | field list (drives the settings UI) |
| `PUT` | `/config` | set a config key |
| `GET` | `/sessions` | list sessions |
| `POST` | `/sessions` | create a session |
| `GET` | `/sessions/{id}` | session info |
| `DELETE` | `/sessions/{id}` | delete a session |
| `PUT` | `/sessions/{id}/name` | rename |
| `POST` | `/sessions/{id}/cancel` | cancel the in-flight turn |
| `POST` | `/sessions/{id}/prompt` | non-streaming turn (returns the outcome) |

## WebSocket — `/ws/{session_id}?token=…`

**Client → server**

```json
{"action": "prompt", "text": "…"}
{"action": "cancel"}
```

**Server → client** — one JSON object per [`SessionEvent`](../../pydantic_deep/session/events.py),
discriminated on `type`: `run_started`, `text_delta`, `thinking_delta`,
`tool_call_started`, `tool_call_result`, `run_completed`, `run_cancelled`,
`run_error`. Cancellation is processed concurrently with an in-flight turn.

## Architecture

```
frontend ── REST + WS ──▶ gateway ── in-process ──▶ create_cli_agent() ──▶ pydantic_deep
                              │
                              └─ SessionManager (lifecycle, history, cancel)
                                   └─ pydantic_deep.session.run_session (shared stream)
```
