import { ChevronDown } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { ModelGroup } from "../types";

const CUSTOM = "__custom__";

export function ModelPicker({
  current,
  onSelect,
}: {
  current: string;
  onSelect: (model: string) => void;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  const [groups, setGroups] = useState<ModelGroup[]>([]);
  const [tab, setTab] = useState<string | null>(null);
  const [custom, setCustom] = useState("");
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (open && groups.length === 0) {
      api
        .getModels()
        .then((r) => setGroups(r.providers))
        .catch(() => undefined);
    }
  }, [open, groups.length]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent): void => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  // Default the active tab to the provider of the current model.
  const currentProvider = current.includes(":") ? current.split(":")[0] : "";
  const activeTab = tab ?? (groups.find((g) => g.id === currentProvider)?.id ?? groups[0]?.id ?? null);

  const activeGroup = useMemo(
    () => groups.find((g) => g.id === activeTab),
    [groups, activeTab],
  );

  const pick = (model: string): void => {
    setOpen(false);
    setTab(null);
    if (model && model !== current) onSelect(model);
  };

  const short = current.includes(":") ? current.split(":").slice(1).join(":") : current;

  return (
    <div className="model-picker" ref={ref}>
      <button className="model-pill" title={current} onClick={() => setOpen((o) => !o)}>
        {short}
        <ChevronDown size={13} />
      </button>
      {open ? (
        <div className="model-dropdown grouped">
          <div className="provider-tabs">
            {groups.map((g) => (
              <button
                key={g.id}
                className={`ptab ${activeTab === g.id ? "active" : ""}`}
                onClick={() => setTab(g.id)}
              >
                {g.label}
              </button>
            ))}
            <button
              className={`ptab ${activeTab === CUSTOM ? "active" : ""}`}
              onClick={() => setTab(CUSTOM)}
            >
              Custom
            </button>
          </div>
          <div className="model-options">
            {activeTab === CUSTOM ? (
              <div className="model-custom">
                <input
                  autoFocus
                  placeholder="provider:model  (e.g. openrouter:meta-llama/llama-4)"
                  value={custom}
                  onChange={(e) => setCustom(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && custom.trim()) pick(custom.trim());
                  }}
                />
                <div className="quick-hint">Press Enter to use this model.</div>
              </div>
            ) : (
              (activeGroup?.models ?? []).map((m) => (
                <div
                  key={m}
                  className={`model-option ${m === current ? "active" : ""}`}
                  onClick={() => pick(m)}
                >
                  {m.includes(":") ? m.split(":").slice(1).join(":") : m}
                </div>
              ))
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
