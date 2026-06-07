import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { PrefsProvider } from "./prefs";
import { ToastProvider } from "./toast";
import "highlight.js/styles/github-dark.css";
import "./styles.css";

// Prevent the webview from zooming (Ctrl/Cmd + wheel, Ctrl/Cmd +/-/0, pinch),
// which would otherwise "grow" the whole app while scrolling the chat.
window.addEventListener(
  "wheel",
  (e) => {
    if (e.ctrlKey || e.metaKey) e.preventDefault();
  },
  { passive: false },
);
window.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && ["+", "-", "=", "0"].includes(e.key)) e.preventDefault();
});
document.addEventListener("gesturestart", (e) => e.preventDefault());

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <PrefsProvider>
        <ToastProvider>
          <App />
        </ToastProvider>
      </PrefsProvider>
    </StrictMode>,
  );
}
