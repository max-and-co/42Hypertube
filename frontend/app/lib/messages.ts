// Validation (lib/validation.ts) and the API word their refusals in English.
// Every message they can produce maps to a translation key here, so a form
// error is shown in the user's language like the rest of the page.

const KNOWN: Record<string, string> = {
  "Username must be 3-30 characters: letters, digits, '.', '_' or '-'": "err.username",
  "Names must be 1-50 letters (spaces, ' and - allowed)": "err.name",
  "Please enter a valid e-mail address": "err.email",
  "Password must be 8-128 characters": "err.password-length",
  "Password must contain at least one letter and one digit": "err.password-mix",
  "Comment cannot be empty": "err.comment-empty",
  "Comment must be at most 1000 characters": "err.comment-long",
  "Email already registered": "err.email-taken",
  "Email already in use": "err.email-taken",
  "Username already taken": "err.username-taken",
  "Incorrect credentials": "err.credentials",
  "Invalid or expired token": "err.token",
  "Reset token has expired": "err.token",
  "Too many attempts. Please wait a minute and try again.": "err.rate-limited",
  "File must be a PNG, JPEG, GIF or WebP image": "settings.avatar-type",
  "Image must be 2 MB or smaller": "settings.avatar-too-big",
  "Uploaded file is empty": "settings.avatar-type",
  "Current password is incorrect": "err.current-password",
  "This video could not be found at its source": "watch.not-found",
  "Request failed": "error.generic",
  "Network error": "err.network",
};

export function localize(message: string, t: (key: string) => string): string {
  // Server validation errors are prefixed with the field: "username: ...".
  const bare = message.replace(/^[a-z_]+: /, "");
  const key = KNOWN[bare];
  if (key) return t(key);
  if (bare.startsWith("value is not a valid email address")) return t("err.email");
  return message;
}
