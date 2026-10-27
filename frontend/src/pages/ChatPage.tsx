import { useEffect, useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Answer, { citationOrder, normalizeAnswer } from "../components/Answer";
import { describeTool, streamChat, type ChatMessage, type Citations, type Source } from "../lib/api";

interface Step {
  label: string;
  tool: boolean;
}

interface Turn {
  role: "user" | "assistant";
  content: string;
  at: number;
  steps?: Step[];
  citations?: Citations;
  meta?: { latency_ms: number; model: string; tool_calls: number };
  error?: string;
  streaming?: boolean;
}

const STORE_KEY = "insaaf.chat.v2";

const SUGGESTIONS = [
  ["Bail", "When has the Bombay High Court granted bail because of long incarceration or delay in trial?"],
  ["Murder", "What did the court consider when deciding bail in murder cases under Section 302 IPC?"],
  ["Dowry death", "Has bail been refused in dowry death cases under Section 304B IPC, and why?"],
  ["Arms Act", "How do courts treat bail applications involving Section 25 of the Arms Act?"],
];

function loadTurns(): Turn[] {
  try {
    const raw = sessionStorage.getItem(STORE_KEY);
    return raw ? (JSON.parse(raw) as Turn[]).map((t) => ({ ...t, streaming: false })) : [];
  } catch {
    return [];
  }
}

function time(ts: number) {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M3.4 20.4 21 12 3.4 3.6l-.01 6.53L15 12 3.39 13.87z" fill="currentColor" />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" />
    </svg>
  );
}

function SourcesCard({ citations, order }: { citations: Citations; order: string[] }) {
  const byId = new Map(citations.cited.map((s) => [s.id, s]));
  const cited = order.map((id) => byId.get(id)).filter((s): s is Source => Boolean(s));
  if (!cited.length && !citations.unverified.length && !citations.consulted.length) return null;
  return (
    <details className="sources" open={cited.length > 0}>
      <summary>
        📚 {cited.length ? `${cited.length} cited judgment${cited.length > 1 ? "s" : ""}` : "Sources consulted"}
      </summary>
      {cited.length > 0 && (
        <ul className="sources-list">
          {cited.map((s) => (
            <li key={s.id} className="source">
              <Link to={`/cases/${s.id}`} className="cite">
                {order.indexOf(s.id) + 1}
              </Link>
              <div>
                <Link to={`/cases/${s.id}`} className="source-title">
                  {s.title}
                </Link>
                <div className="source-meta">{[s.court, s.date].filter(Boolean).join(" · ")}</div>
                {s.summary && <div className="source-summary">{s.summary}</div>}
                {s.url && (
                  <a className="source-ext" href={s.url} target="_blank" rel="noreferrer">
                    Read on Indian Kanoon ↗
                  </a>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {citations.unverified.length > 0 && (
        <div className="sources-warn">
          ⚠ Cited but never retrieved: doc {citations.unverified.join(", ")}. Treat these references as unreliable.
        </div>
      )}
      {citations.consulted.length > 0 && (
        <div className="sources-more">
          Also reviewed:{" "}
          {citations.consulted.slice(0, 5).map((s, i) => (
            <span key={s.id}>
              {i > 0 && " · "}
              <Link to={`/cases/${s.id}`}>{s.title.split(" on ")[0]}</Link>
            </span>
          ))}
          {citations.consulted.length > 5 && ` and ${citations.consulted.length - 5} more`}
        </div>
      )}
    </details>
  );
}

export default function ChatPage() {
  const [turns, setTurns] = useState<Turn[]>(loadTurns);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState<number | null>(null);
  const [params, setParams] = useSearchParams();
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    try {
      sessionStorage.setItem(STORE_KEY, JSON.stringify(turns));
    } catch {
      /* storage unavailable */
    }
  }, [turns]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns]);

  useLayoutEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);

  // /chat?q=... (e.g. "Ask about this case") starts a question immediately.
  useEffect(() => {
    const q = params.get("q");
    if (q) {
      setParams({}, { replace: true });
      void send(q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    // Full-screen chat, as in v1: the page itself doesn't scroll, the thread does.
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
      abortRef.current?.abort();
    };
  }, []);

  function patchLast(fn: (t: Turn) => Turn) {
    setTurns((prev) => [...prev.slice(0, -1), fn(prev[prev.length - 1])]);
  }

  async function send(text: string) {
    const question = text.trim();
    if (!question || busy) return;
    const history: ChatMessage[] = [
      ...turns.filter((t) => !t.error && t.content).map(({ role, content }) => ({ role, content })),
      { role: "user", content: question },
    ];
    const now = Date.now();
    setTurns((prev) => [
      ...prev,
      { role: "user", content: question, at: now },
      { role: "assistant", content: "", at: now, steps: [], streaming: true },
    ]);
    setInput("");
    setBusy(true);
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      for await (const ev of streamChat(history, controller.signal)) {
        switch (ev.type) {
          case "status":
            if (ev.data.message !== "Writing answer")
              patchLast((t) => ({ ...t, steps: [...(t.steps ?? []), { label: ev.data.message, tool: false }] }));
            break;
          case "tool_call":
            patchLast((t) => ({
              ...t,
              steps: [...(t.steps ?? []), { label: describeTool(ev.data.name, ev.data.args), tool: true }],
            }));
            break;
          case "token":
            patchLast((t) => ({ ...t, content: t.content + ev.data.text }));
            break;
          case "citations":
            patchLast((t) => ({ ...t, citations: ev.data }));
            break;
          case "done":
            patchLast((t) => ({ ...t, content: ev.data.answer, streaming: false, meta: ev.data, at: Date.now() }));
            break;
          case "error":
            patchLast((t) => ({ ...t, streaming: false, error: ev.data.message }));
            break;
        }
      }
    } catch (err) {
      const e = err as Error;
      patchLast((t) => ({ ...t, error: e.name === "AbortError" ? "Stopped." : e.message }));
    } finally {
      patchLast((t) => ({ ...t, streaming: false }));
      setBusy(false);
      inputRef.current?.focus();
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void send(input);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send(input);
    }
  }

  async function copy(i: number, text: string) {
    try {
      await navigator.clipboard.writeText(normalizeAnswer(text).body.replace(/\[doc:(\d+)\]/g, "(Indian Kanoon doc $1)"));
      setCopied(i);
      window.setTimeout(() => setCopied(null), 1500);
    } catch {
      /* clipboard unavailable */
    }
  }

  return (
    <div className="chat-page">
      <div className="chat-scroll" ref={scrollRef}>
        {turns.length === 0 ? (
          <div className="welcome">
            <img src="/assets/insaaf-logo.svg" alt="" className="welcome-avatar" />
            <h1 className="welcome-title">How can Insaaf help you today?</h1>
            <p className="welcome-sub">
              Ask about bail, offences, procedure or a provision. Every answer is grounded in real judgments, with
              sources you can open.
            </p>
            <div className="suggestions">
              {SUGGESTIONS.map(([tag, q]) => (
                <button key={q} className="suggestion" onClick={() => void send(q)}>
                  <small>{tag}</small>
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="chat-thread">
            {turns.map((t, i) =>
              t.role === "user" ? (
                <div key={i} className="msg msg--user">
                  <div className="msg-col">
                    <div className="bubble bubble--user">{t.content}</div>
                    <div className="msg-meta">{time(t.at)}</div>
                  </div>
                </div>
              ) : (
                <div key={i} className="msg msg--bot">
                  <img src="/assets/insaaf-logo.svg" alt="Insaaf" className="msg-avatar" />
                  <div className="msg-col">
                    {!!t.steps?.length && (
                      <div className="steps">
                        {t.steps.map((s, j) => (
                          <span
                            key={j}
                            className={`step ${s.tool ? "step--tool" : ""} ${t.streaming && !t.content && j === t.steps!.length - 1 ? "step--active" : ""}`}
                          >
                            <i className="step-dot" />
                            <span>{s.label}</span>
                          </span>
                        ))}
                      </div>
                    )}
                    {(t.content || t.streaming) && (
                      <div className="bubble bubble--bot">
                        {t.content ? (
                          <Answer text={t.content} unverified={t.citations?.unverified} streaming={t.streaming} />
                        ) : (
                          <span className="typing" aria-label="Insaaf is researching">
                            <i />
                            <i />
                            <i />
                            <span className="typing-label">Researching case law…</span>
                          </span>
                        )}
                      </div>
                    )}
                    {t.error && <div className="error-note">{t.error === "Stopped." ? "Stopped." : `Something went wrong: ${t.error}`}</div>}
                    {t.citations && !t.streaming && <SourcesCard citations={t.citations} order={citationOrder(t.content)} />}
                    {!t.streaming && t.content && (
                      <div className="msg-meta">
                        <span>{time(t.at)}</span>
                        {t.meta && (
                          <span>
                            {(t.meta.latency_ms / 1000).toFixed(0)}s · {t.meta.tool_calls} lookup
                            {t.meta.tool_calls === 1 ? "" : "s"}
                          </span>
                        )}
                        <button onClick={() => void copy(i, t.content)}>{copied === i ? "Copied" : "Copy"}</button>
                      </div>
                    )}
                  </div>
                </div>
              ),
            )}
          </div>
        )}
      </div>

      <div className="composer">
        {turns.length > 0 && !busy && (
          <button className="new-chat" onClick={() => setTurns([])}>
            + New conversation
          </button>
        )}
        <form className="composer-form" onSubmit={onSubmit}>
          <textarea
            ref={inputRef}
            className="composer-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            placeholder="Ask me anything about legal matters..."
            aria-label="Your question"
          />
          {busy ? (
            <button type="button" className="send-btn" onClick={() => abortRef.current?.abort()} aria-label="Stop">
              <StopIcon />
            </button>
          ) : (
            <button type="submit" className="send-btn" disabled={!input.trim()} aria-label="Send">
              <SendIcon />
            </button>
          )}
        </form>
        <p className="composer-hint">Research assistance, not legal advice · Enter to send, Shift+Enter for a new line</p>
      </div>
    </div>
  );
}
