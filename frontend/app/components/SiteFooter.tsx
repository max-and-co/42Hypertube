"use client";

import Link from "next/link";
import { useLanguage } from "../i18n/LanguageContext";

// Every page ends with this footer (subject: header, main section and footer).
export default function SiteFooter({ signedIn = true }: { signedIn?: boolean }) {
  const { t } = useLanguage();
  return (
    <footer className="app-footer">
      <div className="app-footer-inner">
        <div>
          <p className="app-footer-brand">Lumière</p>
          <p className="app-footer-tagline">{t("footer.tagline")}</p>
        </div>
        <nav className="app-footer-links" aria-label="Footer">
          {signedIn ? (
            <>
              <Link href="/home">{t("footer.library")}</Link>
              <Link href="/settings">{t("settings")}</Link>
            </>
          ) : (
            <>
              <Link href="/login">{t("footer.sign-in")}</Link>
              <Link href="/register">{t("footer.join")}</Link>
            </>
          )}
        </nav>
      </div>
      <p className="app-footer-copy">{t("home.copyright")}</p>
    </footer>
  );
}
