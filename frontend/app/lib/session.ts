export interface SessionUser {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  preferred_language: string;
  profile_picture: string | null;
}

// Uses /api/auth/session (always 200) instead of /api/users/me so that a
// logged-out visitor doesn't trigger a 401 error in the browser console.
export async function fetchSession(): Promise<SessionUser | null> {
  try {
    const res = await fetch("/api/auth/session", { cache: "no-store" });
    if (!res.ok) return null;
    const data = await res.json();
    return data.authenticated ? (data.user as SessionUser) : null;
  } catch {
    return null;
  }
}

// Persist the UI language as the user's preferred language (best effort).
export async function savePreferredLanguage(lang: string): Promise<boolean> {
  try {
    const res = await fetch("/api/users/me", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ preferred_language: lang }),
    });
    return res.ok;
  } catch {
    return false;
  }
}
