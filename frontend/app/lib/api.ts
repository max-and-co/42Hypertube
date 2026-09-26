// Small fetch helpers shared by every page.
//
// The subject forbids any error in the browser console, and Chrome prints every
// 4xx/5xx fetch in red. So the app never "probes" with a request that may fail:
// login state comes from /api/auth/session (always 200), and form endpoints
// answer 200 with { ok: false, detail } for expected refusals such as a wrong
// password. The public REST API keeps real status codes.

export type SessionUser = {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  preferred_language: string;
  profile_picture: string | null;
};

export async function getSessionUser(): Promise<SessionUser | null> {
  try {
    const res = await fetch("/api/auth/session", { cache: "no-store" });
    if (!res.ok) return null;
    const data = (await res.json()) as { authenticated: boolean; user: SessionUser | null };
    return data.authenticated ? data.user : null;
  } catch {
    return null;
  }
}

export type FormResult<T = Record<string, unknown>> = ({ ok: true } & T) | { ok: false; detail: string };

export async function sendForm<T = Record<string, unknown>>(
  url: string,
  body: unknown,
  method: "POST" | "PATCH" = "POST",
): Promise<FormResult<T>> {
  try {
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok && data.ok !== false) return { ok: true, ...(data as T) };
    return { ok: false, detail: typeof data.detail === "string" ? data.detail : "Request failed" };
  } catch {
    return { ok: false, detail: "Network error" };
  }
}

export async function logout(): Promise<void> {
  try {
    await fetch("/api/auth/logout", { method: "POST" });
  } catch {
    // Leaving for the login page anyway.
  }
}

// Profile pictures are our own uploads or, set through the API, any https URL.
// Remote ones go through the same-origin image proxy, which answers a blank
// pixel instead of an error when the image is gone.
export function avatarUrl(raw: string | null | undefined): string | undefined {
  if (!raw) return undefined;
  if (raw.startsWith("/api/users/avatars/")) return raw;
  if (/^https:\/\//i.test(raw)) return `/api/movies/thumbnail?url=${encodeURIComponent(raw)}`;
  return undefined;
}
