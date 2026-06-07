import { BASE, TOKEN } from "./config";
import type {
  Agent,
  ConfigField,
  Controls,
  FsEntry,
  ModelGroup,
  ServerChatItem,
  SessionInfo,
  Skill,
  UploadResult,
} from "./types";

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${TOKEN}`,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    throw new Error(`${method} ${path} -> ${res.status}`);
  }
  return (await res.json()) as T;
}

export const api = {
  version: () => req<{ version: string }>("GET", "/version"),
  listSessions: () => req<SessionInfo[]>("GET", "/sessions"),
  createSession: (model?: string, agentId?: string, cwd?: string) =>
    req<SessionInfo>("POST", "/sessions", { model, agent_id: agentId, cwd }),
  getSession: (id: string) => req<SessionInfo>("GET", `/sessions/${id}`),
  getMessages: (id: string) => req<ServerChatItem[]>("GET", `/sessions/${id}/messages`),
  deleteSession: (id: string) => req<{ status: string }>("DELETE", `/sessions/${id}`),
  renameSession: (id: string, name: string) =>
    req<{ status: string }>("PUT", `/sessions/${id}/name`, { name }),
  getModels: () => req<{ models: string[]; providers: ModelGroup[] }>("GET", "/models"),
  setModel: (id: string, model: string) =>
    req<SessionInfo>("PUT", `/sessions/${id}/model`, { model }),
  setCwd: (id: string, path: string) => req<SessionInfo>("PUT", `/sessions/${id}/cwd`, { path }),
  browse: (path?: string) =>
    req<{ path: string; parent: string | null; entries: FsEntry[] }>(
      "GET",
      `/fs${path ? `?path=${encodeURIComponent(path)}` : ""}`,
    ),
  setControls: (id: string, controls: Controls) =>
    req<SessionInfo>("PUT", `/sessions/${id}/settings`, controls),
  getKeys: () => req<Record<string, boolean>>("GET", "/keys"),
  setKey: (provider: string, key: string) =>
    req<{ status: string }>("PUT", "/keys", { provider, key }),
  getAgents: () => req<Agent[]>("GET", "/agents"),
  getDefaultPrompt: () => req<{ prompt: string }>("GET", "/agents/default-prompt"),
  createAgent: (a: Omit<Agent, "id" | "builtin">) => req<Agent>("POST", "/agents", a),
  updateAgent: (id: string, a: Omit<Agent, "id" | "builtin">) =>
    req<Agent>("PUT", `/agents/${id}`, a),
  deleteAgent: (id: string) => req<{ status: string }>("DELETE", `/agents/${id}`),
  setSessionAgent: (id: string, agentId: string) =>
    req<SessionInfo>("PUT", `/sessions/${id}/agent`, { agent_id: agentId }),
  cancel: (id: string) => req<{ cancelled: boolean }>("POST", `/sessions/${id}/cancel`),
  getConfig: () => req<Record<string, unknown>>("GET", "/config"),
  getConfigSchema: () => req<ConfigField[]>("GET", "/config/schema"),
  updateConfig: (key: string, value: unknown) =>
    req<{ status: string }>("PUT", "/config", { key, value }),
  getSkills: () => req<Skill[]>("GET", "/skills"),
  getSkill: (name: string) => req<{ name: string; content: string }>("GET", `/skills/${name}`),
  createSkill: (name: string, description: string, content: string) =>
    req<{ name: string }>("POST", "/skills", { name, description, content }),
  getFiles: (id: string) => req<UploadResult[]>("GET", `/sessions/${id}/files`),
  screenshot: (id: string) => req<UploadResult>("POST", `/sessions/${id}/screenshot`),
  uploadFile: async (id: string, file: File): Promise<UploadResult> => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`${BASE}/sessions/${id}/upload`, {
      method: "POST",
      headers: { Authorization: `Bearer ${TOKEN}` },
      body: fd,
    });
    if (!res.ok) throw new Error(`upload -> ${res.status}`);
    return (await res.json()) as UploadResult;
  },
};
