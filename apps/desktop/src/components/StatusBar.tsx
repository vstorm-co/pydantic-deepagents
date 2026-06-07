import { ArrowDown, ArrowUp } from "lucide-react";
import type { SessionStats } from "../types";
import type { SocketStatus } from "../ws";

function fmtTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(Math.round(n));
}

export function StatusBar({
  model,
  status,
  version,
  messageCount,
  stats,
  running,
  elapsed,
}: {
  model: string;
  status: SocketStatus;
  version: string;
  messageCount: number;
  stats: SessionStats | null;
  running: boolean;
  elapsed: number;
}): JSX.Element {
  const cost = stats?.cost?.total_usd ?? 0;
  const input = stats?.cost?.input ?? 0;
  const output = stats?.cost?.output ?? 0;
  const ctxPct = stats?.context?.pct ?? 0;

  return (
    <div className="statusbar">
      <span className={`dot dot-${status}`} />
      <span>{status}</span>
      <span className="sep">·</span>
      <span>{model}</span>
      {running ? (
        <>
          <span className="sep">·</span>
          <span className="working">
            <span className="work-dot" /> working {elapsed}s
          </span>
        </>
      ) : null}
      <span className="sep">·</span>
      <span>{messageCount} msgs</span>
      {cost > 0 ? (
        <>
          <span className="sep">·</span>
          <span>${cost < 0.01 ? cost.toFixed(4) : cost.toFixed(2)}</span>
        </>
      ) : null}
      {input + output > 0 ? (
        <>
          <span className="sep">·</span>
          <span className="tok">
            <ArrowUp size={11} />
            {fmtTokens(input)}
            <ArrowDown size={11} />
            {fmtTokens(output)}
          </span>
        </>
      ) : null}
      {ctxPct > 0 ? (
        <>
          <span className="sep">·</span>
          <span
            className={ctxPct > 0.85 ? "ctx-warn" : ctxPct > 0.6 ? "ctx-mid" : ""}
            title="Context window used"
          >
            {Math.round(ctxPct * 100)}% ctx
          </span>
        </>
      ) : null}
      <span className="spacer" />
      <span className="muted">pydantic-deep v{version}</span>
    </div>
  );
}
