import { Check, ImagePlus, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { ACCENTS, THEMES, usePrefs } from "../prefs";
import { useToast } from "../toast";
import { AgentAvatar } from "./AgentAvatar";

type Tab =
  | "Appearance"
  | "Providers"
  | "Model"
  | "Capabilities"
  | "Execution"
  | "Forking"
  | "Advanced";

const TABS: Tab[] = [
  "Appearance",
  "Providers",
  "Model",
  "Capabilities",
  "Execution",
  "Forking",
  "Advanced",
];

const ENUMS: Record<string, string[]> = {
  thinking_effort: ["minimal", "low", "medium", "high"],
  reasoning_effort: ["minimal", "low", "medium", "high"],
  reminder_mode: ["off", "first", "context", "llm"],
  sandbox: ["local", "docker"],
  charset: ["auto", "ascii", "unicode"],
  fork_merge_strategy: ["manual", "auto", "auto_with_fallback", "vote"],
};

function ModelTab(): JSX.Element {
  const toast = useToast();
  const [cfg, setCfg] = useState<Record<string, unknown>>({});
  const [groups, setGroups] = useState<{ label: string; models: string[] }[]>([]);

  useEffect(() => {
    api.getConfig().then(setCfg).catch((e) => toast.push(String(e), "error"));
    api.getModels().then((r) => setGroups(r.providers)).catch(() => undefined);
  }, [toast]);

  const save = (key: string, value: unknown): void => {
    setCfg((c) => ({ ...c, [key]: value }));
    api.updateConfig(key, value).catch((e) => toast.push(String(e), "error"));
  };

  const allModels = groups.flatMap((g) => g.models);
  const modelSelect = (key: string, includeNone: boolean): JSX.Element => {
    const current = (cfg[key] as string) ?? "";
    const missing = current && !allModels.includes(current);
    return (
      <select value={current} onChange={(e) => save(key, e.target.value)}>
        {includeNone ? <option value="">— none —</option> : null}
        {missing ? <option value={current}>{current}</option> : null}
        {groups.map((g) => (
          <optgroup key={g.label} label={g.label}>
            {g.models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    );
  };

  const temp = cfg.temperature;
  const tempVal = typeof temp === "number" ? temp : 0.7;

  return (
    <>
      <div className="setting-row">
        <label>Model</label>
        {modelSelect("model", false)}
      </div>
      <div className="setting-row">
        <label>Fallback model</label>
        {modelSelect("fallback_model", true)}
      </div>
      <div className="setting-row">
        <label>Thinking / reasoning effort</label>
        <select
          value={(cfg.thinking_effort as string) ?? "high"}
          onChange={(e) => save("thinking_effort", e.target.value)}
        >
          {["minimal", "low", "medium", "high"].map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      </div>
      <div className="setting-row">
        <label>Temperature {temp == null ? "(model default)" : `(${tempVal.toFixed(2)})`}</label>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flex: 1 }}>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={tempVal}
            style={{ flex: 1 }}
            onChange={(e) => save("temperature", Number(e.target.value))}
          />
          <button className="settings-btn" style={{ flex: "none" }} onClick={() => save("temperature", "")}>
            Auto
          </button>
        </div>
      </div>
    </>
  );
}

function humanize(name: string): string {
  return name
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

const PROVIDERS: { id: string; label: string; hint: string }[] = [
  { id: "anthropic", label: "Anthropic", hint: "ANTHROPIC_API_KEY" },
  { id: "openai", label: "OpenAI", hint: "OPENAI_API_KEY" },
  { id: "google-gla", label: "Google", hint: "GOOGLE_API_KEY" },
  { id: "openrouter", label: "OpenRouter", hint: "OPENROUTER_API_KEY" },
  { id: "groq", label: "Groq", hint: "GROQ_API_KEY" },
  { id: "mistral", label: "Mistral", hint: "MISTRAL_API_KEY" },
  { id: "cohere", label: "Cohere", hint: "CO_API_KEY" },
];

function ProvidersTab(): JSX.Element {
  const toast = useToast();
  const [status, setStatus] = useState<Record<string, boolean>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  useEffect(() => {
    api
      .getKeys()
      .then(setStatus)
      .catch((e) => toast.push(String(e), "error"));
  }, [toast]);

  const save = (provider: string): void => {
    const key = (drafts[provider] ?? "").trim();
    if (!key) return;
    api
      .setKey(provider, key)
      .then(() => {
        setStatus((s) => ({ ...s, [provider]: true }));
        setDrafts((d) => ({ ...d, [provider]: "" }));
        toast.push("API key saved", "success");
      })
      .catch((e) => toast.push(String(e), "error"));
  };

  return (
    <>
      <div className="muted pad" style={{ paddingLeft: 0 }}>
        Keys are stored in <code>.pydantic-deep/.env</code> and applied immediately.
      </div>
      {PROVIDERS.map((p) => (
        <div className="setting-row" key={p.id}>
          <label>
            {p.label}
            {status[p.id] ? (
              <span className="saved-tag">
                <Check size={12} /> set
              </span>
            ) : null}
          </label>
          <input
            type="password"
            placeholder={status[p.id] ? "•••••••• (configured)" : p.hint}
            value={drafts[p.id] ?? ""}
            onChange={(e) => setDrafts((d) => ({ ...d, [p.id]: e.target.value }))}
            onKeyDown={(e) => {
              if (e.key === "Enter") save(p.id);
            }}
          />
          <button className="settings-btn" style={{ flex: "none" }} onClick={() => save(p.id)}>
            Save
          </button>
        </div>
      ))}
    </>
  );
}

function classify(name: string): Tab {
  if (name.startsWith("fork_")) return "Forking";
  if (
    name.startsWith("include_") ||
    name.startsWith("web_") ||
    name.startsWith("reminder") ||
    name.startsWith("periodic") ||
    name === "context_discovery"
  )
    return "Capabilities";
  if (
    name.startsWith("sandbox") ||
    name.startsWith("shell") ||
    name.startsWith("approve") ||
    name === "working_dir"
  )
    return "Execution";
  if (["model", "fallback_model", "temperature", "thinking_effort", "reasoning_effort"].includes(name))
    return "Model";
  return "Advanced";
}

export function Settings({
  onClose,
  initialTab = "Appearance",
}: {
  onClose: () => void;
  initialTab?: string;
}): JSX.Element {
  const { prefs, setPref, reset } = usePrefs();
  const toast = useToast();
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [fields, setFields] = useState<{ name: string; type: string }[]>([]);
  const [tab, setTab] = useState<Tab>((TABS as string[]).includes(initialTab) ? (initialTab as Tab) : "Appearance");
  const [search, setSearch] = useState("");
  const userImgRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    Promise.all([api.getConfig(), api.getConfigSchema()])
      .then(([cfg, schema]) => {
        setValues(cfg);
        setFields(schema);
      })
      .catch((e) => toast.push(String(e), "error"));
  }, [toast]);

  const save = (key: string, value: unknown): void => {
    api
      .updateConfig(key, value)
      .then(() => toast.push(`Saved ${key}`, "success"))
      .catch((e) => toast.push(String(e), "error"));
  };

  const visibleFields = useMemo(() => {
    const q = search.toLowerCase().trim();
    return fields
      .filter((f) => classify(f.name) === tab)
      .filter((f) => !q || f.name.toLowerCase().includes(q));
  }, [fields, tab, search]);

  return (
    <div className="overlay" onClick={onClose}>
      <div className="panel" onClick={(e) => e.stopPropagation()}>
        <div className="panel-head">
          <h2>Settings</h2>
          <button className="icon-btn" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <div className="settings-tabs">
          {TABS.map((t) => (
            <button
              key={t}
              className={`settings-tab ${t === tab ? "active" : ""}`}
              onClick={() => setTab(t)}
            >
              {t}
            </button>
          ))}
        </div>
        <div className="panel-body">
          {tab === "Appearance" ? (
            <>
              <div className="setting-row">
                <label>Theme</label>
                <select
                  value={prefs.theme}
                  onChange={(e) => setPref("theme", e.target.value as typeof prefs.theme)}
                >
                  {THEMES.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="setting-row">
                <label>Accent</label>
                <div className="swatches">
                  {ACCENTS.map((c) => (
                    <span
                      key={c}
                      className={`swatch ${prefs.accent === c ? "active" : ""}`}
                      style={{ background: c }}
                      onClick={() => setPref("accent", c)}
                    />
                  ))}
                  <input
                    type="color"
                    className="color-input"
                    value={prefs.accent}
                    title="Custom accent"
                    onChange={(e) => setPref("accent", e.target.value)}
                  />
                </div>
              </div>
              <div className="setting-row">
                <label>Font size ({prefs.fontSize}px)</label>
                <input
                  type="range"
                  min={11}
                  max={20}
                  value={prefs.fontSize}
                  onChange={(e) => setPref("fontSize", Number(e.target.value))}
                />
              </div>
              <div className="setting-row">
                <label>Density</label>
                <select
                  value={prefs.density}
                  onChange={(e) => setPref("density", e.target.value as typeof prefs.density)}
                >
                  <option value="comfortable">Comfortable</option>
                  <option value="compact">Compact</option>
                </select>
              </div>
              <div className="setting-row">
                <label>Your avatar</label>
                <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                  <AgentAvatar avatar={prefs.userAvatar} color={prefs.userColor} size={40} />
                  <button className="settings-btn" style={{ flex: "none" }} onClick={() => userImgRef.current?.click()}>
                    <ImagePlus size={15} /> Upload image
                  </button>
                  {prefs.userAvatar ? (
                    <button className="settings-btn" style={{ flex: "none" }} onClick={() => setPref("userAvatar", "")}>
                      Remove
                    </button>
                  ) : null}
                  <input
                    ref={userImgRef}
                    type="file"
                    accept="image/*"
                    style={{ display: "none" }}
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) {
                        const reader = new FileReader();
                        reader.onload = () => setPref("userAvatar", String(reader.result));
                        reader.readAsDataURL(f);
                      }
                      e.target.value = "";
                    }}
                  />
                  <div className="swatches">
                    {ACCENTS.map((c) => (
                      <span
                        key={c}
                        className={`swatch ${prefs.userColor === c ? "active" : ""}`}
                        style={{ background: c }}
                        onClick={() => setPref("userColor", c)}
                      />
                    ))}
                  </div>
                </div>
              </div>
              <ToggleRow label="Show thinking" value={prefs.showThinking} onChange={(v) => setPref("showThinking", v)} />
              <ToggleRow label="Enter to send" value={prefs.enterToSend} onChange={(v) => setPref("enterToSend", v)} />
              <ToggleRow label="Auto-scroll" value={prefs.autoScroll} onChange={(v) => setPref("autoScroll", v)} />
              <ToggleRow label="Collapse tool output" value={prefs.toolsCollapsed} onChange={(v) => setPref("toolsCollapsed", v)} />
              <ToggleRow label="Animations" value={prefs.animations} onChange={(v) => setPref("animations", v)} />
              <div className="setting-row">
                <label>Reset appearance</label>
                <button className="settings-btn" onClick={reset} style={{ flex: "none" }}>
                  Reset to defaults
                </button>
              </div>
            </>
          ) : tab === "Providers" ? (
            <ProvidersTab />
          ) : tab === "Model" ? (
            <ModelTab />
          ) : (
            <>
              <input
                className="search-box"
                style={{ margin: "0 0 8px", width: "100%" }}
                placeholder="Filter settings…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              {visibleFields.map((f) => {
                const value = values[f.name];
                const isBool = typeof value === "boolean";
                const isNum = typeof value === "number";
                const isComplex = value !== null && typeof value === "object";
                const enumOpts = ENUMS[f.name];
                return (
                  <div className="setting-row" key={f.name}>
                    <label title={f.name}>{humanize(f.name)}</label>
                    {isComplex ? (
                      <input
                        type="text"
                        disabled
                        value={Array.isArray(value) ? value.join(", ") || "—" : JSON.stringify(value)}
                      />
                    ) : isBool ? (
                      <label className="switch">
                        <input
                          type="checkbox"
                          checked={Boolean(value)}
                          onChange={(e) => {
                            setValues({ ...values, [f.name]: e.target.checked });
                            save(f.name, e.target.checked);
                          }}
                        />
                        <span className="slider" />
                      </label>
                    ) : enumOpts ? (
                      <select
                        value={value === null || value === undefined ? "" : String(value)}
                        onChange={(e) => {
                          setValues({ ...values, [f.name]: e.target.value });
                          save(f.name, e.target.value);
                        }}
                      >
                        {enumOpts.map((o) => (
                          <option key={o} value={o}>
                            {o}
                          </option>
                        ))}
                      </select>
                    ) : isNum ? (
                      <input
                        type="number"
                        defaultValue={String(value)}
                        onBlur={(e) => save(f.name, e.target.value)}
                      />
                    ) : (
                      <input
                        type="text"
                        defaultValue={value === null || value === undefined ? "" : String(value)}
                        onBlur={(e) => save(f.name, e.target.value)}
                      />
                    )}
                  </div>
                );
              })}
              {visibleFields.length === 0 ? <div className="muted pad">No settings here.</div> : null}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function ToggleRow({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}): JSX.Element {
  return (
    <div className="setting-row">
      <label>{label}</label>
      <label className="switch">
        <input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)} />
        <span className="slider" />
      </label>
    </div>
  );
}
