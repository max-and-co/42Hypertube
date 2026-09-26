"use client";

import { useState, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import "./reset-password.css";
import { useLanguage } from "../i18n/LanguageContext";
import { sendForm } from "../lib/api";
import { passwordError } from "../lib/validation";
import SiteHeader from "../components/SiteHeader";
import SiteFooter from "../components/SiteFooter";

function ResetPasswordForm() {
  const [password, setPassword]   = useState("");
  const [confirm, setConfirm]     = useState("");
  const [error, setError]         = useState("");
  const [success, setSuccess]     = useState(false);
  const [token, setToken]         = useState("");
  const router = useRouter();
  const searchParams = useSearchParams();
  const { t } = useLanguage();

  useEffect(() => {
    const tk = searchParams.get("token");
    if (!tk) {
      setError(t("reset.invalid"));
    } else {
      setToken(tk);
    }
  }, [searchParams, t]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (password !== confirm) {
      setError(t("reset.mismatch"));
      return;
    }
    const invalid = passwordError(password);
    if (invalid) {
      setError(invalid);
      return;
    }

    const result = await sendForm("/api/auth/reset-password", { token, new_password: password });
    if (result.ok) {
      setSuccess(true);
      setTimeout(() => router.push("/login"), 3000);
    } else {
      setError(result.detail || t("reset.failed"));
    }
  };

  return (
    <div className="page-shell">
      <SiteHeader />
      <main className="reset-page">

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

        <p className="section-label f3">{t("reset.section")}</p>

        {error && <p className="error-msg">⚠ {error}</p>}

        {success ? (
          <div className="success-box f4">
            <p className="success-msg">
              {t("reset.success")}
            </p>
            <p className="success-sub">
              {t("reset.success-sub")}
            </p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="reset-form" noValidate>
            <div className="field f4">
              <label className="field-label">{t("reset.new")}</label>
              <input
                type="password"
                className="field-input"
                placeholder="· · · · · · · ·"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                maxLength={128}
                required
                disabled={!token}
              />
            </div>

            <div className="field f5">
              <label className="field-label">{t("reset.confirm")}</label>
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
                {t("reset.submit")}
              </button>
            </div>
          </form>
        )}

        <hr className="divider footer-divider" />

        <p className="back-text f6">
          <Link href="/login" className="back-link">
            {t("reset.return")}
          </Link>
        </p>
      </div>
      </main>
      <SiteFooter signedIn={false} />
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
