"use client";

import { useState } from "react";
import Link from "next/link";
import "./forgot-password.css";
import { useLanguage } from "../i18n/LanguageContext";
import { sendForm } from "../lib/api";
import { emailError } from "../lib/validation";
import SiteHeader from "../components/SiteHeader";
import SiteFooter from "../components/SiteFooter";

export default function ForgotPassword() {
  const [email, setEmail]     = useState("");
  const [error, setError]     = useState("");
  const [success, setSuccess] = useState(false);
  const { t } = useLanguage();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    const invalid = emailError(email);
    if (invalid) {
      setError(invalid);
      return;
    }
    const result = await sendForm("/api/auth/forgot-password", { email: email.trim() });
    if (result.ok) {
      setSuccess(true);
    } else {
      setError(result.detail || t("forgot.failed"));
    }
  };

  return (
    <div className="page-shell">
      <SiteHeader />
      <main className="forgot-page">

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

        <p className="section-label f3">{t("forgot.section")}</p>

        {error && <p className="error-msg">⚠ {error}</p>}

        {success ? (
          <div className="success-box f4">
            <p className="success-msg">
              {t("forgot.success")}
            </p>
            <p className="success-sub">
              {t("forgot.success-sub")}
            </p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="forgot-form" noValidate>
            <div className="field f4">
              <label className="field-label">{t("forgot.email")}</label>
              <input
                type="email"
                className="field-input"
                placeholder={t("forgot.email-placeholder")}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                maxLength={254}
                required
              />
            </div>

            <div className="f5">
              <button type="submit" className="submit-btn">
                {t("forgot.submit")}
              </button>
            </div>
          </form>
        )}

        <hr className="divider footer-divider" />

        <p className="back-text f6">
          <Link href="/login" className="back-link">
            {t("forgot.return")}
          </Link>
        </p>
      </div>
      </main>
      <SiteFooter signedIn={false} />
    </div>
  );
}
