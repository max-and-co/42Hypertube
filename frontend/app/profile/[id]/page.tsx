"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import "../../settings/settings.css";
import { useLanguage } from "../../i18n/LanguageContext";
import SiteFooter from "../../components/SiteFooter";
import { fetchSession } from "../../lib/session";

interface PublicProfile {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  preferred_language: string;
  profile_picture: string | null;
}

const LANG_LABELS: Record<string, string> = { en: "English", fr: "Français", es: "Español" };

// Public profile of any member: picture and information, never the email.
export default function ProfilePage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { t } = useLanguage();
  const [profile, setProfile] = useState<PublicProfile | null>(null);
  const [isSelf, setIsSelf] = useState(false);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    const id = Number(params.id);
    if (!Number.isInteger(id) || id <= 0) {
      setNotFound(true);
      return;
    }
    fetchSession().then(async (me) => {
      if (!me) {
        router.replace("/login");
        return;
      }
      setIsSelf(me.id === id);
      const res = await fetch(`/api/users/profile/${id}`);
      if (!res.ok) {
        setNotFound(true);
        return;
      }
      setProfile(await res.json());
    });
  }, [params.id, router]);

  const handleLogout = async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    router.replace("/login");
  };

  return (
    <div className="settings-page">
      <div className="vignette" />
      <div className="scanlines" />
      <div className="grain" />
      <main className="settings-card f1">
        <div className="corner tl" />
        <div className="corner tr" />
        <div className="corner bl" />
        <div className="corner br" />
        <header className="settings-header">
          <p className="eyebrow f2">✦ &nbsp; ANNO DOMINI MMXXV &nbsp; ✦</p>
          <h1 className="brand metallic flicker f2">LUMIÈRE</h1>
          <p className="subtitle f3">Pictures &amp; Entertainment</p>
          <hr className="divider f3" />
        </header>

        <p className="section-label f3">{t("profile.section")}</p>

        {notFound && <p className="error-msg">⚠ {t("profile.not-found")}</p>}

        {profile && (
          <div className="profile-card f3">
            <div className="profile-avatar-wrap">
              {profile.profile_picture ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={profile.profile_picture} alt={profile.username} className="profile-avatar-img" />
              ) : (
                <div className="profile-avatar-placeholder">
                  <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1">
                    <circle cx="12" cy="8" r="4" />
                    <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
                  </svg>
                </div>
              )}
            </div>
            <p className="profile-fullname">{profile.first_name} {profile.last_name}</p>
            <p className="profile-username">@{profile.username}</p>
            <div className="profile-meta">
              <span className="profile-meta-label">{t("settings.language-label")}</span>
              <span className="profile-meta-value">{LANG_LABELS[profile.preferred_language] ?? profile.preferred_language}</span>
            </div>
            {isSelf && (
              <p className="profile-meta">
                <Link href="/settings" className="back-link">{t("profile.edit")}</Link>
              </p>
            )}
          </div>
        )}

        <div className="back-link-wrap f6">
          <Link href="/home" className="back-link">{t("settings.return-home")}</Link>
          <button className="logout-btn" onClick={handleLogout}>{t("logout")}</button>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
