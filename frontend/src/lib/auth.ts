/**
 * Google sign-in, as in the v1 site (script.js): Google Identity Services
 * token client → userinfo → stored in localStorage under "user".
 * The OAuth client must list this site's origin as an authorised JS origin.
 */

export interface GoogleUser {
  name: string;
  email: string;
  picture: string;
}

const CLIENT_ID =
  import.meta.env.VITE_GOOGLE_CLIENT_ID ??
  "425189354801-8o8bbo69lj9m0b5mh5lvrq4hip19783k.apps.googleusercontent.com";
const STORAGE_KEY = "user";
export const AUTH_EVENT = "insaaf:auth";

interface TokenResponse {
  access_token?: string;
  error?: string;
}

interface GoogleAccounts {
  oauth2: {
    initTokenClient(config: {
      client_id: string;
      scope: string;
      callback: (r: TokenResponse) => void;
      error_callback?: (e: { type: string }) => void;
    }): { requestAccessToken(): void };
  };
}

declare global {
  interface Window {
    google?: { accounts: GoogleAccounts };
  }
}

let gsiPromise: Promise<void> | null = null;

function loadGsi(): Promise<void> {
  if (window.google?.accounts) return Promise.resolve();
  gsiPromise ??= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => {
      gsiPromise = null;
      reject(new Error("Could not load Google sign-in"));
    };
    document.head.appendChild(s);
  });
  return gsiPromise;
}

export function currentUser(): GoogleUser | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as GoogleUser) : null;
  } catch {
    return null;
  }
}

function setUser(user: GoogleUser | null) {
  try {
    if (user) localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage unavailable — keep the session in memory only */
  }
  window.dispatchEvent(new CustomEvent(AUTH_EVENT, { detail: user }));
}

export async function signInWithGoogle(): Promise<GoogleUser> {
  await loadGsi();
  return new Promise((resolve, reject) => {
    const client = window.google!.accounts.oauth2.initTokenClient({
      client_id: CLIENT_ID,
      scope: "email profile",
      callback: async (resp) => {
        if (!resp.access_token) return reject(new Error(resp.error ?? "Sign-in was cancelled"));
        try {
          const r = await fetch("https://www.googleapis.com/oauth2/v2/userinfo", {
            headers: { Authorization: `Bearer ${resp.access_token}` },
          });
          if (!r.ok) throw new Error("Could not load your Google profile");
          const data = (await r.json()) as GoogleUser;
          const user = { name: data.name, email: data.email, picture: data.picture };
          setUser(user);
          resolve(user);
        } catch (e) {
          reject(e as Error);
        }
      },
      error_callback: (e) => reject(new Error(e.type === "popup_closed" ? "Sign-in was cancelled" : "Google sign-in failed")),
    });
    client.requestAccessToken();
  });
}

export function signOut() {
  setUser(null);
}
