import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getStats, type Stats } from "../lib/api";

const PROBLEMS =
  "Over 5.2 crore cases pending in Indian courts • 4.2 crore in district courts, 59 lakh in high courts, 81,000 in Supreme Court • Delayed justice – cases take 10–15 years • 70% of Indians unaware of basic legal rights • High lawyer-to-citizen ratio – 1 lawyer per 1,200 citizens • Legal fees unaffordable – ₹5,000 to ₹50,000 per case • People unaware how to file FIR, bail, property disputes • Exploitation of poor and uneducated due to lack of awareness • Language barrier – most legal info in English";
const SOLUTIONS =
  "24/7 free legal guidance • Local language support • Simple explanations of laws • Helps in document generation • Connects to verified lawyers/legal aid • Reduces court backlog • Empowers citizens with knowledge";

function Marquee({ text, size, reverse }: { text: string; size: "large" | "small"; reverse?: boolean }) {
  return (
    <div className="marquee-container">
      <div className={`marquee-content marquee-content-${reverse ? "reverse" : "forward"}`}>
        {[0, 1].map((i) => (
          <div key={i} className="marquee-text-block" aria-hidden={i === 1}>
            <span className={`marquee-text-${size}`}>{text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const PLANS = [
  {
    name: "Starter",
    desc: "Ideal for small projects",
    price: null,
    features: ["Basic AI Chatbot (20 queries/month)", "Legal Document Templates", "General Legal Info", "Community Support", "Web & Mobile Access"],
    action: { label: "Try for free", to: "/chat" },
  },
  {
    name: "Professional",
    desc: "For freelancers and startups",
    price: { monthly: 15, annual: 12 },
    highlight: "All starter features +",
    features: ["Unlimited AI Queries", "Advanced Document Drafting", "Case Law Search & Summaries", "Secure Document Storage (10GB)", "Priority Email Support"],
    action: { label: "Select plan", to: "/contact" },
    popular: true,
  },
  {
    name: "Organization",
    desc: "For fast-growing businesses",
    price: { monthly: 30, annual: 25 },
    highlight: "All professional features +",
    features: ["Team Collaboration Tools", "Role-Based Access Control", "Bulk Document Processing", "Integration with Case Management Tools", "Dedicated 24/7 Support"],
    action: { label: "Select plan", to: "/contact" },
  },
];

function Plans() {
  const [billing, setBilling] = useState<"monthly" | "annual">("monthly");
  return (
    <section id="plans" className="plans">
      <div className="plans-header container">
        <h2 className="plans-title">Plans &amp; Pricing</h2>
        <p className="plans-desc">
          Choose the plan that fits your needs. All plans include essential features to get you started, with options to
          scale as you grow. No hidden fees and the flexibility to change anytime.
        </p>
        <div className="billing-toggle">
          <div className="toggle-track" role="group" aria-label="Billing period">
            {(["monthly", "annual"] as const).map((p) => (
              <button key={p} className="toggle-btn" aria-pressed={billing === p} onClick={() => setBilling(p)}>
                {p === "monthly" ? "Monthly" : "Annual"}
              </button>
            ))}
          </div>
          <div className="toggle-note">-15% off on annual payments</div>
        </div>
      </div>

      <div className="plan-grid container">
        {PLANS.map((plan) => {
          const card = (
            <div className="card">
              <header className="plan-header">
                <div className="plan-name">{plan.name}</div>
                <div className="plan-desc">{plan.desc}</div>
                <div className="plan-price">
                  {plan.price ? (
                    <>
                      <span className="price-currency">$</span>
                      <span className="price-value">{plan.price[billing]}</span>
                      <span className="price-unit"> /per user</span>
                    </>
                  ) : (
                    <span className="price-value">Free</span>
                  )}
                </div>
              </header>
              <div className="features">
                {plan.highlight && (
                  <div className="feature feature--highlight">
                    <div className="checkmark">✓</div>
                    <div className="feature-text">{plan.highlight}</div>
                  </div>
                )}
                {plan.features.map((f) => (
                  <div key={f} className="feature">
                    <div className="checkmark">✓</div>
                    <div className="feature-text">{f}</div>
                  </div>
                ))}
              </div>
              <div className="plan-action">
                <Link className="plan-button" to={plan.action.to}>
                  {plan.action.label}
                </Link>
                {plan.popular && <div className="alt-action">or contact sales</div>}
              </div>
            </div>
          );
          return plan.popular ? (
            <article key={plan.name} className="card--highlight-wrap">
              <div className="highlight-label">MOST POPULAR PLAN</div>
              {card}
            </article>
          ) : (
            <article key={plan.name}>{card}</article>
          );
        })}
      </div>
    </section>
  );
}

function Capabilities() {
  const [stats, setStats] = useState<Stats | null>(null);
  useEffect(() => {
    const ctl = new AbortController();
    getStats(ctl.signal).then(setStats).catch(() => undefined);
    return () => ctl.abort();
  }, []);
  const g = stats?.graph;

  return (
    <section className="section" id="features">
      <div className="container">
        <h2 className="section-title">What Insaaf can do today</h2>
        <div className="grid-auto-280">
          <Link to="/chat" className="glass-card">
            <span className="card-icon">⚖️</span>
            <h3>Ask a legal question</h3>
            <p>Get a plain-language answer grounded in real judgments, with every case it relies on cited and linked.</p>
            <span className="card-link">Try the assistant →</span>
          </Link>
          <Link to="/search" className="glass-card">
            <span className="card-icon">🔎</span>
            <h3>Search case law</h3>
            <p>Find judgments by meaning, not just keywords — ranked by relevance and how often courts rely on them.</p>
            <span className="card-link">Search judgments →</span>
          </Link>
          <Link to="/search?q=bail" className="glass-card">
            <span className="card-icon">📜</span>
            <h3>Read judgments simply</h3>
            <p>Every judgment comes with a case note: the issues, what the court held, the outcome and the provisions applied.</p>
            <span className="card-link">Explore a case →</span>
          </Link>
        </div>
        {g?.cases ? (
          <div className="grid-auto-200" style={{ marginTop: 40 }}>
            {[
              [g.cases, "Judgments indexed"],
              [g.sections, "Statutory provisions linked"],
              [g.judges, "Judges in the graph"],
              [g.chunks, "Searchable passages"],
            ].map(([n, label]) => (
              <div key={label} className="glass-card">
                <div className="stat-number">{(n ?? 0).toLocaleString("en-IN")}</div>
                <div className="stat-label">{label}</div>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </section>
  );
}

export default function HomePage() {
  return (
    <>
      <section className="hero">
        <div className="container">
          <img src="/assets/statue4.png" alt="" className="statue2" />
          <h1 className="hero-title">
            Justice.
            <br />
            Simplified with
            <br />
            AI.
          </h1>
          <p className="hero-subtitle">
            Your AI legal assistant for contracts, queries, and simplified law – anytime, anywhere.
          </p>
          <div className="hero-ctas">
            <Link className="cta" to="/#plans">
              Get Started
            </Link>
            <Link className="cta" to="/chat">
              Try Demo
            </Link>
          </div>
        </div>
      </section>

      <section className="infinite-scroll-section" aria-label="Why Insaaf">
        <Marquee text={PROBLEMS} size="large" />
        <Marquee text={SOLUTIONS} size="small" reverse />
      </section>

      <Capabilities />
      <Plans />
    </>
  );
}
