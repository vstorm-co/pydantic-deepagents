import type { ChatItem, ServerChatItem, SessionEvent, ToolCall } from "./types";

let counter = 0;
const nextId = (): string => `m${(counter += 1)}`;

export type ChatAction =
  | { kind: "user_prompt"; text: string }
  | { kind: "event"; event: SessionEvent }
  | { kind: "load"; items: ServerChatItem[] }
  | { kind: "reset" };

type Assistant = Extract<ChatItem, { kind: "assistant" }>;

function lastAssistantIndex(items: ChatItem[]): number {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    if (items[i].kind === "assistant") return i;
  }
  return -1;
}

function applyEvent(item: Assistant, event: SessionEvent): Assistant {
  switch (event.type) {
    case "text_delta":
      return { ...item, text: item.text + event.text };
    case "thinking_delta":
      return { ...item, thinking: item.thinking + event.text };
    case "tool_call_started": {
      const tool: ToolCall = {
        id: event.id,
        name: event.name,
        title: event.title,
        kind: event.kind,
        status: "running",
      };
      return { ...item, tools: [...item.tools, tool] };
    }
    case "tool_call_result": {
      const tools = item.tools.map((t) =>
        t.id === event.id
          ? { ...t, status: event.is_error ? ("error" as const) : ("completed" as const), result: event.content }
          : t,
      );
      return { ...item, tools };
    }
    case "run_completed":
    case "run_cancelled":
      return { ...item, running: false };
    case "run_error":
      return { ...item, running: false, error: event.message };
    case "run_started":
      return item;
  }
}

export function chatReducer(items: ChatItem[], action: ChatAction): ChatItem[] {
  if (action.kind === "reset") return [];
  if (action.kind === "load") {
    return action.items.map((it) => ({ ...it, id: nextId() }) as ChatItem);
  }
  if (action.kind === "user_prompt") {
    return [
      ...items,
      { kind: "user", id: nextId(), text: action.text },
      {
        kind: "assistant",
        id: nextId(),
        text: "",
        thinking: "",
        tools: [],
        running: true,
      },
    ];
  }
  const idx = lastAssistantIndex(items);
  if (idx < 0) return items;
  const updated = applyEvent(items[idx] as Assistant, action.event);
  const next = items.slice();
  next[idx] = updated;
  return next;
}
