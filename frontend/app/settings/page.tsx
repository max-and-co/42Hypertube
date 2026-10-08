"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import "./settings.css";
import { useLanguage } from "../i18n/LanguageContext";
import type { Lang } from "../i18n/translations";
import { getSessionUser, sendForm, avatarUrl } from "../lib/api";
import { localize } from "../lib/messages";
import { emailError, firstError, nameError, usernameError } from "../lib/validation";
import SiteHeader from "../components/SiteHeader";
import SiteFooter from "../components/SiteFooter";

const MAX_AVATAR_BYTES = 2 * 1024 * 1024;
const AVATAR_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];

const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "fr", label: "Français" },
  { code: "es", label: "Español" },
];

const LANG_LABELS: Record<string, string> = { en: "English", fr: "Français", es: "Español" };

interface UserData {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  preferred_language: string;
  profile_picture: string | null;
}

interface SearchResult {
  id: number;
  username: string;
  profile_picture: string | null;
}

interface PublicProfile {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  preferred_language: string;
  profile_picture: string | null;
}

export default function Settings() {
  const { setLang, t } = useLanguage();
  const [user, setUser] = useState<UserData | null>(null);

  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [language, setLanguage] = useState("en");

  const [profileError, setProfileError] = useState("");
  const [profileSuccess, setProfileSuccess] = useState("");
  const [avatarError, setAvatarError] = useState("");
  const [saving, setSaving] = useState(false);

  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [selectedProfile, setSelectedProfile] = useState<PublicProfile | null>(null);
  const [loadingProfile, setLoadingProfile] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const searchTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const router = useRouter();

  useEffect(() => {
    getSessionUser().then((data) => {
      if (!data) { router.replace("/login"); return; }
      setUser(data);
      setFirstName(data.first_name);
      setLastName(data.last_name);
      setUsername(data.username);
      setEmail(data.email);
      const preferred = ["en", "fr", "es"].includes(data.preferred_language) ? data.preferred_language : "en";
      setLanguage(preferred);
      setLang(preferred as Lang);
    });
  }, [router, setLang]);

  const handleProfileSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setProfileError("");
    setProfileSuccess("");
    const invalid = firstError(nameError(firstName), nameError(lastName), usernameError(username), emailError(email));
    if (invalid) {
      setProfileError(invalid);
      return;
    }
    setSaving(true);
    const result = await sendForm<{ user: UserData }>(
      "/api/users/me",
      {
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        username: username.trim(),
        email: email.trim(),
        preferred_language: language,
      },
      "PATCH",
    );
    setSaving(false);
    if (result.ok) {
      setUser(result.user);
      setProfileSuccess(t("settings.saved"));
      setLang(language as Lang);
    } else {
      setProfileError(result.detail || t("settings.update-failed"));
    }
  };

  const handleAvatarChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setAvatarError("");
    // Checked before sending: nginx refuses bodies over 2 MB with a 413, which
    // would show as an error in the console. The server re-checks the bytes.
    if (!AVATAR_TYPES.includes(file.type)) {
      setAvatarError(t("settings.avatar-type"));
      return;
    }
    if (file.size > MAX_AVATAR_BYTES) {
      setAvatarError(t("settings.avatar-too-big"));
      return;
    }
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch("/api/users/me/avatar", { method: "POST", body: formData });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.ok !== false) {
        setUser((prev) => prev ? { ...prev, profile_picture: data.profile_picture } : prev);
      } else {
        setAvatarError(data.detail || t("settings.upload-failed"));
      }
    } catch {
      setAvatarError(t("settings.upload-error"));
    }
  };

  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const q = e.target.value;
    setSearchQuery(q);
    setSelectedProfile(null);
    if (searchTimeout.current) clearTimeout(searchTimeout.current);
    if (q.trim().length < 2 || q.length > 30) { setSearchResults([]); return; }
    setSearching(true);
    searchTimeout.current = setTimeout(async () => {
      try {
        const res = await fetch(`/api/users/search?q=${encodeURIComponent(q.trim())}`);
        if (res.ok) setSearchResults(await res.json());
      } finally {
        setSearching(false);
      }
    }, 300);
  };

  const handleSelectUser = async (id: number) => {
    setLoadingProfile(true);
    setSelectedProfile(null);
    try {
      const res = await fetch(`/api/users/profile/${id}`);
      const data = res.ok ? await res.json() : null;
      if (data && data.ok !== false) setSelectedProfile(data);
    } finally {
      setLoadingProfile(false);
    }
  };

  const handleCloseProfile = () => {
    setSelectedProfile(null);
  };

  if (!user) return null;

  return (
    <div className="page-shell">
    <SiteHeader signedIn />
    <main className="settings-page">

      <div className="settings-card f1">
        <div className="corner tl" />
        <div className="corner tr" />
        <div className="corner bl" />
        <div className="corner br" />

        {/* Header */}
        <div className="settings-header">
          <p className="eyebrow f2">✦ &nbsp; ANNO DOMINI MMXXV &nbsp; ✦</p>
          <h1 className="brand metallic flicker f2">LUMIÈRE</h1>
          <p className="subtitle f3">Pictures &amp; Entertainment</p>
          <hr className="divider f3" />
        </div>

        <p className="section-label f3">{t("settings.section")}</p>

        {/* Avatar */}
        <div className="avatar-section f3">
          <div className="avatar-wrap">
            {user.profile_picture ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={avatarUrl(user.profile_picture)} alt="Portrait" className="avatar-img" />
            ) : (
              <div className="avatar-placeholder">
                <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1">
                  <circle cx="12" cy="8" r="4" />
                  <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
                </svg>
              </div>
            )}
          </div>
          <button className="avatar-upload-btn" onClick={() => fileInputRef.current?.click()} type="button">
            {t("settings.change-portrait")}
          </button>
          <input ref={fileInputRef} type="file" accept="image/png,image/jpeg,image/gif,image/webp" style={{ display: "none" }} onChange={handleAvatarChange} />
          {avatarError && <p className="error-msg" style={{ marginTop: "12px", marginBottom: 0 }}>⚠ {localize(avatarError, t)}</p>}
        </div>

        <hr className="section-divider" />

        {/* Profile form */}
        <p className="section-label f4">{t("settings.personal")}</p>

        {profileError && <p className="error-msg">⚠ {localize(profileError, t)}</p>}
        {profileSuccess && <p className="success-msg">✓ {profileSuccess}</p>}

        <form onSubmit={handleProfileSave} className="settings-form f4" noValidate>
          <div className="field-row">
            <div className="field">
              <label className="field-label">{t("settings.first-name")}</label>
              <input type="text" className="field-input" placeholder={t("settings.first-placeholder")} value={firstName} onChange={(e) => setFirstName(e.target.value)} maxLength={50} required />
            </div>
            <div className="field">
              <label className="field-label">{t("settings.last-name")}</label>
              <input type="text" className="field-input" placeholder={t("settings.last-placeholder")} value={lastName} onChange={(e) => setLastName(e.target.value)} maxLength={50} required />
            </div>
          </div>
          <div className="field">
            <label className="field-label">{t("settings.username")}</label>
            <input type="text" className="field-input" placeholder={t("settings.username-placeholder")} value={username} onChange={(e) => setUsername(e.target.value)} maxLength={30} required />
          </div>
          <div className="field">
            <label className="field-label">{t("settings.email")}</label>
            <input type="email" className="field-input" placeholder={t("settings.email-placeholder")} value={email} onChange={(e) => setEmail(e.target.value)} maxLength={254} required />
          </div>
          <div className="field">
            <label className="field-label">{t("settings.lang")}</label>
            <select className="field-input field-select" value={language} onChange={(e) => setLanguage(e.target.value)}>
              {LANGUAGES.map((l) => (
                <option key={l.code} value={l.code}>{l.label}</option>
              ))}
            </select>
          </div>
          <div className="f5">
            <button type="submit" className="submit-btn" disabled={saving}>
              {saving ? t("settings.saving") : t("settings.save")}
            </button>
          </div>
        </form>

        <hr className="section-divider" />

        {/* Member search */}
        <p className="section-label f5">{t("settings.find-member")}</p>

        <div className="search-section f5">
          <div className="search-wrap">
            <svg className="search-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.35-4.35" />
            </svg>
            <input
              type="text"
              className="search-input"
              placeholder={t("settings.search-placeholder")}
              value={searchQuery}
              onChange={handleSearchChange}
              maxLength={30}
              autoComplete="off"
            />
            {(searching || loadingProfile) && <span className="search-spinner" />}
          </div>

          {/* Inline profile view */}
          {selectedProfile && (
            <div className="profile-card">
              <button className="profile-close" onClick={handleCloseProfile} aria-label="Close">✕</button>
              <div className="profile-avatar-wrap">
                {selectedProfile.profile_picture ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={avatarUrl(selectedProfile.profile_picture)} alt={selectedProfile.username} className="profile-avatar-img" />
                ) : (
                  <div className="profile-avatar-placeholder">
                    <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1">
                      <circle cx="12" cy="8" r="4" />
                      <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
                    </svg>
                  </div>
                )}
              </div>
              <p className="profile-fullname">{selectedProfile.first_name} {selectedProfile.last_name}</p>
              <p className="profile-username">@{selectedProfile.username}</p>
              <div className="profile-meta">
                <span className="profile-meta-label">{t("settings.language-label")}</span>
                <span className="profile-meta-value">{LANG_LABELS[selectedProfile.preferred_language] ?? selectedProfile.preferred_language}</span>
              </div>
              <Link href={`/users/${selectedProfile.id}`} className="back-link">{t("settings.open-profile")}</Link>
            </div>
          )}

          {/* Search results list (hidden while a profile is shown) */}
          {!selectedProfile && searchResults.length > 0 && (
            <ul className="search-results">
              {searchResults.map((r) => (
                <li key={r.id} className="search-result-item" onClick={() => handleSelectUser(r.id)}>
                  <div className="result-avatar">
                    {r.profile_picture ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={avatarUrl(r.profile_picture)} alt={r.username} className="result-avatar-img" />
                    ) : (
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                        <circle cx="12" cy="8" r="4" />
                        <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
                      </svg>
                    )}
                  </div>
                  <span className="result-username">{r.username}</span>
                  <svg className="result-chevron" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="m9 18 6-6-6-6" />
                  </svg>
                </li>
              ))}
            </ul>
          )}

          {!selectedProfile && searchQuery.length >= 2 && !searching && searchResults.length === 0 && (
            <p className="search-empty">{t("settings.no-members")}</p>
          )}
        </div>

        <div className="back-link-wrap f6">
          <Link href="/home" className="back-link">{t("settings.return-home")}</Link>
        </div>
      </div>
    </main>
    <SiteFooter />
    </div>
  );
}
