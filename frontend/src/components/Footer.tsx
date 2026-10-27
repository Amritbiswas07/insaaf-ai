import { Link } from "react-router-dom";

export default function Footer() {
  return (
    <footer className="footer">
      <div className="footer-inner">
        <div className="divider" />
        <div className="footer-grid">
          <div className="footer-col">
            <span className="title">Product</span>
            <Link to="/#plans">Pricing</Link>
            <Link to="/chat">Ask Insaaf</Link>
            <Link to="/search">Case Search</Link>
            <Link to="/#plans">Team plans</Link>
          </div>
          <div className="footer-col">
            <span className="title">About us</span>
            <Link to="/about">About</Link>
            <Link to="/about#team">Team</Link>
            <Link to="/about#story">Our story</Link>
            <Link to="/contact">Partnerships</Link>
            <Link to="/contact">Careers</Link>
          </div>
          <div className="footer-col">
            <span className="title">Help and support</span>
            <Link to="/contact#faq">Help center</Link>
            <Link to="/contact">Contact us</Link>
            <Link to="/contact#faq">Privacy &amp; Terms</Link>
            <Link to="/contact#faq">Safety information</Link>
          </div>
          <div className="footer-col">
            <span className="title">Community</span>
            <Link to="/contact">Agencies</Link>
            <Link to="/contact">Freelancers</Link>
            <Link to="/contact">Engineers</Link>
            <div className="store-row">
              <img src="/assets/app-store-badge.svg" alt="Download on the App Store" />
              <img src="/assets/google-play-badge.svg" alt="Get it on Google Play" />
            </div>
          </div>
        </div>
        <div className="divider" />
        <div className="footer-bottom">
          <div className="legal">@insaaf copyright {new Date().getFullYear()}</div>
          <div className="footer-links">
            <Link to="/contact#faq">Help</Link>
            <Link to="/contact#faq">Privacy</Link>
            <Link to="/contact#faq">Terms</Link>
          </div>
          <div className="social-lang">
            <div className="social">
              <img src="/assets/icon-facebook.svg" alt="Facebook" />
              <img src="/assets/icon-twitter.svg" alt="Twitter" />
              <img src="/assets/icon-instagram.svg" alt="Instagram" />
            </div>
            <div className="lang">English (India)</div>
          </div>
        </div>
      </div>
    </footer>
  );
}
