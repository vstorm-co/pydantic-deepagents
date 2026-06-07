import { ChevronDown, Settings as SettingsIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Agent, SessionInfo } from "../types";
import { AgentAvatar } from "./AgentAvatar";

export function AgentPicker({
  session,
  onSelect,
  onManage,
}: {
  session: SessionInfo | undefined;
  onSelect: (agentId: string) => void;
  onManage: () => void;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  const [agents, setAgents] = useState<Agent[]>([]);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (open) api.getAgents().then(setAgents).catch(() => undefined);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent): void => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <div className="model-picker" ref={ref}>
      <button className="agent-pill" title="Agent" onClick={() => setOpen((o) => !o)}>
        <AgentAvatar
          avatar={session?.agent_avatar ?? ""}
          color={session?.agent_color ?? "#4493f8"}
          size={20}
        />
        {session?.agent_name ?? "Assistant"}
        <ChevronDown size={13} />
      </button>
      {open ? (
        <div className="model-dropdown">
          {agents.map((a) => (
            <div
              key={a.id}
              className={`agent-option ${a.id === session?.agent_id ? "active" : ""}`}
              onClick={() => {
                setOpen(false);
                onSelect(a.id);
              }}
            >
              <AgentAvatar avatar={a.avatar} color={a.color} size={20} />
              {a.name}
            </div>
          ))}
          <div className="model-custom">
            <button
              className="settings-btn"
              style={{ width: "100%" }}
              onClick={() => {
                setOpen(false);
                onManage();
              }}
            >
              <SettingsIcon size={14} /> Manage agents…
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
