import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

const FAQ = [
  ["How does the AI legal assistant work?", "Insaaf searches a knowledge graph of real Indian judgments — by meaning and by exact legal terms — then explains what the courts decided in plain language, citing every judgment it relies on."],
  ["Is my information secure?", "Yes, we use enterprise-grade encryption and security measures to protect all your data and conversations. Your privacy is our top priority."],
  ["Can I get a demo before subscribing?", "Absolutely! You can try our demo for free to experience the full capabilities of our AI legal assistant before committing to a subscription."],
  ["What types of legal questions can the AI help with?", "Our AI can assist with contract analysis, legal research, document review, compliance questions, and general legal guidance across various practice areas."],
  ["How accurate are the AI responses?", "Every citation is checked against the judgments the assistant actually retrieved, and unverified ones are flagged. Still, please consult a qualified lawyer for matters requiring formal legal advice."],
  ["Can I integrate Insaaf with my existing legal software?", "Yes! We offer comprehensive APIs and integration tools that allow seamless connectivity with most legal practice management systems, case management software, and document repositories."],
];

export default function ContactPage({ notify }: { notify: (msg: string) => void }) {
  const [form, setForm] = useState({ name: "", email: "", subject: "", message: "" });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const body = `${form.message}\n\n— ${form.name} (${form.email})`;
    window.location.href = `mailto:support@insaaf.ai?subject=${encodeURIComponent(form.subject)}&body=${encodeURIComponent(body)}`;
    notify("Opening your email app to send the message…");
  }

  return (
    <>
      <section className="hero hero--compact">
        <div className="container">
          <img src="/assets/statue4.png" alt="" className="statue2" />
          <h1 className="hero-title">Get in Touch</h1>
          <p className="hero-subtitle">
            Have questions about our AI legal assistant? We're here to help you get the support you need.
          </p>
        </div>
      </section>

      <section className="section">
        <div className="container contact-grid">
          <div className="contact-info">
            <h2 className="contact-title">Contact Information</h2>
            <div className="contact-item">
              <h3>Email</h3>
              <a href="mailto:support@insaaf.ai">support@insaaf.ai</a>
              <a href="mailto:legal@insaaf.ai">legal@insaaf.ai</a>
            </div>
            <div className="contact-item">
              <h3>Phone</h3>
              <a href="tel:+918369067744">+91 8369067744</a>
              <p>Mon–Fri: 9AM–6PM IST</p>
            </div>
            <div className="contact-item">
              <h3>Address</h3>
              <p>
                NMIMS Mumbai
                <br />
                Vile Parle, Mumbai 400056
                <br />
                India
              </p>
            </div>
          </div>

          <div className="contact-form">
            <h2 className="contact-title">Send us a Message</h2>
            <form onSubmit={onSubmit}>
              <div className="form-group">
                <label htmlFor="name">Full Name</label>
                <input id="name" value={form.name} onChange={set("name")} required autoComplete="name" />
              </div>
              <div className="form-group">
                <label htmlFor="email">Email Address</label>
                <input id="email" type="email" value={form.email} onChange={set("email")} required autoComplete="email" />
              </div>
              <div className="form-group">
                <label htmlFor="subject">Subject</label>
                <input id="subject" value={form.subject} onChange={set("subject")} required />
              </div>
              <div className="form-group">
                <label htmlFor="message">Message</label>
                <textarea id="message" rows={5} value={form.message} onChange={set("message")} required />
              </div>
              <button type="submit" className="cta">Send Message</button>
              <p className="form-note">This opens your email app with the message ready to send.</p>
            </form>
          </div>
        </div>
      </section>

      <section className="section" id="faq">
        <div className="container">
          <h2 className="section-title">Frequently Asked Questions</h2>
          <div className="grid-auto-300">
            {FAQ.map(([q, a]) => (
              <div key={q} className="glass-card faq-item">
                <h3>{q}</h3>
                <p>{a}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="section cta-section">
        <div className="container">
          <h2 className="section-title" style={{ marginBottom: 20 }}>Ready to Get Started?</h2>
          <p className="section-subtitle">
            Join thousands of legal professionals who trust Insaaf for their AI-powered legal assistance.
          </p>
          <div className="cta-buttons">
            <Link className="cta" to="/#plans">View Pricing Plans</Link>
            <Link className="cta" to="/chat">Try Demo Now</Link>
          </div>
        </div>
      </section>
    </>
  );
}
