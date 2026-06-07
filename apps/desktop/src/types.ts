// Wire types — mirror of `pydantic_deep.session.events` + gateway schemas.
// Every event carries a `type` discriminator.

export type SessionEvent =
  | { type: "run_started" }
  | { type: "text_delta"; text: string }
  | { type: "thinking_delta"; text: string }
  | {
      type: "tool_call_started";
      id: string;
      name: string;
      args: Record<string, unknown>;
      title: string;
      kind: string;
    }
  | {
      type: "tool_call_result";
      id: string;
      content: string;
      is_error: boolean;
      status: "completed" | "error";
    }
  | { type: "run_completed"; output: unknown }
  | { type: "run_cancelled" }
  | { type: "run_error"; message: string };

export interface SessionStats {
  type: "session_stats";
  cost: { run_usd?: number; total_usd?: number; input?: number; output?: number };
  context: { pct?: number; current?: number; max?: number };
  message_count: number;
}

export type GatewayMessage = SessionEvent | SessionStats;

export interface SessionInfo {
  id: string;
  model: string;
  cwd: string;
  name: string | null;
  created_at: number;
  message_count: number;
  thinking?: string | null;
  temperature?: number | null;
  agent_id: string;
  agent_name: string;
  agent_avatar: string;
  agent_color: string;
}

export interface Agent {
  id: string;
  name: string;
  avatar: string;
  color: string;
  prompt: string;
  builtin: boolean;
}

export interface Controls {
  thinking?: string;
  temperature?: number;
}

export interface ModelGroup {
  id: string;
  label: string;
  models: string[];
}

export interface FsEntry {
  name: string;
  is_dir: boolean;
  path: string;
}

export interface ConfigField {
  name: string;
  type: string;
}

export interface Skill {
  name: string;
  description: string;
}

export interface UploadResult {
  path: string;
  name: string;
  size: number;
}

export interface Attachment {
  path: string;
  name: string;
}

export type ToolStatus = "running" | "completed" | "error";

export interface ToolCall {
  id: string;
  name: string;
  title: string;
  kind: string;
  status: ToolStatus;
  result?: string;
}

export type ChatItem =
  | { kind: "user"; id: string; text: string }
  | {
      kind: "assistant";
      id: string;
      text: string;
      thinking: string;
      tools: ToolCall[];
      running: boolean;
      error?: string;
    };

// Transcript items returned by GET /sessions/{id}/messages (no client id yet).
export type ServerChatItem =
  | { kind: "user"; text: string }
  | {
      kind: "assistant";
      text: string;
      thinking: string;
      tools: ToolCall[];
      running: boolean;
    };
