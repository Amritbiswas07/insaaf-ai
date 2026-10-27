export type Role = "user" | "assistant";

export interface ChatMessage {
  role: Role;
  content: string;
}

export interface Source {
  id: string;
  title: string;
  court: string | null;
  date: string | null;
  url: string | null;
  summary: string | null;
}

export interface Citations {
  cited: Source[];
  unverified: string[];
  consulted: Source[];
}

export interface AgentStep {
  kind: "status" | "tool";
  label: string;
}

export type StreamEvent =
  | { type: "status"; data: { message: string } }
  | { type: "tool_call"; data: { name: string; args: Record<string, unknown> } }
  | { type: "tool_result"; data: { name: string; args: Record<string, unknown>; sources: number } }
  | { type: "token"; data: { text: string } }
  | { type: "citations"; data: Citations }
  | { type: "done"; data: { answer: string; tool_calls: number; latency_ms: number; model: string } }
  | { type: "error"; data: { message: string } };

export interface CaseHit {
  id: string;
  title: string;
  court: string | null;
  date: string | null;
  url: string | null;
  summary: string | null;
  outcome: string | null;
  statutes: string[];
  cited_by_count: number;
  score: number;
  passages: { text: string; roles: string[] }[];
}

export interface SearchResponse {
  query: string;
  results: CaseHit[];
  precedents: { id: string; title: string | null; support: number }[];
}

export interface CaseDetail {
  id: string;
  title: string;
  url: string | null;
  court: string | null;
  decision_date: string | null;
  bench: string[];
  parties: { name: string; role: string }[];
  insights: {
    summary: string;
    case_type: string;
    legal_issues: string[];
    holding: string;
    outcome: string;
    key_principles: string[];
  } | null;
  statutes: { label: string; mentions: number; key: string }[];
  paragraphs: { idx: number; role: string; text: string }[];
  graph: {
    judges?: string[];
    statutes?: string[];
    cites?: { id: string; title: string | null }[];
    cited_by?: { id: string; title: string | null }[];
  };
  status: string | null;
}

const BASE = import.meta.env.VITE_API_BASE ?? "";

function headers(): HeadersInit {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  const key = import.meta.env.VITE_API_KEY;
  if (key) h["X-API-Key"] = key;
  return h;
}

async function getJSON<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: headers(), signal });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail ?? `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export interface Stats {
  pipeline: Record<string, number>;
  graph: { cases?: number; chunks?: number; sections?: number; judges?: number; citations?: number };
  models: { chat: string; extract: string; embed: string };
}

export const getStats = (signal?: AbortSignal) => getJSON<Stats>("/api/stats", signal);

export const searchCases = (q: string, signal?: AbortSignal) =>
  getJSON<SearchResponse>(`/api/search?q=${encodeURIComponent(q)}&limit=15`, signal);

export const getCase = (id: string, signal?: AbortSignal) =>
  getJSON<CaseDetail>(`/api/cases/${encodeURIComponent(id)}`, signal);

/** POST /api/chat and yield server-sent events as they arrive. */
export async function* streamChat(
  messages: ChatMessage[],
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const res = await fetch(`${BASE}/api/chat`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ messages, stream: true }),
    signal,
  });
  if (!res.ok || !res.body) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(
      typeof detail.detail === "string" ? detail.detail : `Chat request failed (${res.status})`,
    );
  }

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let type = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) type = line.slice(7).trim();
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (data) yield { type, data: JSON.parse(data) } as StreamEvent;
    }
  }
}

export const TOOL_LABELS: Record<string, string> = {
  search_case_law: "Searched case law",
  get_case_details: "Read judgment",
  find_related_cases: "Followed citations",
  cases_applying_statute: "Looked up provision",
};

export function describeTool(name: string, args: Record<string, unknown>): string {
  const label = TOOL_LABELS[name] ?? name;
  const detail =
    (args.query as string) ??
    (args.case_id ? `doc ${args.case_id}${args.relation ? ` · ${args.relation}` : ""}` : "") ??
    "";
  const statute = args.act ? `${args.section ? `s. ${args.section} ` : ""}${args.act}` : "";
  return [label, detail || statute].filter(Boolean).join(": ");
}
