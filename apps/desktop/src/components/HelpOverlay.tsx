import { X } from "lucide-react";

const SHORTCUTS: [string, string][] = [
  ["⌘K / Ctrl+K", "Command palette"],
  ["⌘N / Ctrl+N", "New session"],
  ["⌘, / Ctrl+,", "Settings"],
  ["?", "This help"],
  ["Enter", "Send message (configurable)"],
  ["Shift+Enter", "New line"],
  ["Esc", "Stop run / close overlay"],
];

export function HelpOverlay({ onClose }: { onClose: () => void }): JSX.Element {
  return (
    <div className="overlay" onClick={onClose}>
      <div className="panel" onClick={(e) => e.stopPropagation()}>
        <div className="panel-head">
          <h2>Keyboard shortcuts</h2>
          <button className="icon-btn" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <div className="panel-body">
          {SHORTCUTS.map(([keys, desc]) => (
            <div className="setting-row" key={keys}>
              <label>
                <span className="kbd">{keys}</span>
              </label>
              <span>{desc}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
