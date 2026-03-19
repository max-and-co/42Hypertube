"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import "./register.css";
import { useLanguage } from "../i18n/LanguageContext";
import type { Lang } from "../i18n/translations";

const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "fr", label: "Français" },
  { code: "es", label: "Español" },
];

export default function Register() {
  const [firstName, setFirstName]   = useState("");
  const [lastName, setLastName]     = useState("");
  const [username, setUsername]     = useState("");
  const [email, setEmail]           = useState("");
  const [password, setPassword]     = useState("");
  const [confirm, setConfirm]       = useState("");
  const [language, setLanguage]     = useState("en");
  const [error, setError]           = useState("");
  const router = useRouter();
  const { t, setLang } = useLanguage();

  useEffect(() => {
    fetch("/api/users/me").then((res) => {
      if (res.ok) router.replace("/home");
    });
  }, [router]);

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (password !== confirm) {
      setError(t("register.mismatch"));
      return;
    }
    if (password.length < 8) {
      setError(t("register.too-short"));
      return;
    }

    try {
      const res = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          username,
          first_name: firstName,
          last_name: lastName,
          password,
          preferred_language: language,
        }),
      });

      if (res.ok) {
        router.push("/login");
      } else {
        const data = await res.json();
        setError(data.detail || t("register.failed"));
      }
    } catch {
      setError(t("error.generic"));
    }
  };

  return (
    <div className="register-page">
      <div className="vignette" />
      <div className="scanlines" />
      <div className="grain" />

      <div className="register-card f1">
        <div className="corner tl" />
        <div className="corner tr" />
        <div className="corner bl" />
        <div className="corner br" />

        <div className="register-header">
          <p className="eyebrow f2">✦ &nbsp; ANNO DOMINI MMXXV &nbsp; ✦</p>
          <h1 className="brand metallic flicker f2">LUMIÈRE</h1>
          <p className="subtitle f3">Pictures &amp; Entertainment</p>
          <hr className="divider f3" />
        </div>

        <p className="section-label f3">{t("register.section")}</p>

        {error && <p className="error-msg">⚠ {error}</p>}

        <form onSubmit={handleRegister} className="register-form">
          <div className="field-row f3">
            <div className="field">
              <label className="field-label">{t("register.first-name")}</label>
              <input
                type="text"
                className="field-input"
                placeholder={t("register.first-placeholder")}
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                required
              />
            </div>
            <div className="field">
              <label className="field-label">{t("register.last-name")}</label>
              <input
                type="text"
                className="field-input"
                placeholder={t("register.last-placeholder")}
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                required
              />
            </div>
          </div>

          <div className="field f4">
            <label className="field-label">{t("register.username")}</label>
            <input
              type="text"
              className="field-input"
              placeholder={t("register.username-placeholder")}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>

          <div className="field f4">
            <label className="field-label">{t("register.email")}</label>
            <input
              type="email"
              className="field-input"
              placeholder={t("register.email-placeholder")}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          <div className="field f5">
            <label className="field-label">{t("register.password")}</label>
            <input
              type="password"
              className="field-input"
              placeholder="· · · · · · · ·"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <div className="field f5">
            <label className="field-label">{t("register.confirm")}</label>
            <input
              type="password"
              className="field-input"
              placeholder="· · · · · · · ·"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
            />
          </div>

          <div className="field f5">
            <label className="field-label">{t("register.lang")}</label>
            <select
              className="field-input field-select"
              value={language}
              onChange={(e) => {
                setLanguage(e.target.value);
                setLang(e.target.value as Lang);
              }}
            >
              {LANGUAGES.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.label}
                </option>
              ))}
            </select>
          </div>

          <div className="f6">
            <button type="submit" className="submit-btn">
              {t("register.submit")}
            </button>
          </div>
        </form>

        <hr className="divider footer-divider" />

        <p className="login-text f6">
          {t("register.already")}{" "}
          <Link href="/login" className="login-link">
            {t("register.signin")}
          </Link>
        </p>
      </div>
    </div>
  );
}
