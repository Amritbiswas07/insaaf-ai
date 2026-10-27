import { Link } from "react-router-dom";

const VALUES = [
  ["💻", "Developer-First", "We prioritize developer experience with comprehensive APIs, SDKs, and documentation that makes integration seamless and powerful."],
  ["🔧", "Open Source", "We believe in transparency and community collaboration. Our core libraries and tools are open-source and community-driven."],
  ["⚡", "Performance", "Built for scale with high-performance APIs, real-time processing, and optimized algorithms for enterprise-grade applications."],
  ["🔗", "Integration Ready", "Seamlessly integrate with existing legal tech stacks, case management systems, and third-party applications."],
];

const TEAM = [
  ["AJ", "Amandeep & Jab", "CEO & Co-Founder", "Full-stack developer with 10+ years building scalable legal tech applications and API platforms."],
  ["AB", "Amrit Biswas", "CTO & Co-Founder", "AI/ML engineer and former Google developer specializing in NLP and legal document processing."],
  ["SH", "Shahanawaz Hussain", "Lead Developer", "Backend architect with expertise in distributed systems and legal API design patterns."],
  ["OS", "Omkar & Shiv", "Developer Relations", "Developer advocate with experience building developer communities and technical documentation."],
];

const STATS = [
  ["5,000+", "Active Developers"],
  ["1M+", "API Calls Daily"],
  ["99.9%", "Uptime SLA"],
  ["50ms", "Average Response Time"],
];

export default function AboutPage() {
  return (
    <>
      <section className="hero hero--compact">
        <div className="container">
          <img src="/assets/statue4.png" alt="" className="statue2" />
          <h1 className="hero-title">About Insaaf</h1>
          <p className="hero-subtitle">
            Built by developers, for developers. We're revolutionizing legal tech with open-source tools, APIs, and
            AI-powered solutions.
          </p>
        </div>
      </section>

      <section className="section">
        <div className="container mission-content">
          <h2 className="section-title">Our Mission</h2>
          <p className="mission-text">
            To empower developers and legal professionals with cutting-edge AI tools, APIs, and open-source solutions that
            streamline legal workflows, automate document processing, and build the next generation of legal technology
            applications.
          </p>
        </div>
      </section>

      <section className="section">
        <div className="container">
          <h2 className="section-title">Our Values</h2>
          <div className="grid-auto-280">
            {VALUES.map(([icon, title, text]) => (
              <div key={title} className="glass-card">
                <span className="card-icon">{icon}</span>
                <h3>{title}</h3>
                <p>{text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="section" id="story">
        <div className="container story-content">
          <h2 className="section-title">Our Story</h2>
          <div className="story-text">
            <p>
              Founded in 2024 by a team of developers and legal tech enthusiasts, Insaaf emerged from the frustration of
              building legal applications with outdated, fragmented tools. Our founders, experienced software engineers and
              legal technology experts, recognized that the legal tech ecosystem lacked modern, developer-friendly APIs and
              tools.
            </p>
            <p>
              We started with a simple question: "What if legal technology was as easy to build as any other modern
              application?" This led to the development of our comprehensive API suite, AI-powered document processing
              tools, and developer-first platform that makes legal tech development accessible to any developer.
            </p>
            <p>
              Today, Insaaf powers thousands of legal applications worldwide, from solo developer projects to enterprise
              legal tech platforms. Our APIs process millions of legal documents, our AI models understand complex legal
              language, and our developer community continues to grow as we build the future of legal technology together.
            </p>
          </div>
        </div>
      </section>

      <section className="section" id="team">
        <div className="container">
          <h2 className="section-title">Our Team</h2>
          <div className="grid-auto-250">
            {TEAM.map(([initials, name, role, bio]) => (
              <div key={name} className="glass-card">
                <div className="member-avatar">{initials}</div>
                <h3>{name}</h3>
                <p className="member-role">{role}</p>
                <p className="member-bio">{bio}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="section">
        <div className="container">
          <h2 className="section-title">Our Impact</h2>
          <div className="grid-auto-200">
            {STATS.map(([n, label]) => (
              <div key={label} className="glass-card">
                <div className="stat-number">{n}</div>
                <div className="stat-label">{label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="section cta-section">
        <div className="container">
          <h2 className="section-title" style={{ marginBottom: 20 }}>Join Our Developer Community</h2>
          <p className="section-subtitle">Build the future of legal technology with our APIs, SDKs, and developer tools.</p>
          <div className="cta-buttons">
            <Link className="cta" to="/#plans">Start Building</Link>
            <Link className="cta" to="/contact">Developer Support</Link>
          </div>
        </div>
      </section>
    </>
  );
}
