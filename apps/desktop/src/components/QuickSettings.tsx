import { useEffect, useRef, useState } from "react";
import type { Controls, SessionInfo } from "../types";

const EFFORTS = ["off", "minimal", "low", "medium", "high"];

// In-chat quick controls for the most-tuned per-turn settings (thinking effort,
// temperature). Persisted per session; applied by rebuilding the agent.
export function QuickSettings({
  session,
  onChange,
}: {
  session: SessionInfo | undefined;
  onChange: (controls: Controls) => void;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent): void => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const thinking = session?.thinking ?? "high";
  const temperature = session?.temperature ?? 0.7;

  return (
    <div className="model-picker" ref={ref}>
      <button className="model-pill" title="Reasoning & sampling" onClick={() => setOpen((o) => !o)}>
        ⚙ tuning
      </button>
      {open ? (
        <div className="model-dropdown quick">
          <div className="quick-label">Thinking effort</div>
          <div className="segmented">
            {EFFORTS.map((e) => (
              <button
                key={e}
                className={`seg ${thinking === e ? "active" : ""}`}
                onClick={() => onChange({ thinking: e })}
              >
                {e}
              </button>
            ))}
          </div>
          <div className="quick-label" style={{ marginTop: 12 }}>
            Temperature: {temperature.toFixed(2)}
          </div>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={temperature}
            style={{ width: "100%" }}
            onChange={(e) => onChange({ temperature: Number(e.target.value) })}
          />
          <div className="quick-hint">Changes apply from your next message.</div>
        </div>
      ) : null}
    </div>
  );
}
