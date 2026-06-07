import { FileText, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useToast } from "../toast";
import type { UploadResult } from "../types";

function fmtSize(n: number): string {
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)} KB`;
  return `${n} B`;
}

export function FilesPanel({
  sessionId,
  onUse,
  onClose,
}: {
  sessionId: string | null;
  onUse: (path: string) => void;
  onClose: () => void;
}): JSX.Element {
  const toast = useToast();
  const [files, setFiles] = useState<UploadResult[]>([]);

  useEffect(() => {
    if (!sessionId) return;
    api
      .getFiles(sessionId)
      .then(setFiles)
      .catch((e) => toast.push(String(e), "error"));
  }, [sessionId, toast]);

  return (
    <div className="overlay" onClick={onClose}>
      <div className="panel" onClick={(e) => e.stopPropagation()}>
        <div className="panel-head">
          <h2>Workspace files</h2>
          <button className="icon-btn" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <div className="panel-body">
          <div className="muted pad" style={{ paddingLeft: 0 }}>
            Files you've uploaded into this session's <code>uploads/</code> folder.
          </div>
          {files.map((f) => (
            <div className="setting-row" key={f.path}>
              <span style={{ flex: 1, display: "inline-flex", alignItems: "center", gap: 8 }}>
                <FileText size={14} /> {f.name} <span className="muted">· {fmtSize(f.size)}</span>
              </span>
              <button
                className="settings-btn"
                style={{ flex: "none" }}
                onClick={() => {
                  onUse(f.path);
                  onClose();
                }}
              >
                Reference
              </button>
            </div>
          ))}
          {files.length === 0 ? (
            <div className="muted pad">No files yet — drag one onto the composer.</div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
