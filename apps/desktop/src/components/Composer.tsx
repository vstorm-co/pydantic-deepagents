import { Camera, FolderOpen, Paperclip, Send, Sparkles, Square, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { usePrefs } from "../prefs";
import type { Attachment } from "../types";
import { VoiceButton } from "./VoiceButton";

export interface SlashCommand {
  id: string;
  label: string;
  hint?: string;
  run: () => void;
}

export function Composer({
  value,
  onChange,
  running,
  disabled,
  onSend,
  onCancel,
  attachments,
  onAttach,
  onRemoveAttachment,
  onOpenSkills,
  onOpenFiles,
  onAtMention,
  onScreenshot,
  slashCommands,
}: {
  value: string;
  onChange: (text: string) => void;
  running: boolean;
  disabled: boolean;
  onSend: (text: string) => void;
  onCancel: () => void;
  attachments: Attachment[];
  onAttach: (files: FileList) => void;
  onRemoveAttachment: (path: string) => void;
  onOpenSkills: () => void;
  onOpenFiles: () => void;
  onAtMention: () => void;
  onScreenshot: () => void;
  slashCommands: SlashCommand[];
}): JSX.Element {
  const { prefs } = usePrefs();
  const [dragging, setDragging] = useState(false);
  const [slashIdx, setSlashIdx] = useState(0);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const taRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 220)}px`;
  }, [value]);

  const change = (v: string): void => {
    // Open the file picker when the user types a fresh "@".
    if (v.endsWith("@") && (v.length === 1 || /\s/.test(v[v.length - 2]))) {
      onAtMention();
    }
    onChange(v);
    setSlashIdx(0);
  };

  const slashActive = value.startsWith("/") && !value.includes(" ") && !running;
  const slashQuery = value.slice(1).toLowerCase();
  const slashMatches = slashActive
    ? slashCommands.filter((c) => c.label.toLowerCase().includes(slashQuery))
    : [];

  const runSlash = (cmd: SlashCommand | undefined): void => {
    if (!cmd) return;
    onChange("");
    cmd.run();
  };

  const submit = (): void => {
    const trimmed = value.trim();
    if ((!trimmed && attachments.length === 0) || disabled) return;
    onSend(trimmed);
    onChange("");
  };

  return (
    <div className="composer-wrap">
      {slashMatches.length > 0 ? (
        <div className="slash-menu">
          {slashMatches.map((c, i) => (
            <div
              key={c.id}
              className={`slash-item ${i === slashIdx ? "active" : ""}`}
              onMouseEnter={() => setSlashIdx(i)}
              onMouseDown={(e) => {
                e.preventDefault();
                runSlash(c);
              }}
            >
              <span className="slash-label">{c.label}</span>
              {c.hint ? <span className="hint">{c.hint}</span> : null}
            </div>
          ))}
        </div>
      ) : null}
      <div
        className={`composer ${dragging ? "dragging" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (e.dataTransfer.files.length) onAttach(e.dataTransfer.files);
        }}
      >
        <div className="composer-main">
          {attachments.length > 0 ? (
            <div className="chips">
              {attachments.map((a) => (
                <span className="chip" key={a.path}>
                  <Paperclip size={12} /> {a.name}
                  <button onClick={() => onRemoveAttachment(a.path)}>
                    <X size={12} />
                  </button>
                </span>
              ))}
            </div>
          ) : null}
          <textarea
            ref={taRef}
            value={value}
            placeholder={
              disabled
                ? "Connecting…"
                : dragging
                  ? "Drop files to attach…"
                  : "Message your agent…  (/ commands · @ files · Shift+Enter newline)"
            }
            disabled={disabled}
            onChange={(e) => change(e.target.value)}
            onKeyDown={(e) => {
              if (slashMatches.length > 0) {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setSlashIdx((i) => Math.min(i + 1, slashMatches.length - 1));
                  return;
                }
                if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setSlashIdx((i) => Math.max(i - 1, 0));
                  return;
                }
                if (e.key === "Enter" || e.key === "Tab") {
                  e.preventDefault();
                  runSlash(slashMatches[slashIdx]);
                  return;
                }
                if (e.key === "Escape") {
                  onChange("");
                  return;
                }
              }
              const enterSends = prefs.enterToSend ? !e.shiftKey : e.metaKey || e.ctrlKey;
              if (e.key === "Enter" && enterSends) {
                e.preventDefault();
                submit();
              }
            }}
          />
        </div>
        <div className="composer-actions">
          <button className="icon-btn" title="Attach file" onClick={() => fileRef.current?.click()}>
            <Paperclip size={18} />
          </button>
          <button className="icon-btn" title="Skills" onClick={onOpenSkills}>
            <Sparkles size={18} />
          </button>
          <button className="icon-btn" title="Workspace files" onClick={onOpenFiles}>
            <FolderOpen size={18} />
          </button>
          <button className="icon-btn" title="Screenshot → agent" onClick={onScreenshot}>
            <Camera size={18} />
          </button>
          <VoiceButton onTranscript={(t) => onChange(value ? `${value} ${t}` : t)} />
          <input
            ref={fileRef}
            type="file"
            multiple
            style={{ display: "none" }}
            onChange={(e) => {
              if (e.target.files?.length) onAttach(e.target.files);
              e.target.value = "";
            }}
          />
          {running ? (
            <button className="cancel-btn" onClick={onCancel}>
              <Square size={13} fill="currentColor" /> Stop
            </button>
          ) : (
            <button
              className="send-btn"
              disabled={disabled || (!value.trim() && attachments.length === 0)}
              onClick={submit}
            >
              <Send size={15} /> Send
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
