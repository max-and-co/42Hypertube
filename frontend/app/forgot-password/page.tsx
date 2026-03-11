"use client";

import { useState } from "react";
import Link from "next/link";
import "./forgot-password.css";

export default function ForgotPassword() {
  const [email, setEmail]     = useState("");
  const [error, setError]     = useState("");
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const res = await fetch("/api/auth/forgot-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      if (res.ok) {
        setSuccess(true);
      } else {
        const data = await res.json();
        setError(data.detail || "Request failed");
      }
    } catch {
      setError("An error occurred");
    }
  };

  return (
    <div className="forgot-page">
      <div className="vignette" />
      <div className="scanlines" />
      <div className="grain" />

      <div className="forgot-card f1">
        <div className="corner tl" />
        <div className="corner tr" />
        <div className="corner bl" />
        <div className="corner br" />

        <div className="forgot-header">
          <p className="eyebrow f2">✦ &nbsp; ANNO DOMINI MMXXV &nbsp; ✦</p>
          <h1 className="brand metallic flicker f2">LUMIÈRE</h1>
          <p className="subtitle f3">Pictures &amp; Entertainment</p>
          <hr className="divider f3" />
        </div>

        <p className="section-label f3">— Passphrase Recovery —</p>

        {error && <p className="error-msg">⚠ {error}</p>}

        {success ? (
          <div className="success-box f4">
            <p className="success-msg">
              If this address is registered, a recovery link has been dispatched.
            </p>
            <p className="success-sub">
              Please inspect your correspondence.
            </p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="forgot-form">
            <div className="field f4">
              <label className="field-label">Electronic Mail</label>
              <input
                type="email"
                className="field-input"
                placeholder="YOUR ADDRESS"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            <div className="f5">
              <button type="submit" className="submit-btn">
                Dispatch Recovery Link
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
