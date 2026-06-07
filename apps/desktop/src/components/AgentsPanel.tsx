import { ImagePlus, Plus, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useToast } from "../toast";
import type { Agent } from "../types";
import { AgentAvatar } from "./AgentAvatar";

const COLORS = ["#4493f8", "#3fb950", "#bc8cff", "#f778ba", "#ff8c42", "#56d4dd", "#e3b341"];

interface Draft {
  name: string;
  avatar: string;
  color: string;
  prompt: string;
}

export function AgentsPanel({
  onClose,
  onChanged,
}: {
  onClose: () => void;
  onChanged: () => void;
}): JSX.Element {
  const toast = useToast();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [editing, setEditing] = useState<Agent | "new" | null>(null);
  const [defaultPrompt, setDefaultPrompt] = useState("");

  const load = (): void => {
    api
      .getAgents()
      .then(setAgents)
      .catch((e) => toast.push(String(e), "error"));
  };
  useEffect(load, [toast]);
  useEffect(() => {
    api.getDefaultPrompt().then((r) => setDefaultPrompt(r.prompt)).catch(() => undefined);
  }, []);

  if (editing) {
    const base: Draft =
      editing === "new"
        ? { name: "", avatar: "", color: "#4493f8", prompt: "" }
        : { name: editing.name, avatar: editing.avatar, color: editing.color, prompt: editing.prompt };
    return (
      <AgentEditor
        draft={base}
        isNew={editing === "new"}
        defaultPrompt={defaultPrompt}
        onCancel={() => setEditing(null)}
        onSave={async (d) => {
          try {
            if (editing === "new") await api.createAgent(d);
            else await api.updateAgent(editing.id, d);
            setEditing(null);
            load();
            onChanged();
            toast.push("Agent saved", "success");
          } catch (e) {
            toast.push(String(e), "error");
          }
        }}
      />
    );
  }

  return (
    <div className="overlay" onClick={onClose}>
      <div className="panel" onClick={(e) => e.stopPropagation()}>
        <div className="panel-head">
          <h2>Agents</h2>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="send-btn" style={{ padding: "6px 12px" }} onClick={() => setEditing("new")}>
              <Plus size={14} /> New
            </button>
            <button className="icon-btn" onClick={onClose}>
              <X size={18} />
            </button>
          </div>
        </div>
        <div className="panel-body">
          {agents.map((a) => (
            <div className="agent-row" key={a.id}>
              <AgentAvatar avatar={a.avatar} color={a.color} size={36} />

              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600 }}>{a.name}</div>
                <div className="muted" style={{ fontSize: 12 }}>
                  {a.builtin ? "Built-in · framework prompt (tools)" : a.prompt ? "Custom prompt" : "Default prompt"}
                </div>
              </div>
              {!a.builtin ? (
                <>
                  <button className="settings-btn" style={{ flex: "none" }} onClick={() => setEditing(a)}>
                    Edit
                  </button>
                  <button
                    className="settings-btn"
                    style={{ flex: "none" }}
                    onClick={async () => {
                      await api.deleteAgent(a.id);
                      load();
                      onChanged();
                    }}
                  >
                    <X size={14} />
                  </button>
                </>
              ) : (
                <span className="muted" style={{ fontSize: 11 }}>built-in</span>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function AgentEditor({
  draft,
  isNew,
  defaultPrompt,
  onCancel,
  onSave,
}: {
  draft: Draft;
  isNew: boolean;
  defaultPrompt: string;
  onCancel: () => void;
  onSave: (d: Draft) => void;
}): JSX.Element {
  const [d, setD] = useState<Draft>(draft);
  const set = <K extends keyof Draft>(k: K, v: Draft[K]): void => setD((p) => ({ ...p, [k]: v }));
  const imgRef = useRef<HTMLInputElement | null>(null);

  const onImage = (file: File): void => {
    const reader = new FileReader();
    reader.onload = () => set("avatar", String(reader.result));
    reader.readAsDataURL(file);
  };

  return (
    <div className="overlay" onClick={onCancel}>
      <div className="panel" onClick={(e) => e.stopPropagation()}>
        <div className="panel-head">
          <h2>{isNew ? "New agent" : "Edit agent"}</h2>
          <button className="icon-btn" onClick={onCancel}>
            <X size={18} />
          </button>
        </div>
        <div className="panel-body">
          <div className="agent-preview">
            <AgentAvatar avatar={d.avatar} color={d.color} size={48} />
            <input
              className="title-input"
              style={{ fontSize: 16 }}
              placeholder="Agent name"
              value={d.name}
              onChange={(e) => set("name", e.target.value)}
            />
          </div>
          <div className="quick-label" style={{ marginTop: 12 }}>
            Avatar
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <button className="settings-btn" style={{ flex: "none" }} onClick={() => imgRef.current?.click()}>
              <ImagePlus size={15} /> Upload image
            </button>
            {d.avatar ? (
              <button className="settings-btn" style={{ flex: "none" }} onClick={() => set("avatar", "")}>
                Remove
              </button>
            ) : null}
            <input
              ref={imgRef}
              type="file"
              accept="image/*"
              style={{ display: "none" }}
              onChange={(e) => {
                if (e.target.files?.[0]) onImage(e.target.files[0]);
                e.target.value = "";
              }}
            />
          </div>
          <div className="quick-label" style={{ marginTop: 12 }}>
            Color
          </div>
          <div className="swatches">
            {COLORS.map((c) => (
              <span
                key={c}
                className={`swatch ${d.color === c ? "active" : ""}`}
                style={{ background: c }}
                onClick={() => set("color", c)}
              />
            ))}
          </div>
          <div className="quick-label" style={{ marginTop: 12 }}>
            System prompt <span className="muted">(blank = framework default with tool descriptions)</span>
          </div>
          <textarea
            className="agent-prompt"
            placeholder={defaultPrompt.slice(0, 300) + "…"}
            value={d.prompt}
            onChange={(e) => set("prompt", e.target.value)}
          />
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button className="send-btn" disabled={!d.name.trim()} onClick={() => onSave(d)}>
              Save
            </button>
            <button className="settings-btn" style={{ flex: "none" }} onClick={onCancel}>
              Cancel
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
