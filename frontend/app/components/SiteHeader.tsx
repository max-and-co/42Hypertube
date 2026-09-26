"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useLanguage } from "../i18n/LanguageContext";
import { logout } from "../lib/api";

// Header for pages without their own masthead (auth pages, settings).
// Signed in, it carries the one-click logout the subject asks for on every page.
export default function SiteHeader({ signedIn = false }: { signedIn?: boolean }) {
  const { t } = useLanguage();
  const router = useRouter();

  const handleLogout = async () => {
    await logout();
    router.replace("/login");
  };

  return (
    <header className="app-header">
      <Link href={signedIn ? "/home" : "/login"} className="app-header-brand">
        Lumière
      </Link>
      <nav className="app-header-nav" aria-label="Main">
        {signedIn ? (
          <>
            <Link href="/home">{t("footer.library")}</Link>
            <Link href="/settings">{t("settings")}</Link>
            <button type="button" onClick={handleLogout}>{t("logout")}</button>
          </>
        ) : (
          <>
            <Link href="/login">{t("footer.sign-in")}</Link>
            <Link href="/register">{t("footer.join")}</Link>
          </>
        )}
      </nav>
    </header>
  );
}
