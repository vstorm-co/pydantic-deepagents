import { ChevronUp, File as FileIcon, Folder, HardDrive, Home } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useToast } from "../toast";
import type { FsEntry } from "../types";

export function FileBrowser({
  mode,
  initialPath,
  onPick,
  onClose,
}: {
  mode: "file" | "folder";
  initialPath?: string;
  onPick: (path: string) => void;
  onClose: () => void;
}): JSX.Element {
  const toast = useToast();
  const [path, setPath] = useState(initialPath ?? "");
  const [parent, setParent] = useState<string | null>(null);
  const [entries, setEntries] = useState<FsEntry[]>([]);

  const load = useCallback(
    (p?: string) => {
      api
        .browse(p)
        .then((r) => {
          setPath(r.path);
          setParent(r.parent);
          setEntries(r.entries);
        })
        .catch((e) => toast.push(String(e), "error"));
    },
    [toast],
  );

  useEffect(() => load(initialPath), [load, initialPath]);

  return (
    <div className="overlay" onClick={onClose}>
      <div className="panel" onClick={(e) => e.stopPropagation()}>
        <div className="panel-head">
          <h2>{mode === "folder" ? "Choose working folder" : "Pick a file"}</h2>
          <div style={{ display: "flex", gap: 6 }}>
            <button className="icon-btn" title="Home" onClick={() => load("")}>
              <Home size={16} />
            </button>
            <button className="icon-btn" title="Whole computer" onClick={() => load("/")}>
              <HardDrive size={16} />
            </button>
          </div>
        </div>
        <div className="fs-path" title={path}>
          {parent ? (
            <button className="icon-btn" title="Up" onClick={() => load(parent)}>
              <ChevronUp size={16} />
            </button>
          ) : null}
          <span className="fs-current">{path}</span>
        </div>
        <div className="panel-body fs-list">
          {entries.map((e) => (
            <div
              key={e.path}
              className="fs-entry"
              onClick={() => (e.is_dir ? load(e.path) : mode === "file" ? onPick(e.path) : undefined)}
              onDoubleClick={() => !e.is_dir && mode === "file" && onPick(e.path)}
            >
              {e.is_dir ? (
                <Folder size={16} className="fs-folder" />
              ) : (
                <FileIcon size={16} className="fs-file" />
              )}
              <span className="fs-name">{e.name}</span>
            </div>
          ))}
          {entries.length === 0 ? <div className="muted pad">Empty folder</div> : null}
        </div>
        {mode === "folder" ? (
          <div className="fs-foot">
            <button className="send-btn" onClick={() => onPick(path)}>
              Use this folder
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
