import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { AUTH_EVENT, currentUser, signInWithGoogle, signOut, type GoogleUser } from "../lib/auth";

const MENU = [
  { to: "/", label: "Home" },
  { to: "/about", label: "About Us" },
  { to: "/#plans", label: "Plans & Pricing" },
  { to: "/chat", label: "Try Demo" },
  { to: "/search", label: "Case Search" },
  { to: "/contact", label: "Contact Us" },
];

export default function Header({ notify }: { notify: (msg: string) => void }) {
  const [open, setOpen] = useState(false);
  const [user, setUser] = useState<GoogleUser | null>(currentUser);
  const ref = useRef<HTMLElement>(null);
  const location = useLocation();

  useEffect(() => setOpen(false), [location.pathname, location.hash]);

  useEffect(() => {
    const onAuth = (e: Event) => setUser((e as CustomEvent<GoogleUser | null>).detail);
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener(AUTH_EVENT, onAuth);
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener(AUTH_EVENT, onAuth);
      document.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  async function login() {
    try {
      const u = await signInWithGoogle();
      notify(`Welcome, ${u.name}! You're signed in to Insaaf.`);
    } catch (e) {
      notify((e as Error).message);
    }
  }

  return (
    <header className="header" ref={ref}>
      <div className="header-inner">
        <button
          className="nav-toggle"
          aria-label="Navigation menu"
          aria-expanded={open}
          aria-controls="dropdown-menu"
          onClick={() => setOpen((o) => !o)}
        >
          ☰
        </button>
        <Link to="/" className="brand" aria-label="Insaaf home">
          <img src="/assets/insaaf_logo.png" alt="Insaaf" className="brand-logo" />
        </Link>

        <div className="header-spacer" />

        <nav className="header-links" aria-label="Quick links">
          <NavLink to="/chat">Ask AI</NavLink>
          <NavLink to="/search">Case Search</NavLink>
        </nav>

        <div className="auth-buttons">
          {user ? (
            <div className="user-info">
              <img src={user.picture} alt={user.name} title={user.name} className="user-avatar" referrerPolicy="no-referrer" />
              <button className="btn--logout" onClick={() => { signOut(); notify("You've been logged out."); }}>
                Logout
              </button>
            </div>
          ) : (
            <>
              <button className="btn btn--ghost" onClick={login}>Log in</button>
              <button className="btn btn--outline" onClick={login}>Sign up</button>
            </>
          )}
        </div>
      </div>

      <nav id="dropdown-menu" className={`dropdown-menu ${open ? "show" : ""}`} aria-label="Main">
        {MENU.map((m) => (
          <Link
            key={m.to}
            to={m.to}
            className={location.pathname + location.hash === m.to ? "active" : undefined}
          >
            {m.label}
          </Link>
        ))}
      </nav>
    </header>
  );
}
