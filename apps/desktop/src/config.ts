// Resolve the gateway endpoint + bearer token.
//
// Three supply paths, in priority order:
//   1. window.__GATEWAY__  — injected by the gateway when it serves the SPA,
//      or by the desktop shell (Tauri/pywebview) before loading the page.
//   2. ?token=&port=       — query params (handy in `vite dev`).
//   3. location.origin     — same-origin fallback (token then empty).

interface InjectedGateway {
  token?: string;
  base?: string;
}

const injected = (window as unknown as { __GATEWAY__?: InjectedGateway }).__GATEWAY__;
const params = new URLSearchParams(window.location.search);
const port = params.get("port");

export const TOKEN: string = injected?.token ?? params.get("token") ?? "";

export const BASE: string =
  injected?.base ?? (port ? `http://127.0.0.1:${port}` : window.location.origin);

export const WS_BASE: string = BASE.replace(/^http/, "ws");
