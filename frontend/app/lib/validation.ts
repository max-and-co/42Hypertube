// Same rules as user-service/schemas.py, checked here for instant feedback.
// The server re-checks everything; these only save a round trip.

export const USERNAME_RE = /^[A-Za-z0-9_.-]{3,30}$/;
const NAME_RE = /^\p{L}+(?:[ '\-]\p{L}+)*$/u;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
export const MAX_COMMENT_LENGTH = 1000;

export function usernameError(value: string): string | null {
  return USERNAME_RE.test(value.trim()) ? null : "Username must be 3-30 characters: letters, digits, '.', '_' or '-'";
}

export function nameError(value: string): string | null {
  const v = value.trim().replace(/\s+/g, " ");
  return v.length >= 1 && v.length <= 50 && NAME_RE.test(v) ? null : "Names must be 1-50 letters (spaces, ' and - allowed)";
}

export function emailError(value: string): string | null {
  return value.length <= 254 && EMAIL_RE.test(value.trim()) ? null : "Please enter a valid e-mail address";
}

export function passwordError(value: string): string | null {
  if (value.length < 8 || value.length > 128) return "Password must be 8-128 characters";
  if (!/\p{L}/u.test(value) || !/\d/.test(value)) return "Password must contain at least one letter and one digit";
  return null;
}

export function commentError(value: string): string | null {
  const v = value.trim();
  if (!v) return "Comment cannot be empty";
  if (v.length > MAX_COMMENT_LENGTH) return `Comment must be at most ${MAX_COMMENT_LENGTH} characters`;
  return null;
}

export function firstError(...errors: (string | null)[]): string | null {
  return errors.find((e) => e !== null) ?? null;
}
