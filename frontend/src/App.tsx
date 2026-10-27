import { useCallback, useEffect, useRef, useState } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import Footer from "./components/Footer";
import Header from "./components/Header";
import AboutPage from "./pages/AboutPage";
import CasePage from "./pages/CasePage";
import ChatPage from "./pages/ChatPage";
import ContactPage from "./pages/ContactPage";
import HomePage from "./pages/HomePage";
import SearchPage from "./pages/SearchPage";

const TITLES: Record<string, string> = {
  "/": "Insaaf — Justice. Simplified with AI.",
  "/about": "About — Insaaf",
  "/contact": "Contact — Insaaf",
  "/chat": "Ask Insaaf — AI legal research",
  "/search": "Case Search — Insaaf",
};

/** Scroll to #anchors after navigation, or to top on a new page. */
function useScrollManagement() {
  const { pathname, hash } = useLocation();
  useEffect(() => {
    document.title = TITLES[pathname] ?? "Insaaf";
    if (hash) {
      const t = window.setTimeout(() => document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: "smooth" }), 60);
      return () => window.clearTimeout(t);
    }
    window.scrollTo({ top: 0 });
  }, [pathname, hash]);
}

export default function App() {
  const { pathname } = useLocation();
  const [toast, setToast] = useState<string | null>(null);
  const timer = useRef<number>();
  useScrollManagement();

  const notify = useCallback((msg: string) => {
    setToast(msg);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setToast(null), 3500);
  }, []);

  const isChat = pathname === "/chat";

  return (
    <>
      <Header notify={notify} />
      <main>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="/contact" element={<ContactPage notify={notify} />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/cases/:id" element={<CasePage />} />
          <Route
            path="*"
            element={
              <section className="hero hero--compact">
                <div className="container">
                  <h1 className="hero-title">Page not found.</h1>
                  <p className="hero-subtitle">The page you were looking for doesn't exist.</p>
                </div>
              </section>
            }
          />
        </Routes>
      </main>
      {!isChat && <Footer />}
      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}
    </>
  );
}
