# pydantic-deep Desktop

A cross-platform desktop app for pydantic-deep. A **React + Vite + TypeScript**
frontend talks to the local [gateway](../gateway) over REST + WebSocket; the
agent core is never reimplemented in JS (same approach as Hermes Desktop).

Two shells are supported:

- **pywebview** (pure-Python, default) — `pydantic-deep desktop`.
- **Tauri** (native, production) — `src-tauri/` (see below).

## Run it (pywebview, fastest)

```bash
# 1. build the frontend once (needs Node ≥ 18)
cd apps/desktop && npm install && npm run build

# 2. launch the native window (needs the desktop extra)
pip install 'pydantic-deep[desktop]'
pydantic-deep desktop
```

`pydantic-deep desktop` starts the gateway on a free loopback port, waits for
health, and opens a native window pointed at `…/?token=…`.

Headless / browser fallback:

```bash
python -m apps.gateway --port 8765      # then open the printed URL with ?token=
```

## Develop the frontend

```bash
cd apps/desktop
npm run dev          # vite dev server on :5173
# in another terminal:
python -m apps.gateway --port 8765
# open http://localhost:5173/?port=8765&token=<token-from-gateway-stdout>
```

Connection config (`src/config.ts`) resolves the gateway from, in order:
`window.__GATEWAY__` (injected by a shell) → `?token=&port=` query → same-origin.

## Layout

```
apps/desktop/
├─ src/                 React app
│  ├─ App.tsx           orchestration (sessions, socket, transcript)
│  ├─ ws.ts             WebSocket client (auto-reconnect)
│  ├─ api.ts            REST client
│  ├─ chatReducer.ts    SessionEvent → chat state
│  ├─ types.ts          wire types (mirror of the gateway)
│  └─ components/        Sidebar, Composer, StatusBar, ToolCallCard, Settings
├─ launcher.py          pywebview launcher (`pydantic-deep desktop`)
├─ src-tauri/           Tauri shell (native production build)
└─ dist/                built SPA (served by the gateway; git-ignored)
```

## Tauri (native production shell)

`src-tauri/` holds a Tauri 2 shell that spawns the gateway sidecar, opens a
native webview, and provides auto-update + OS-keychain secret storage. Build:

```bash
cd apps/desktop
npm install && npm run build
cargo tauri build      # needs the Tauri CLI + platform webview deps
```

Packaging/signing/notarization is wired in CI (see `IMPLEMENTATION_PLAN_DESKTOP.md`).
