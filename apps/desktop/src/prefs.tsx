import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type ThemeName =
  | "dark"
  | "light"
  | "midnight"
  | "solarized"
  | "nord"
  | "rose"
  | "forest"
  | "highContrast";
export type Density = "comfortable" | "compact";

export interface Prefs {
  theme: ThemeName;
  accent: string;
  fontSize: number;
  density: Density;
  sidebarWidth: number;
  showThinking: boolean;
  enterToSend: boolean;
  autoScroll: boolean;
  toolsCollapsed: boolean;
  animations: boolean;
  lastModel: string;
  lastAgentId: string;
  userAvatar: string;
  userColor: string;
  pinnedSessions: string[];
}

export const DEFAULT_PREFS: Prefs = {
  theme: "dark",
  accent: "#4493f8",
  fontSize: 14,
  density: "comfortable",
  sidebarWidth: 240,
  showThinking: true,
  enterToSend: true,
  autoScroll: true,
  toolsCollapsed: false,
  animations: true,
  lastModel: "",
  lastAgentId: "default",
  userAvatar: "",
  userColor: "#6b7280",
  pinnedSessions: [],
};

export const THEMES: { id: ThemeName; label: string }[] = [
  { id: "dark", label: "Dark" },
  { id: "midnight", label: "Midnight" },
  { id: "nord", label: "Nord" },
  { id: "forest", label: "Forest" },
  { id: "rose", label: "Rosé" },
  { id: "light", label: "Light" },
  { id: "solarized", label: "Solarized" },
  { id: "highContrast", label: "High contrast" },
];

export const ACCENTS: string[] = [
  "#4493f8",
  "#3fb950",
  "#bc8cff",
  "#f778ba",
  "#ff8c42",
  "#56d4dd",
  "#e3b341",
];

const STORAGE_KEY = "pd.prefs.v1";

function load(): Prefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return { ...DEFAULT_PREFS, ...(JSON.parse(raw) as Partial<Prefs>) };
  } catch {
    /* ignore corrupt storage */
  }
  return { ...DEFAULT_PREFS };
}

interface PrefsContextValue {
  prefs: Prefs;
  setPref: <K extends keyof Prefs>(key: K, value: Prefs[K]) => void;
  reset: () => void;
}

const PrefsContext = createContext<PrefsContextValue | null>(null);

export function PrefsProvider({ children }: { children: ReactNode }): JSX.Element {
  const [prefs, setPrefs] = useState<Prefs>(load);

  // Persist + apply to the document on every change.
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
    } catch {
      /* ignore */
    }
    const root = document.documentElement;
    root.dataset.theme = prefs.theme;
    root.dataset.density = prefs.density;
    root.dataset.animations = prefs.animations ? "on" : "off";
    root.style.setProperty("--accent", prefs.accent);
    root.style.setProperty("--font-size", `${prefs.fontSize}px`);
  }, [prefs]);

  const value = useMemo<PrefsContextValue>(
    () => ({
      prefs,
      setPref: (key, val) => setPrefs((p) => ({ ...p, [key]: val })),
      reset: () => setPrefs({ ...DEFAULT_PREFS }),
    }),
    [prefs],
  );

  return <PrefsContext.Provider value={value}>{children}</PrefsContext.Provider>;
}

export function usePrefs(): PrefsContextValue {
  const ctx = useContext(PrefsContext);
  if (!ctx) throw new Error("usePrefs must be used within PrefsProvider");
  return ctx;
}
