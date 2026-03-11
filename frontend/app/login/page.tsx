"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import "./login.css";

export default function Login() {
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword]     = useState("");
  const [error, setError]           = useState("");
  const router = useRouter();

  useEffect(() => {
    // If already authenticated, skip to home
    fetch("/api/users/me").then((res) => {
      if (res.ok) router.replace("/home");
    });
    // Check for OAuth error param
    const params = new URLSearchParams(window.location.search);
    if (params.get("error") === "oauth_failed") {
      setError("OAuth authentication failed. Please try again.");
    }
  }, [router]);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identifier, password }),
      });
      if (res.ok) {
        router.push("/home");
      } else {
        const data = await res.json();
        setError(data.detail || "Login failed");
      }
    } catch {
      setError("An error occurred");
    }
  };

  return (
    <div className="login-page">
      <div className="vignette" />
      <div className="scanlines" />
      <div className="grain" />

      <div className="login-card f1">
        <div className="corner tl" />
        <div className="corner tr" />
        <div className="corner bl" />
        <div className="corner br" />

        <div className="login-header">
          <p className="eyebrow f2">✦ &nbsp; ANNO DOMINI MMXXV &nbsp; ✦</p>
          <h1 className="brand metallic flicker f2">LUMIÈRE</h1>
          <p className="subtitle f3">Pictures &amp; Entertainment</p>
          <hr className="divider f3" />
        </div>

        <p className="section-label f3">— Member Entrance —</p>

        {error && <p className="error-msg">⚠ {error}</p>}

        <form onSubmit={handleLogin} className="login-form">
          <div className="field f4">
            <label className="field-label">Username or Email</label>
            <input
              type="text"
              className="field-input"
              placeholder="YOUR HANDLE OR ADDRESS"
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              required
            />
          </div>

          <div className="field f5">
            <label className="field-label">Secret Passphrase</label>
            <input
              type="password"
              className="field-input"
              placeholder="· · · · · · · ·"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <div className="forgot-row f5">
            <Link href="/forgot-password" className="forgot-link">
              Forgot passphrase?
            </Link>
          </div>

          <div className="f6">
            <button type="submit" className="submit-btn">
              Enter the Theatre
            </button>
          </div>
        </form>

        <hr className="divider oauth-divider f6" />

        <p className="oauth-label f6">— Or enter via —</p>

        <div className="oauth-buttons f6">
          <a href="/api/oauth/42/login" className="oauth-btn">
            42 Network
          </a>
          <a href="/api/oauth/github/login" className="oauth-btn">
            GitHub
          </a>
        </div>

        <hr className="divider footer-divider" />

        <p className="register-text f6">
          No Membership?{" "}
          <Link href="/register" className="register-link">
            Enrol Here
          </Link>
        </p>
      </div>
    </div>
  );
}
