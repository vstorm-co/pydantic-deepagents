import { ArrowDown, Brain, KeyRound, Lightbulb, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { api } from "./api";
import { chatReducer } from "./chatReducer";
import { CommandPalette, type Command } from "./components/CommandPalette";
import { Composer } from "./components/Composer";
import { Header } from "./components/Header";
import { HelpOverlay } from "./components/HelpOverlay";
import { Markdown } from "./components/Markdown";
import { AgentAvatar } from "./components/AgentAvatar";
import { AgentsPanel } from "./components/AgentsPanel";
import { FileBrowser } from "./components/FileBrowser";
import { FilesPanel } from "./components/FilesPanel";
import { Settings } from "./components/Settings";
import { Sidebar } from "./components/Sidebar";
import { SkillsPanel } from "./components/SkillsPanel";
import { StatusBar } from "./components/StatusBar";
import { ToolCallCard } from "./components/ToolCallCard";
import { THEMES, usePrefs } from "./prefs";
import { useToast } from "./toast";
import type { Attachment, ChatItem, SessionInfo, SessionStats } from "./types";
import { SessionSocket, type SocketStatus } from "./ws";

const EXAMPLES = [
  "Explain this project's architecture",
  "Find and fix the failing tests",
  "Refactor the largest file into modules",
  "Write a README for the gateway",
];

const TIPS = [
  "Type / in the message box for quick commands.",
  "Press ⌘K to open the command palette.",
  "Drag files straight onto the composer to attach them.",
  "Create custom agents — each with its own prompt & avatar.",
  "Switch the model per session from the header pill.",
  "Ask for a ```mermaid diagram and it renders inline.",
  "Tune thinking effort & temperature from ⚙ in the header.",
];

function greeting(): string {
  const h = new Date().getHours();
  if (h < 5) return "Burning the midnight oil?";
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

export function App(): JSX.Element {
  const { prefs, setPref } = usePrefs();
  const toast = useToast();

  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [items, dispatch] = useReducer(chatReducer, []);
  const [status, setStatus] = useState<SocketStatus>("closed");
  const [version, setVersion] = useState("");
  const [overlay, setOverlay] = useState<
    "none" | "settings" | "palette" | "help" | "skills" | "agents" | "files" | "browse" | "folder"
  >("none");
  const [fatal, setFatal] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [atBottom, setAtBottom] = useState(true);
  const [stats, setStats] = useState<SessionStats | null>(null);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [tip] = useState(() => TIPS[Math.floor(Math.random() * TIPS.length)]);
  const [hasKey, setHasKey] = useState(true);
  const [settingsTab, setSettingsTab] = useState("Appearance");
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const socketRef = useRef<SessionSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const attachmentsRef = useRef<Attachment[]>([]);
  useEffect(() => {
    attachmentsRef.current = attachments;
  }, [attachments]);

  const refreshSessions = useCallback(async (): Promise<SessionInfo[]> => {
    const list = await api.listSessions();
    setSessions(list);
    return list;
  }, []);

  const refreshKeys = useCallback(async (): Promise<void> => {
    try {
      const keys = await api.getKeys();
      setHasKey(Object.values(keys).some(Boolean));
    } catch {
      setHasKey(true); // don't nag if the check fails
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        setVersion((await api.version()).version);
        void refreshKeys();
        let list = await refreshSessions();
        if (list.length === 0) {
          const created = await api.createSession(
            prefs.lastModel || undefined,
            prefs.lastAgentId || undefined,
          );
          list = [created];
          setSessions(list);
        }
        setSelectedId(list[0].id);
      } catch (e) {
        setFatal(String(e));
      }
    })();
  }, [refreshSessions]);

  useEffect(() => {
    if (!selectedId) return;
    dispatch({ kind: "reset" });
    setStats(null);
    let cancelled = false;
    api
      .getMessages(selectedId)
      .then((msgs) => {
        if (!cancelled && msgs.length > 0) dispatch({ kind: "load", items: msgs });
      })
      .catch(() => undefined);
    const socket = new SessionSocket(
      selectedId,
      (event) => {
        if (event.type === "session_stats") {
          setStats(event);
          // The server may have auto-named the session from the user's message.
          void refreshSessions();
        } else {
          dispatch({ kind: "event", event });
        }
      },
      (s) => setStatus(s),
    );
    socket.connect();
    socketRef.current = socket;
    return () => {
      cancelled = true;
      socket.close();
      socketRef.current = null;
    };
  }, [selectedId]);

  // Auto-scroll when pinned to the bottom.
  useEffect(() => {
    if (prefs.autoScroll && atBottom) {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
    }
  }, [items, atBottom, prefs.autoScroll]);

  const running = items.some((it) => it.kind === "assistant" && it.running);
  const selected = sessions.find((s) => s.id === selectedId);

  // Live elapsed timer while the agent is working + a completion toast.
  const [elapsed, setElapsed] = useState(0);
  const elapsedRef = useRef(0);
  useEffect(() => {
    if (!running) {
      setElapsed(0);
      elapsedRef.current = 0;
      return;
    }
    const start = Date.now();
    const id = window.setInterval(() => {
      const e = Math.floor((Date.now() - start) / 1000);
      elapsedRef.current = e;
      setElapsed(e);
    }, 500);
    return () => {
      window.clearInterval(id);
      if (elapsedRef.current >= 3) {
        toast.push(`Done in ${elapsedRef.current}s`, "success");
        // Flash the window title if the app isn't focused.
        if (!document.hasFocus()) {
          document.title = "Done — pydantic·deep";
          const restore = (): void => {
            document.title = "pydantic·deep";
            window.removeEventListener("focus", restore);
          };
          window.addEventListener("focus", restore);
        }
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  const onSend = useCallback((text: string): void => {
    const atts = attachmentsRef.current;
    const full = atts.length
      ? `Attached files in the workspace:\n${atts.map((a) => `- ${a.path}`).join("\n")}\n\n${text}`
      : text;
    dispatch({ kind: "user_prompt", text: full });
    socketRef.current?.prompt(full);
    if (atts.length) setAttachments([]);
  }, []);

  const onCancel = (): void => socketRef.current?.cancel();

  const onAttach = useCallback(
    async (files: FileList): Promise<void> => {
      if (!selectedId) return;
      for (const file of Array.from(files)) {
        try {
          const r = await api.uploadFile(selectedId, file);
          setAttachments((a) => [...a, { path: r.path, name: r.name }]);
          toast.push(`Attached ${r.name}`, "success");
        } catch (e) {
          toast.push(String(e), "error");
        }
      }
    },
    [selectedId, toast],
  );

  const onScreenshot = async (): Promise<void> => {
    if (!selectedId) return;
    try {
      const r = await api.screenshot(selectedId);
      setAttachments((a) => [...a, { path: r.path, name: r.name }]);
      toast.push("Screenshot attached", "success");
    } catch (e) {
      toast.push(String(e), "error");
    }
  };

  const onPickSkill = (name: string): void => {
    setInput(`Use the "${name}" skill: `);
    toast.push(`Skill: ${name}`);
  };

  const onAgentChange = async (agentId: string): Promise<void> => {
    if (!selectedId) return;
    try {
      await api.setSessionAgent(selectedId, agentId);
      setPref("lastAgentId", agentId);
      await refreshSessions();
    } catch (e) {
      toast.push(String(e), "error");
    }
  };


  const onCreate = useCallback(async (): Promise<void> => {
    const created = await api.createSession(
      prefs.lastModel || undefined,
      prefs.lastAgentId || undefined,
    );
    await refreshSessions();
    setSelectedId(created.id);
    toast.push("New session", "success");
  }, [refreshSessions, toast, prefs.lastModel, prefs.lastAgentId]);

  const onDelete = async (id: string): Promise<void> => {
    await api.deleteSession(id);
    const list = await refreshSessions();
    if (id === selectedId) setSelectedId(list.length > 0 ? list[0].id : null);
  };

  const onRename = async (name: string): Promise<void> => {
    if (!selectedId) return;
    await api.renameSession(selectedId, name);
    await refreshSessions();
  };

  const onModelChange = async (model: string): Promise<void> => {
    if (!selectedId) return;
    try {
      await api.setModel(selectedId, model);
      setPref("lastModel", model);
      await refreshSessions();
      toast.push(`Model: ${model}`, "success");
    } catch (e) {
      toast.push(String(e), "error");
    }
  };

  const onControlsChange = async (controls: {
    thinking?: string;
    temperature?: number;
  }): Promise<void> => {
    if (!selectedId) return;
    try {
      await api.setControls(selectedId, controls);
      await refreshSessions();
    } catch (e) {
      toast.push(String(e), "error");
    }
  };

  const onSetCwd = async (path: string): Promise<void> => {
    if (!selectedId) return;
    try {
      await api.setCwd(selectedId, path);
      await refreshSessions();
      toast.push(`Working folder: ${path}`, "success");
    } catch (e) {
      toast.push(String(e), "error");
    }
  };

  const onExport = (): void => {
    if (items.length === 0) {
      toast.push("Nothing to export");
      return;
    }
    const agentName = selected?.agent_name ?? "Assistant";
    const md = items
      .map((it) => (it.kind === "user" ? `### You\n\n${it.text}` : `### ${agentName}\n\n${it.text}`))
      .join("\n\n");
    const blob = new Blob([md], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(selected?.name ?? "conversation").replace(/[^\w]+/g, "-")}.md`;
    a.click();
    URL.revokeObjectURL(url);
    toast.push("Exported to markdown", "success");
  };

  const onRegenerate = (): void => {
    for (let i = items.length - 1; i >= 0; i -= 1) {
      const it = items[i];
      if (it.kind === "user") {
        onSend(it.text);
        return;
      }
    }
  };

  const slashCommands = useMemo(
    () => [
      { id: "new", label: "/new — new chat", run: () => void onCreate() },
      { id: "agents", label: "/agents — manage agents", run: () => setOverlay("agents") },
      { id: "skills", label: "/skills — browse skills", run: () => setOverlay("skills") },
      { id: "files", label: "/files — workspace files", run: () => setOverlay("files") },
      { id: "export", label: "/export — save chat as markdown", run: onExport },
      { id: "regenerate", label: "/regenerate — redo last answer", run: onRegenerate },
      { id: "settings", label: "/settings — open settings", run: () => setOverlay("settings") },
      { id: "help", label: "/help — keyboard shortcuts", run: () => setOverlay("help") },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [onCreate, items, selected],
  );

  const cycleTheme = useCallback((): void => {
    const idx = THEMES.findIndex((t) => t.id === prefs.theme);
    const next = THEMES[(idx + 1) % THEMES.length];
    setPref("theme", next.id);
    toast.push(`Theme: ${next.label}`);
  }, [prefs.theme, setPref, toast]);

  // Global keyboard shortcuts.
  useEffect(() => {
    const handler = (e: KeyboardEvent): void => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOverlay((o) => (o === "palette" ? "none" : "palette"));
      } else if (mod && e.key.toLowerCase() === "b") {
        e.preventDefault();
        setSidebarOpen((s) => !s);
      } else if (mod && e.key.toLowerCase() === "n") {
        e.preventDefault();
        void onCreate();
      } else if (mod && /^[1-9]$/.test(e.key)) {
        e.preventDefault();
        const target = sessions[Number(e.key) - 1];
        if (target) setSelectedId(target.id);
      } else if (mod && e.key === ",") {
        e.preventDefault();
        setOverlay("settings");
      } else if (e.key === "?" && !isTyping(e)) {
        e.preventDefault();
        setOverlay("help");
      } else if (e.key === "Escape") {
        if (overlay !== "none") setOverlay("none");
        else if (running) onCancel();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [overlay, running, onCreate, sessions]);

  const commands = useMemo<Command[]>(() => {
    const base: Command[] = [
      { id: "new", label: "New session", hint: "⌘N", run: () => void onCreate() },
      { id: "settings", label: "Open settings", hint: "⌘,", run: () => setOverlay("settings") },
      { id: "skills", label: "Browse skills", run: () => setOverlay("skills") },
      { id: "help", label: "Keyboard shortcuts", hint: "?", run: () => setOverlay("help") },
      { id: "theme", label: "Cycle theme", run: cycleTheme },
      { id: "cancel", label: "Stop current run", hint: "Esc", run: onCancel },
    ];
    const switchers: Command[] = sessions.map((s) => ({
      id: `switch-${s.id}`,
      label: `Switch to ${s.name ?? "New chat"}`,
      group: "session",
      run: () => setSelectedId(s.id),
    }));
    return [...base, ...switchers];
  }, [sessions, onCreate, cycleTheme]);

  if (fatal) {
    return (
      <div className="fatal">
        <h1>Cannot reach the gateway</h1>
        <p>{fatal}</p>
        <p className="muted">Is the pydantic-deep gateway running?</p>
      </div>
    );
  }

  return (
    <div
      className={`app ${sidebarOpen ? "" : "collapsed"}`}
      style={{ ["--sidebar-w" as string]: `${prefs.sidebarWidth}px` }}
    >
      <aside className="sidebar">
        <Sidebar
          sessions={sessions}
          selectedId={selectedId}
          pinned={prefs.pinnedSessions}
          onSelect={setSelectedId}
          onCreate={() => void onCreate()}
          onDelete={(id) => void onDelete(id)}
          onTogglePin={(id) =>
            setPref(
              "pinnedSessions",
              prefs.pinnedSessions.includes(id)
                ? prefs.pinnedSessions.filter((x) => x !== id)
                : [...prefs.pinnedSessions, id],
            )
          }
          onOpenSettings={() => setOverlay("settings")}
          onOpenPalette={() => setOverlay("palette")}
          onOpenHelp={() => setOverlay("help")}
        />
        <SidebarResizer width={prefs.sidebarWidth} onResize={(w) => setPref("sidebarWidth", w)} />
      </aside>

      <main className="main">
        <Header
          session={selected}
          status={status}
          onRename={(n) => void onRename(n)}
          onModelChange={(m) => void onModelChange(m)}
          onControlsChange={(c) => void onControlsChange(c)}
          onAgentChange={(a) => void onAgentChange(a)}
          onManageAgents={() => setOverlay("agents")}
          onOpenPalette={() => setOverlay("palette")}
          onToggleSidebar={() => setSidebarOpen((s) => !s)}
          onOpenFolder={() => setOverlay("folder")}
        />
        <div
          className="transcript"
          ref={scrollRef}
          onScroll={(e) => {
            const el = e.currentTarget;
            setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 48);
          }}
        >
          {items.map((item, i) => (
            <ChatRow
              key={item.id}
              item={item}
              agentAvatar={selected?.agent_avatar ?? ""}
              agentColor={selected?.agent_color ?? "#4493f8"}
              isLast={i === items.length - 1}
              onCopy={(t) => copyText(t, toast)}
              onRetry={onSend}
              onEdit={(t) => setInput(t)}
              onRegenerate={onRegenerate}
            />
          ))}
          {items.length === 0 && !hasKey ? (
            <div className="welcome">
              <div className="welcome-logo">
                <KeyRound size={30} />
              </div>
              <h2>Add an API key to begin</h2>
              <p className="muted">
                pydantic·deep needs a provider key (Anthropic, OpenAI, OpenRouter, …) to talk to a
                model. Your keys stay local.
              </p>
              <button
                className="send-btn"
                style={{ marginTop: 16 }}
                onClick={() => {
                  setSettingsTab("Providers");
                  setOverlay("settings");
                }}
              >
                Add API key
              </button>
            </div>
          ) : items.length === 0 ? (
            <div className="welcome">
              <AgentAvatar
                avatar={selected?.agent_avatar ?? ""}
                color={selected?.agent_color ?? "#4493f8"}
                size={64}
              />
              <h2 style={{ marginTop: 16 }}>{greeting()}</h2>
              <p className="muted">
                What should {selected?.agent_name ?? "your agent"} work on?
              </p>
              <div className="examples">
                {EXAMPLES.map((ex) => (
                  <button key={ex} className="example" onClick={() => setInput(ex)}>
                    {ex}
                  </button>
                ))}
              </div>
              <div className="welcome-tip">
                <Lightbulb size={13} /> {tip}
              </div>
            </div>
          ) : null}
        </div>
        {!atBottom ? (
          <button
            className="scroll-bottom"
            title="Scroll to bottom"
            onClick={() => {
              scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
              setAtBottom(true);
            }}
          >
            <ArrowDown size={16} />
          </button>
        ) : null}
        <Composer
          value={input}
          onChange={setInput}
          running={running}
          disabled={status !== "open"}
          onSend={onSend}
          onCancel={onCancel}
          attachments={attachments}
          onAttach={(files) => void onAttach(files)}
          onRemoveAttachment={(path) => setAttachments((a) => a.filter((x) => x.path !== path))}
          onOpenSkills={() => setOverlay("skills")}
          onOpenFiles={() => setOverlay("files")}
          onAtMention={() => setOverlay("browse")}
          onScreenshot={() => void onScreenshot()}
          slashCommands={slashCommands}
        />
        <StatusBar
          model={selected?.model ?? "—"}
          status={status}
          version={version}
          messageCount={items.length}
          stats={stats}
          running={running}
          elapsed={elapsed}
        />
      </main>

      {overlay === "settings" ? (
        <Settings
          initialTab={settingsTab}
          onClose={() => {
            setOverlay("none");
            void refreshKeys();
          }}
        />
      ) : null}
      {overlay === "palette" ? (
        <CommandPalette commands={commands} onClose={() => setOverlay("none")} />
      ) : null}
      {overlay === "help" ? <HelpOverlay onClose={() => setOverlay("none")} /> : null}
      {overlay === "skills" ? (
        <SkillsPanel onPick={onPickSkill} onClose={() => setOverlay("none")} />
      ) : null}
      {overlay === "agents" ? (
        <AgentsPanel onClose={() => setOverlay("none")} onChanged={() => void refreshSessions()} />
      ) : null}
      {overlay === "files" ? (
        <FilesPanel
          sessionId={selectedId}
          onUse={(p) => setInput((d) => (d ? `${d} @${p}` : `@${p} `))}
          onClose={() => setOverlay("none")}
        />
      ) : null}
      {overlay === "browse" ? (
        <FileBrowser
          mode="file"
          initialPath={selected?.cwd}
          onPick={(p) => {
            setInput((prev) => (prev.endsWith("@") ? `${prev.slice(0, -1)}@${p} ` : `${prev} @${p} `));
            setOverlay("none");
          }}
          onClose={() => setOverlay("none")}
        />
      ) : null}
      {overlay === "folder" ? (
        <FileBrowser
          mode="folder"
          initialPath={selected?.cwd}
          onPick={(p) => {
            void onSetCwd(p);
            setOverlay("none");
          }}
          onClose={() => setOverlay("none")}
        />
      ) : null}
    </div>
  );
}

function isTyping(e: KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null;
  return t != null && (t.tagName === "INPUT" || t.tagName === "TEXTAREA");
}

function copyText(text: string, toast: { push: (m: string, k?: "success") => void }): void {
  void navigator.clipboard.writeText(text);
  toast.push("Copied", "success");
}

function SidebarResizer({
  width,
  onResize,
}: {
  width: number;
  onResize: (w: number) => void;
}): JSX.Element {
  const start = (e: React.MouseEvent): void => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = width;
    const move = (ev: MouseEvent): void => {
      const next = Math.min(Math.max(startW + (ev.clientX - startX), 180), 460);
      onResize(next);
    };
    const up = (): void => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };
  return <div className="resizer" onMouseDown={start} />;
}

function ChatRow({
  item,
  agentAvatar,
  agentColor,
  isLast,
  onCopy,
  onRetry,
  onEdit,
  onRegenerate,
}: {
  item: ChatItem;
  agentAvatar: string;
  agentColor: string;
  isLast: boolean;
  onCopy: (text: string) => void;
  onRetry: (text: string) => void;
  onEdit: (text: string) => void;
  onRegenerate: () => void;
}): JSX.Element {
  const { prefs } = usePrefs();
  if (item.kind === "user") {
    return (
      <div className="row user">
        <div className="msg">
          <AgentAvatar avatar={prefs.userAvatar} color={prefs.userColor} size={28} />
          <div className="bubble">{item.text}</div>
        </div>
        <div className="row-actions">
          <button onClick={() => onCopy(item.text)}>Copy</button>
          <button onClick={() => onEdit(item.text)}>Edit</button>
          <button onClick={() => onRetry(item.text)}>Retry</button>
        </div>
      </div>
    );
  }
  return (
    <div className="row assistant">
      <div className="msg">
        <AgentAvatar avatar={agentAvatar} color={agentColor} size={28} />
        <div className="msg-body">
          {prefs.showThinking && item.thinking ? <ThinkingBlock text={item.thinking} /> : null}
          {item.tools.map((t) => (
            <ToolCallCard key={t.id} tool={t} />
          ))}
          {item.text ? (
            item.running ? (
              // Show raw text while streaming (cheap); render rich markdown only
              // once the turn completes — avoids re-parsing on every delta.
              <div className="bubble streaming">{item.text}</div>
            ) : (
              <div className="bubble md">
                <Markdown text={item.text} />
              </div>
            )
          ) : null}
          {item.running && !item.text ? (
            <div className="typing">
              <span></span>
              <span></span>
              <span></span>
            </div>
          ) : null}
          {item.running && item.text ? <span className="cursor">▍</span> : null}
          {item.error ? <div className="error-banner">{item.error}</div> : null}
        </div>
      </div>
      {item.text && !item.running ? (
        <div className="row-actions">
          <button onClick={() => onCopy(item.text)}>Copy</button>
          {isLast ? (
            <button onClick={onRegenerate}>
              <RefreshCw size={12} /> Regenerate
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function ThinkingBlock({ text }: { text: string }): JSX.Element {
  return (
    <details className="thinking-box" open>
      <summary>
        <Brain size={13} className="think-icon" /> Thinking
      </summary>
      <div className="thinking-text">{text}</div>
    </details>
  );
}
