import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getCase, type CaseDetail } from "../lib/api";
import { formatDate, outcomeClass, prettyOutcome } from "./SearchPage";

const ROLE_LABEL: Record<string, string> = {
  Facts: "Facts",
  Issue: "Issue",
  PetArg: "Petitioner's argument",
  RespArg: "Respondent's argument",
  Section: "Statute",
  Precedent: "Precedent",
  CDiscource: "Court's reasoning",
  Conclusion: "Conclusion",
};

function CaseLinks({ title, items }: { title: string; items?: { id: string; title: string | null }[] }) {
  if (!items?.length) return null;
  return (
    <div className="panel">
      <h3>{title}</h3>
      <ul className="side-list">
        {items.map((c) => (
          <li key={c.id}>
            <Link to={`/cases/${c.id}`}>{c.title ?? `Judgment ${c.id} (not yet in the corpus)`}</Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function CasePage() {
  const { id = "" } = useParams();
  const [data, setData] = useState<CaseDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [role, setRole] = useState<string | null>(null);

  useEffect(() => {
    const ctl = new AbortController();
    setData(null);
    setError(null);
    setRole(null);
    getCase(id, ctl.signal)
      .then((d) => {
        setData(d);
        document.title = `${d.title.split(" on ")[0]} — Insaaf`;
      })
      .catch((e: Error) => e.name !== "AbortError" && setError(e.message));
    return () => ctl.abort();
  }, [id]);

  const roles = useMemo(
    () => [...new Set((data?.paragraphs ?? []).map((p) => p.role).filter((r) => r in ROLE_LABEL))],
    [data],
  );

  if (error) {
    return (
      <div className="page">
        <div className="container">
          <p className="notice notice--error">{error}</p>
          <a className="pill-btn" style={{ marginTop: 16 }} href={`https://indiankanoon.org/doc/${id}/`} target="_blank" rel="noreferrer">
            Open on Indian Kanoon ↗
          </a>
        </div>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="page">
        <div className="container">
          <p className="notice">Loading judgment…</p>
        </div>
      </div>
    );
  }

  const ins = data.insights;
  const paras = role ? data.paragraphs.filter((p) => p.role === role) : data.paragraphs;
  const shortTitle = data.title.split(" on ")[0];

  return (
    <div className="page">
      <div className="container">
        <header className="case-head">
          <h1 className="case-title">{data.title}</h1>
          <div className="meta-line">
            {data.court && <span>{data.court}</span>}
            {data.decision_date && <span>{formatDate(data.decision_date)}</span>}
            {data.bench.length > 0 && <span>Bench: {data.bench.join(", ")}</span>}
          </div>
          <div className="case-actions">
            <Link className="pill-btn" to={`/chat?q=${encodeURIComponent(`Explain the judgment in ${shortTitle} — what was decided and why?`)}`}>
              Ask Insaaf about this case
            </Link>
            {data.url && (
              <a className="pill-btn pill-btn--light" href={data.url} target="_blank" rel="noreferrer">
                Read on Indian Kanoon ↗
              </a>
            )}
          </div>
        </header>

        <div className="case-layout">
          <div>
            {ins && (
              <section className="panel">
                <h2>Case note</h2>
                <div className="tags" style={{ marginTop: 0, marginBottom: 14 }}>
                  {ins.case_type && <span className="tag tag--dark">{ins.case_type}</span>}
                  {ins.outcome && <span className={outcomeClass(ins.outcome)}>{prettyOutcome(ins.outcome)}</span>}
                </div>
                <div className="note-grid">
                  <p>{ins.summary}</p>
                  {ins.holding && (
                    <div>
                      <h4>What the court held</h4>
                      <p>{ins.holding}</p>
                    </div>
                  )}
                  {ins.legal_issues.length > 0 && (
                    <div>
                      <h4>Issues</h4>
                      <ul>{ins.legal_issues.map((x) => <li key={x}>{x}</li>)}</ul>
                    </div>
                  )}
                  {ins.key_principles.length > 0 && (
                    <div>
                      <h4>Principles</h4>
                      <ul>{ins.key_principles.map((x) => <li key={x}>{x}</li>)}</ul>
                    </div>
                  )}
                </div>
                <p className="ai-note">AI-generated case note — verify against the judgment text below.</p>
              </section>
            )}

            <section className="panel">
              <h2>Judgment</h2>
              {roles.length > 1 && (
                <div className="para-toolbar" role="group" aria-label="Filter paragraphs">
                  <button className="chip" aria-pressed={role === null} onClick={() => setRole(null)}>
                    All ({data.paragraphs.length})
                  </button>
                  {roles.map((r) => (
                    <button key={r} className="chip" aria-pressed={role === r} onClick={() => setRole(role === r ? null : r)}>
                      {ROLE_LABEL[r]}
                    </button>
                  ))}
                </div>
              )}
              <div className="paras">
                {paras.map((p) => (
                  <div key={p.idx} className="para">
                    <span className="para-num">¶{p.idx}</span>
                    <div>
                      {p.role in ROLE_LABEL && <span className={`para-role role-${p.role}`}>{ROLE_LABEL[p.role]}</span>}
                      <p className="para-text">{p.text}</p>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          </div>

          <aside>
            {data.statutes.length > 0 && (
              <div className="panel">
                <h3>Provisions applied</h3>
                <div className="tags" style={{ marginTop: 0 }}>
                  {data.statutes.map((s) => (
                    <Link key={s.key} to={`/search?q=${encodeURIComponent(s.label)}`} className="tag" title={`${s.mentions} mention(s)`} style={{ textDecoration: "none" }}>
                      {s.label}
                    </Link>
                  ))}
                </div>
              </div>
            )}
            <CaseLinks title="Relies on" items={data.graph.cites} />
            <CaseLinks title="Relied on by" items={data.graph.cited_by} />
            {data.parties.length > 0 && (
              <div className="panel">
                <h3>Parties</h3>
                <ul className="side-list">
                  {data.parties.map((p) => (
                    <li key={p.name}>
                      {p.name} <small>({p.role})</small>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </aside>
        </div>
      </div>
    </div>
  );
}
