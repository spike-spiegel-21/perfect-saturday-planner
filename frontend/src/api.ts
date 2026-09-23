import type {
  AssistantTurn,
  Health,
  MemoryOut,
  OptionKind,
  SessionOut,
  Simulate,
  TraceEvent,
} from "./types";

const BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/+$/, "");

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const OFFLINE = "I can't reach the planner server right now. Check your connection and try again.";

async function errorFrom(res: Response): Promise<ApiError> {
  let detail = res.statusText || `HTTP ${res.status}`;
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") detail = body.detail;
    else if (body?.detail) detail = JSON.stringify(body.detail);
  } catch {
    /* not JSON */
  }
  return new ApiError(res.status, detail);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, OFFLINE);
  }
  if (!res.ok) throw await errorFrom(res);
  return (await res.json()) as T;
}

export const api = {
  health: () => request<Health>("/health"),
  createSession: (userId: string) =>
    request<SessionOut>("/api/sessions", { method: "POST", body: JSON.stringify({ user_id: userId }) }),
  getSession: (sessionId: string) => request<SessionOut>(`/api/sessions/${sessionId}`),
  sendMessage: (sessionId: string, text: string) =>
    request<AssistantTurn>(`/api/sessions/${sessionId}/messages`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  choose: (sessionId: string, runId: string, kind: OptionKind) =>
    request<{ ok: boolean }>(`/api/sessions/${sessionId}/choose`, {
      method: "POST",
      body: JSON.stringify({ run_id: runId, kind }),
    }),
  memory: (userId: string) => request<MemoryOut>(`/api/users/${userId}/memory`),
  forget: (userId: string) => request<{ ok: boolean }>(`/api/users/${userId}`, { method: "DELETE" }),
};

/**
 * Start a planning run and feed each SSE event to `onEvent` as it arrives.
 * The endpoint is a POST, so this reads the stream with fetch instead of EventSource.
 */
export async function streamPlan(
  sessionId: string,
  simulate: Simulate | null,
  onEvent: (event: TraceEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const qs = simulate ? `?simulate=${encodeURIComponent(simulate)}` : "";
  let res: Response;
  try {
    res = await fetch(`${BASE}/api/sessions/${sessionId}/plan${qs}`, {
      method: "POST",
      headers: { Accept: "text/event-stream" },
      signal,
    });
  } catch {
    if (signal?.aborted) return;
    throw new ApiError(0, OFFLINE);
  }
  if (!res.ok || !res.body) throw await errorFrom(res);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const flush = (chunk: string) => {
    const data = chunk
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).replace(/^ /, ""))
      .join("\n");
    if (!data) return; // heartbeat / comment line
    try {
      onEvent(JSON.parse(data) as TraceEvent);
    } catch {
      /* ignore a malformed frame rather than killing the run */
    }
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let match: RegExpExecArray | null;
      while ((match = /\r?\n\r?\n/.exec(buffer))) {
        flush(buffer.slice(0, match.index));
        buffer = buffer.slice(match.index + match[0].length);
      }
    }
    buffer += decoder.decode();
    if (buffer.trim()) flush(buffer);
  } catch {
    if (signal?.aborted) return;
    throw new ApiError(0, "The connection dropped while planning. Your plan may still finish — try reloading.");
  }
}
