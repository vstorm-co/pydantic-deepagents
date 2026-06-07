import { Hexagon, HelpCircle, Plus, Settings as SettingsIcon, Star, Terminal, X } from "lucide-react";
import { useMemo, useState } from "react";
import { AgentAvatar } from "./AgentAvatar";
import type { SessionInfo } from "../types";

function bucket(createdAtSec: number): string {
  const now = Date.now();
  const ts = createdAtSec * 1000;
  const day = 86400000;
  const startOfToday = new Date().setHours(0, 0, 0, 0);
  if (ts >= startOfToday) return "Today";
  if (ts >= startOfToday - day) return "Yesterday";
  if (now - ts < 7 * day) return "Previous 7 days";
  return "Older";
}

const ORDER = ["Pinned", "Today", "Yesterday", "Previous 7 days", "Older"];

export function Sidebar({
  sessions,
  selectedId,
  pinned,
  onSelect,
  onCreate,
  onDelete,
  onTogglePin,
  onOpenSettings,
  onOpenPalette,
  onOpenHelp,
}: {
  sessions: SessionInfo[];
  selectedId: string | null;
  pinned: string[];
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: (id: string) => void;
  onTogglePin: (id: string) => void;
  onOpenSettings: () => void;
  onOpenPalette: () => void;
  onOpenHelp: () => void;
}): JSX.Element {
  const [query, setQuery] = useState("");
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const groups = useMemo(() => {
    const q = query.toLowerCase().trim();
    const matched = q
      ? sessions.filter((s) => (s.name ?? "new chat").toLowerCase().includes(q))
      : sessions;
    const map = new Map<string, SessionInfo[]>();
    for (const s of matched) {
      const key = pinned.includes(s.id) ? "Pinned" : bucket(s.created_at);
      (map.get(key) ?? map.set(key, []).get(key)!).push(s);
    }
    return ORDER.filter((g) => map.has(g)).map((g) => ({ label: g, items: map.get(g)! }));
  }, [sessions, query, pinned]);

  return (
    <>
      <div className="sidebar-head">
        <span className="brand">
          <span className="brand-mark">
            <Hexagon size={14} fill="currentColor" />
          </span>
          <span className="brand-text">
            pydantic<span className="brand-dim">·</span>deep
          </span>
        </span>
        <button className="new-chat-btn" title="New session (⌘N)" onClick={onCreate}>
          <Plus size={14} /> New
        </button>
      </div>
      {sessions.length > 4 ? (
        <input
          className="search-box"
          placeholder="Search chats…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      ) : null}
      <div className="session-list">
        {groups.map((g) => (
          <div key={g.label} className="session-group">
            <div className="group-label">{g.label}</div>
            {g.items.map((s) => (
              <div
                key={s.id}
                className={`session-row ${s.id === selectedId ? "active" : ""}`}
                onClick={() => onSelect(s.id)}
              >
                <AgentAvatar avatar={s.agent_avatar} color={s.agent_color} size={22} />
                <span className="session-name">{s.name ?? "New chat"}</span>
                <button
                  className={`pin-btn ${pinned.includes(s.id) ? "pinned" : ""}`}
                  title={pinned.includes(s.id) ? "Unpin" : "Pin"}
                  onClick={(e) => {
                    e.stopPropagation();
                    onTogglePin(s.id);
                  }}
                >
                  <Star size={13} fill={pinned.includes(s.id) ? "currentColor" : "none"} />
                </button>
                <button
                  className={`icon-btn small ${confirmId === s.id ? "confirm" : ""}`}
                  title="Delete"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (confirmId === s.id) {
                      onDelete(s.id);
                      setConfirmId(null);
                    } else {
                      setConfirmId(s.id);
                      window.setTimeout(() => setConfirmId((c) => (c === s.id ? null : c)), 2500);
                    }
                  }}
                >
                  {confirmId === s.id ? "Sure?" : <X size={13} />}
                </button>
              </div>
            ))}
          </div>
        ))}
        {groups.length === 0 ? <div className="muted pad">No chats</div> : null}
      </div>
      <div className="sidebar-foot">
        <button className="settings-btn" onClick={onOpenSettings} title="Settings">
          <SettingsIcon size={16} />
        </button>
        <button className="settings-btn" onClick={onOpenPalette} title="Command palette (⌘K)">
          <Terminal size={16} />
        </button>
        <button className="settings-btn" onClick={onOpenHelp} title="Shortcuts (?)">
          <HelpCircle size={16} />
        </button>
      </div>
    </>
  );
}
