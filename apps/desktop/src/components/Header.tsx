import { FolderOpen, PanelLeft, Terminal } from "lucide-react";
import { useState } from "react";
import type { Controls, SessionInfo } from "../types";
import type { SocketStatus } from "../ws";
import { AgentPicker } from "./AgentPicker";
import { ModelPicker } from "./ModelPicker";
import { QuickSettings } from "./QuickSettings";

export function Header({
  session,
  status,
  onRename,
  onModelChange,
  onControlsChange,
  onAgentChange,
  onManageAgents,
  onOpenPalette,
  onToggleSidebar,
  onOpenFolder,
}: {
  session: SessionInfo | undefined;
  status: SocketStatus;
  onRename: (name: string) => void;
  onModelChange: (model: string) => void;
  onControlsChange: (controls: Controls) => void;
  onAgentChange: (agentId: string) => void;
  onManageAgents: () => void;
  onOpenPalette: () => void;
  onToggleSidebar: () => void;
  onOpenFolder: () => void;
}): JSX.Element {
  const cwd = session?.cwd ?? ".";
  const folderName = cwd === "." ? "." : cwd.split("/").filter(Boolean).pop() || "/";
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  const title = session?.name ?? (session ? "New chat" : "No session");

  const commit = (): void => {
    setEditing(false);
    const trimmed = draft.trim();
    if (trimmed && trimmed !== title) onRename(trimmed);
  };

  return (
    <div className="header">
      <button className="icon-btn" title="Toggle sidebar (⌘B)" onClick={onToggleSidebar}>
        <PanelLeft size={17} />
      </button>
      <span className={`dot dot-${status}`} />
      {editing ? (
        <input
          className="title-input"
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") setEditing(false);
          }}
        />
      ) : (
        <span
          className="title"
          title="Click to rename"
          onClick={() => {
            if (!session) return;
            setDraft(title);
            setEditing(true);
          }}
        >
          {title}
        </span>
      )}
      <button className="model-pill" title={`Working folder: ${cwd}`} onClick={onOpenFolder}>
        <FolderOpen size={13} /> {folderName}
      </button>
      <span className="spacer" />
      {session ? (
        <AgentPicker session={session} onSelect={onAgentChange} onManage={onManageAgents} />
      ) : null}
      {session ? <QuickSettings session={session} onChange={onControlsChange} /> : null}
      {session ? <ModelPicker current={session.model} onSelect={onModelChange} /> : null}
      <button className="model-pill icon-pill" onClick={onOpenPalette} title="Command palette (⌘K)">
        <Terminal size={14} />
      </button>
    </div>
  );
}
