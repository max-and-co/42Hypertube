"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import "./settings/settings.css";
import { useLanguage } from "./i18n/LanguageContext";
import { getSessionUser } from "./lib/api";
import SiteHeader from "./components/SiteHeader";
import SiteFooter from "./components/SiteFooter";

// Unknown URLs get the site's own page (header, main, footer, translated)
// instead of Next's bare default. The HTTP status stays 404.
export default function NotFound() {
  const { t } = useLanguage();
  const [signedIn, setSignedIn] = useState(false);

  useEffect(() => {
    getSessionUser().then((user) => setSignedIn(Boolean(user)));
  }, []);

  return (
    <div className="page-shell">
      <SiteHeader signedIn={signedIn} />
      <main className="settings-page">
        <div className="settings-card f1">
          <p className="section-label">404</p>
          <p className="search-empty">{t("notfound.text")}</p>
          <div className="back-link-wrap">
            <Link href={signedIn ? "/home" : "/login"} className="back-link">
              {signedIn ? t("settings.return-home") : t("notfound.to-login")}
            </Link>
          </div>
        </div>
      </main>
      <SiteFooter signedIn={signedIn} />
    </div>
  );
}
