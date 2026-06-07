import { ArrowLeft, Plus, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useToast } from "../toast";
import type { Skill } from "../types";

export function SkillsPanel({
  onPick,
  onClose,
}: {
  onPick: (name: string) => void;
  onClose: () => void;
}): JSX.Element {
  const toast = useToast();
  const [skills, setSkills] = useState<Skill[]>([]);
  const [query, setQuery] = useState("");
  const [preview, setPreview] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState({ name: "", description: "", content: "" });

  const load = (): void => {
    api
      .getSkills()
      .then(setSkills)
      .catch((e) => toast.push(String(e), "error"));
  };
  useEffect(load, [toast]);

  const saveSkill = (): void => {
    if (!draft.name.trim()) return;
    api
      .createSkill(draft.name, draft.description, draft.content)
      .then(() => {
        toast.push("Skill created", "success");
        setCreating(false);
        setDraft({ name: "", description: "", content: "" });
        load();
      })
      .catch((e) => toast.push(String(e), "error"));
  };

  const filtered = useMemo(() => {
    const q = query.toLowerCase().trim();
    if (!q) return skills;
    return skills.filter(
      (s) => s.name.toLowerCase().includes(q) || s.description.toLowerCase().includes(q),
    );
  }, [skills, query]);

  const viewSkill = (name: string): void => {
    api
      .getSkill(name)
      .then((s) => setPreview(s.content))
      .catch((e) => toast.push(String(e), "error"));
  };

  return (
    <div className="overlay" onClick={onClose}>
      <div className="panel" onClick={(e) => e.stopPropagation()}>
        <div className="panel-head">
          <h2>Skills</h2>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="send-btn" style={{ padding: "6px 12px" }} onClick={() => setCreating(true)}>
              <Plus size={14} /> New
            </button>
            <button className="icon-btn" onClick={onClose}>
              <X size={18} />
            </button>
          </div>
        </div>
        {creating ? (
          <div className="panel-body">
            <input
              className="search-box"
              style={{ width: "100%", margin: "0 0 8px" }}
              placeholder="Skill name (e.g. Deploy to staging)"
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
            <input
              className="search-box"
              style={{ width: "100%", margin: "0 0 8px" }}
              placeholder="One-line description"
              value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            />
            <textarea
              className="agent-prompt"
              placeholder="Skill instructions (markdown)…"
              value={draft.content}
              onChange={(e) => setDraft({ ...draft, content: e.target.value })}
            />
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <button className="send-btn" disabled={!draft.name.trim()} onClick={saveSkill}>
                Create skill
              </button>
              <button className="settings-btn" style={{ flex: "none" }} onClick={() => setCreating(false)}>
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <>
            <input
              className="palette-input"
              placeholder="Search skills…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <div className="panel-body">
          {preview ? (
            <>
              <button className="settings-btn" style={{ flex: "none" }} onClick={() => setPreview(null)}>
                <ArrowLeft size={14} /> Back
              </button>
              <pre className="tool-result" style={{ maxHeight: "50vh" }}>
                {preview}
              </pre>
            </>
          ) : (
            <>
              {filtered.map((s) => (
                <div className="setting-row" key={s.name}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600 }}>{s.name}</div>
                    <div className="muted" style={{ fontSize: 12 }}>
                      {s.description || "No description"}
                    </div>
                  </div>
                  <button className="settings-btn" style={{ flex: "none" }} onClick={() => viewSkill(s.name)}>
                    View
                  </button>
                  <button
                    className="send-btn"
                    style={{ padding: "6px 12px" }}
                    onClick={() => {
                      onPick(s.name);
                      onClose();
                    }}
                  >
                    Use
                  </button>
                </div>
              ))}
              {filtered.length === 0 ? <div className="muted pad">No skills found.</div> : null}
            </>
          )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
