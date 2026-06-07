// pydantic-deep desktop shell (Tauri 2).
//
// Responsibilities of the native shell (kept thin — the agent lives in Python):
//   * spawn the Python gateway as a managed child process,
//   * read its advertised {"port", "token"} JSON line from stdout,
//   * inject that into the webview as `window.__GATEWAY__` before the SPA loads,
//   * own window lifecycle and kill the gateway on exit.
//
// The gateway command is resolved from the PYDANTIC_DEEP_PYTHON env var (so a
// bundled standalone CPython can be pointed at) or falls back to `python`.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use serde::Deserialize;
use tauri::{Manager, WebviewWindowBuilder, WebviewUrl};

#[derive(Deserialize)]
struct GatewayInfo {
    port: u16,
    token: String,
}

struct GatewayProcess(Mutex<Option<Child>>);

fn spawn_gateway() -> Result<(GatewayInfo, Child), String> {
    let python = std::env::var("PYDANTIC_DEEP_PYTHON").unwrap_or_else(|_| "python".to_string());
    let mut child = Command::new(python)
        .args(["-m", "apps.gateway", "--port", "0"])
        .stdout(Stdio::piped())
        .spawn()
        .map_err(|e| format!("failed to start gateway: {e}"))?;

    let stdout = child.stdout.take().ok_or("gateway produced no stdout")?;
    let mut reader = BufReader::new(stdout);
    let mut line = String::new();
    reader
        .read_line(&mut line)
        .map_err(|e| format!("failed to read gateway handshake: {e}"))?;
    let info: GatewayInfo =
        serde_json::from_str(line.trim()).map_err(|e| format!("bad gateway handshake: {e}"))?;
    Ok((info, child))
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let (info, child) = spawn_gateway().expect("gateway must start");
            app.manage(GatewayProcess(Mutex::new(Some(child))));

            let url = format!("http://127.0.0.1:{}/?token={}", info.port, info.token);
            let init = format!(
                "window.__GATEWAY__ = {{ token: {:?}, base: \"http://127.0.0.1:{}\" }};",
                info.token, info.port
            );

            WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url.parse().unwrap()))
                .title("pydantic-deep")
                .inner_size(1200.0, 820.0)
                .initialization_script(&init)
                .build()?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(state) = window.app_handle().try_state::<GatewayProcess>() {
                    if let Ok(mut guard) = state.0.lock() {
                        if let Some(mut child) = guard.take() {
                            let _ = child.kill();
                        }
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
