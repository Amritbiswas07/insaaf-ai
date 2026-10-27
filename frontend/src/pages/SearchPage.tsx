import { useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { searchCases, type SearchResponse } from "../lib/api";

const EXAMPLES = ["bail long incarceration", "Section 302 IPC murder", "dowry death 304B", "Arms Act Section 25", "cheating 420 IPC"];

export function outcomeClass(outcome?: string | null) {
  if (!outcome) return "outcome";
  if (/granted|allowed|acquitted/.test(outcome)) return "outcome outcome--good";
  if (/rejected|dismissed|convicted/.test(outcome)) return "outcome outcome--bad";
  return "outcome";
}

export const prettyOutcome = (o?: string | null) => (o ? o.replace(/_/g, " ") : "");

export function formatDate(d?: string | null) {
  if (!d) return null;
  const date = new Date(d);
  return Number.isNaN(date.getTime()) ? d : date.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export default function SearchPage() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const [input, setInput] = useState(q);
  const [data, setData] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => setInput(q), [q]);

  useEffect(() => {
    if (q.length < 2) {
      setData(null);
      return;
    }
    const ctl = new AbortController();
    setLoading(true);
    setError(null);
    searchCases(q, ctl.signal)
      .then(setData)
      .catch((e: Error) => e.name !== "AbortError" && setError(e.message))
      .finally(() => setLoading(false));
    return () => ctl.abort();
  }, [q]);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setParams(input.trim() ? { q: input.trim() } : {});
  }

  return (
    <div className="page">
      <div className="container">
        <h1 className="page-title">Case Search</h1>
        <p className="page-sub">Search judgments by meaning or exact legal terms — ranked by relevance and authority.</p>

        <form className="search-bar" onSubmit={onSubmit} role="search">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="e.g. bail in murder case after long custody"
            aria-label="Search judgments"
          />
          <button className="pill-btn" type="submit">
            Search
          </button>
        </form>
        <div className="filter-row">
          {EXAMPLES.map((ex) => (
            <button key={ex} className="chip" onClick={() => setParams({ q: ex })}>
              {ex}
            </button>
          ))}
        </div>

        {loading && <p className="result-count">Searching…</p>}
        {error && <p className="notice notice--error" style={{ marginTop: 24 }}>{error}</p>}

        {data && !loading && (
          <>
            <p className="result-count">
              {data.results.length} judgment{data.results.length === 1 ? "" : "s"} for “{data.query}”
            </p>
            {data.results.length === 0 && (
              <p className="notice">No matching judgments yet. Try different words, or ask the assistant instead.</p>
            )}
            <ul className="results">
              {data.results.map((r) => (
                <li key={r.id} className="result-card">
                  <Link to={`/cases/${r.id}`} className="result-title">
                    {r.title}
                  </Link>
                  <div className="meta-line">
                    {r.court && <span>{r.court}</span>}
                    {r.date && <span>{formatDate(r.date)}</span>}
                    {r.outcome && <span className={outcomeClass(r.outcome)}>{prettyOutcome(r.outcome)}</span>}
                    {r.cited_by_count > 0 && <span>Cited by {r.cited_by_count}</span>}
                  </div>
                  {r.summary && <p className="result-summary">{r.summary}</p>}
                  {r.passages[0] && <blockquote className="result-quote">{r.passages[0].text}</blockquote>}
                  {r.statutes.length > 0 && (
                    <div className="tags">
                      {r.statutes.slice(0, 6).map((s) => (
                        <span key={s} className="tag">
                          {s}
                        </span>
                      ))}
                    </div>
                  )}
                </li>
              ))}
            </ul>
            {data.precedents.length > 0 && (
              <div className="panel" style={{ marginTop: 24 }}>
                <h2>Leading precedents in these results</h2>
                <ul className="side-list">
                  {data.precedents.map((p) => (
                    <li key={p.id}>
                      <Link to={`/cases/${p.id}`}>{p.title ?? `Judgment ${p.id}`}</Link>{" "}
                      <small>— relied on by {p.support} of the results</small>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}

        {!data && !loading && !error && (
          <p className="notice" style={{ marginTop: 28 }}>
            Tip: describe the situation in your own words — “bail refused because accused may tamper with witnesses” works
            as well as section numbers.
          </p>
        )}
      </div>
    </div>
  );
}
