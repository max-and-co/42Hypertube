"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import "../../settings/settings.css";
import { useLanguage } from "../../i18n/LanguageContext";
import { getSessionUser, avatarUrl } from "../../lib/api";
import SiteHeader from "../../components/SiteHeader";
import SiteFooter from "../../components/SiteFooter";

type PublicProfile = {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  preferred_language: string;
  profile_picture: string | null;
};

const LANG_LABELS: Record<string, string> = { en: "English", fr: "Français", es: "Español" };

// Any member's public profile (subject III.1). The e-mail is never shown.
export default function UserProfilePage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { t } = useLanguage();
  const [profile, setProfile] = useState<PublicProfile | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    const id = Number(params.id);
    if (!Number.isInteger(id) || id <= 0) {
      setMissing(true);
      return;
    }
    getSessionUser().then(async (user) => {
      if (!user) {
        router.replace("/login");
        return;
      }
      const res = await fetch(`/api/users/profile/${id}`);
      if (res.ok) setProfile(await res.json());
      else setMissing(true);
    });
  }, [params.id, router]);

  return (
    <div className="page-shell">
      <SiteHeader signedIn />
      <main className="settings-page">
        <div className="settings-card f1">
          <p className="section-label">{t("profile.title")}</p>
          {missing && <p className="search-empty">{t("profile.not-found")}</p>}
          {profile && (
            <div className="profile-card">
              <div className="profile-avatar-wrap">
                {profile.profile_picture ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={avatarUrl(profile.profile_picture)} alt={profile.username} className="profile-avatar-img" />
                ) : (
                  <div className="profile-avatar-placeholder" />
                )}
              </div>
              <p className="profile-fullname">{profile.first_name} {profile.last_name}</p>
              <p className="profile-username">@{profile.username}</p>
              <div className="profile-meta">
                <span className="profile-meta-label">{t("settings.language-label")}</span>
                <span className="profile-meta-value">{LANG_LABELS[profile.preferred_language] ?? profile.preferred_language}</span>
              </div>
            </div>
          )}
          <div className="back-link-wrap">
            <Link href="/home" className="back-link">{t("settings.return-home")}</Link>
          </div>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
