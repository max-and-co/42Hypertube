"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import "./register.css";
import { useLanguage } from "../i18n/LanguageContext";
import type { Lang } from "../i18n/translations";
import { getSessionUser, sendForm } from "../lib/api";
import { emailError, firstError, nameError, passwordError, usernameError } from "../lib/validation";
import SiteHeader from "../components/SiteHeader";
import SiteFooter from "../components/SiteFooter";

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
  const [submitting, setSubmitting] = useState(false);
  const router = useRouter();
  const { t, setLang } = useLanguage();

  useEffect(() => {
    getSessionUser().then((user) => {
      if (user) router.replace("/home");
    });
  }, [router]);

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    const invalid = firstError(
      nameError(firstName),
      nameError(lastName),
      usernameError(username),
      emailError(email),
      passwordError(password),
      password === confirm ? null : t("register.mismatch"),
    );
    if (invalid) {
      setError(invalid);
      return;
    }

    setSubmitting(true);
    const result = await sendForm("/api/auth/register", {
      email: email.trim(),
      username: username.trim(),
      first_name: firstName.trim(),
      last_name: lastName.trim(),
      password,
      preferred_language: language,
    });
    setSubmitting(false);

    if (result.ok) {
      router.push("/login");
    } else {
      setError(result.detail || t("register.failed"));
    }
  };

  return (
    <div className="page-shell">
      <SiteHeader />
      <main className="register-page">
        <div className="register-card f1">
          <div className="register-header">
            <p className="eyebrow f2">✦ &nbsp; ANNO DOMINI MMXXV &nbsp; ✦</p>
            <h1 className="brand metallic flicker f2">LUMIÈRE</h1>
            <p className="subtitle f3">Pictures &amp; Entertainment</p>
            <hr className="divider f3" />
          </div>

          <p className="section-label f3">{t("register.section")}</p>

          {error && <p className="error-msg" role="alert">⚠ {error}</p>}

          <form onSubmit={handleRegister} className="register-form" noValidate>
            <div className="field-row f3">
              <div className="field">
                <label className="field-label" htmlFor="reg-first">{t("register.first-name")}</label>
                <input id="reg-first" type="text" className="field-input" placeholder={t("register.first-placeholder")}
                  value={firstName} onChange={(e) => setFirstName(e.target.value)} maxLength={50} autoComplete="given-name" required />
              </div>
              <div className="field">
                <label className="field-label" htmlFor="reg-last">{t("register.last-name")}</label>
                <input id="reg-last" type="text" className="field-input" placeholder={t("register.last-placeholder")}
                  value={lastName} onChange={(e) => setLastName(e.target.value)} maxLength={50} autoComplete="family-name" required />
              </div>
            </div>

            <div className="field f4">
              <label className="field-label" htmlFor="reg-username">{t("register.username")}</label>
              <input id="reg-username" type="text" className="field-input" placeholder={t("register.username-placeholder")}
                value={username} onChange={(e) => setUsername(e.target.value)} maxLength={30} autoComplete="username" required />
              <p className="field-hint">{t("register.username-hint")}</p>
            </div>

            <div className="field f4">
              <label className="field-label" htmlFor="reg-email">{t("register.email")}</label>
              <input id="reg-email" type="email" className="field-input" placeholder={t("register.email-placeholder")}
                value={email} onChange={(e) => setEmail(e.target.value)} maxLength={254} autoComplete="email" required />
            </div>

            <div className="field f5">
              <label className="field-label" htmlFor="reg-password">{t("register.password")}</label>
              <input id="reg-password" type="password" className="field-input" placeholder="· · · · · · · ·"
                value={password} onChange={(e) => setPassword(e.target.value)} maxLength={128} autoComplete="new-password" required />
              <p className="field-hint">{t("register.password-hint")}</p>
            </div>

            <div className="field f5">
              <label className="field-label" htmlFor="reg-confirm">{t("register.confirm")}</label>
              <input id="reg-confirm" type="password" className="field-input" placeholder="· · · · · · · ·"
                value={confirm} onChange={(e) => setConfirm(e.target.value)} maxLength={128} autoComplete="new-password" required />
            </div>

            <div className="field f5">
              <label className="field-label" htmlFor="reg-lang">{t("register.lang")}</label>
              <select
                id="reg-lang"
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
              <button type="submit" className="submit-btn" disabled={submitting}>
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
      </main>
      <SiteFooter signedIn={false} />
    </div>
  );
}
