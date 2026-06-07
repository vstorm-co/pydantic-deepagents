import {
  Copy,
  FileText,
  Globe,
  Loader2,
  Pencil,
  Search,
  Terminal,
  Wrench,
} from "lucide-react";
import { useState } from "react";
import { usePrefs } from "../prefs";
import type { ToolCall } from "../types";

function KindIcon({ kind }: { kind: string }): JSX.Element {
  const size = 15;
  switch (kind) {
    case "read":
      return <FileText size={size} />;
    case "edit":
      return <Pencil size={size} />;
    case "search":
      return <Search size={size} />;
    case "execute":
      return <Terminal size={size} />;
    case "fetch":
      return <Globe size={size} />;
    default:
      return <Wrench size={size} />;
  }
}

export function ToolCallCard({ tool }: { tool: ToolCall }): JSX.Element {
  const { prefs } = usePrefs();
  const [open, setOpen] = useState(!prefs.toolsCollapsed);
  const hasResult = Boolean(tool.result);

  const copy = (e: React.MouseEvent): void => {
    e.stopPropagation();
    void navigator.clipboard.writeText(tool.result ?? "");
  };

  return (
    <div className={`tool tool-${tool.status}`}>
      <div className="tool-head" onClick={() => hasResult && setOpen((o) => !o)}>
        <span className="tool-icon">
          {tool.status === "running" ? (
            <Loader2 size={14} className="spin" />
          ) : (
            <KindIcon kind={tool.kind} />
          )}
        </span>
        <span className="tool-title">{tool.title}</span>
        {hasResult ? (
          <button className="icon-btn small" title="Copy result" onClick={copy}>
            <Copy size={13} />
          </button>
        ) : null}
        <span className={`tool-status status-${tool.status}`}>{tool.status}</span>
      </div>
      {hasResult && open ? <pre className="tool-result">{tool.result}</pre> : null}
    </div>
  );
}
