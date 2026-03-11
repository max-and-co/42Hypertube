"use client";

import { useState, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import "./reset-password.css";

function ResetPasswordForm() {
  const [password, setPassword]   = useState("");
  const [confirm, setConfirm]     = useState("");
  const [error, setError]         = useState("");
  const [success, setSuccess]     = useState(false);
  const [token, setToken]         = useState("");
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const t = searchParams.get("token");
    if (!t) {
      setError("Invalid reset link. Please request a new one.");
    } else {
      setToken(t);
    }
  }, [searchParams]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (password !== confirm) {
      setError("Passphrases do not match");
      return;
    }
    if (password.length < 8) {
      setError("Passphrase must be at least 8 characters");
      return;
    }

    try {
      const res = await fetch("/api/auth/reset-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, new_password: password }),
      });
      if (res.ok) {
        setSuccess(true);
        setTimeout(() => router.push("/login"), 3000);
      } else {
        const data = await res.json();
        setError(data.detail || "Reset failed");
      }
    } catch {
      setError("An error occurred");
    }
  };

  return (
    <div className="reset-page">
      <div className="vignette" />
      <div className="scanlines" />
      <div className="grain" />

      <div className="reset-card f1">
        <div className="corner tl" />
        <div className="corner tr" />
        <div className="corner bl" />
        <div className="corner br" />

        <div className="reset-header">
          <p className="eyebrow f2">✦ &nbsp; ANNO DOMINI MMXXV &nbsp; ✦</p>
          <h1 className="brand metallic flicker f2">LUMIÈRE</h1>
          <p className="subtitle f3">Pictures &amp; Entertainment</p>
          <hr className="divider f3" />
        </div>

        <p className="section-label f3">— Set New Passphrase —</p>

        {error && <p className="error-msg">⚠ {error}</p>}

        {success ? (
          <div className="success-box f4">
            <p className="success-msg">
              Your passphrase has been changed.
            </p>
            <p className="success-sub">
              Redirecting to the entrance…
            </p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="reset-form">
            <div className="field f4">
              <label className="field-label">New Passphrase</label>
              <input
                type="password"
                className="field-input"
                placeholder="· · · · · · · ·"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={!token}
              />
            </div>

            <div className="field f5">
              <label className="field-label">Confirm Passphrase</label>
              <input
                type="password"
                className="field-input"
                placeholder="· · · · · · · ·"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
                disabled={!token}
              />
            </div>

            <div className="f6">
              <button type="submit" className="submit-btn" disabled={!token}>
                Confirm New Passphrase
              </button>
            </div>
          </form>
        )}

        <hr className="divider footer-divider" />

        <p className="back-text f6">
          <Link href="/login" className="back-link">
            ← Return to Entrance
          </Link>
        </p>
      </div>
    </div>
  );
}

export default function ResetPassword() {
  return (
    <Suspense>
      <ResetPasswordForm />
    </Suspense>
  );
}
