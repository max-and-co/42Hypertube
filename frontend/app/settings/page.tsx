"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import "./settings.css";

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

  const handleLogout = async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    router.replace("/login");
  };

  useEffect(() => {
    fetch("/api/users/me").then(async (res) => {
      if (!res.ok) { router.replace("/login"); return; }
      const data: UserData = await res.json();
      setUser(data);
      setFirstName(data.first_name);
      setLastName(data.last_name);
      setUsername(data.username);
      setEmail(data.email);
      setLanguage(data.preferred_language);
    });
  }, [router]);

  const handleProfileSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setProfileError("");
    setProfileSuccess("");
    setSaving(true);
    try {
      const res = await fetch("/api/users/me", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ first_name: firstName, last_name: lastName, username, email, preferred_language: language }),
      });
      if (res.ok) {
        const updated: UserData = await res.json();
        setUser(updated);
        setProfileSuccess("Profile updated successfully");
      } else {
        const data = await res.json();
        setProfileError(data.detail || "Update failed");
      }
    } catch {
      setProfileError("An error occurred");
    } finally {
      setSaving(false);
    }
  };

  const handleAvatarChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setAvatarError("");
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch("/api/users/me/avatar", { method: "POST", body: formData });
      if (res.ok) {
        const data = await res.json();
        setUser((prev) => prev ? { ...prev, profile_picture: data.profile_picture } : prev);
      } else {
        const data = await res.json();
        setAvatarError(data.detail || "Upload failed");
      }
    } catch {
      setAvatarError("An error occurred during upload");
    }
  };

  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const q = e.target.value;
    setSearchQuery(q);
    setSelectedProfile(null);
    if (searchTimeout.current) clearTimeout(searchTimeout.current);
    if (q.length < 2) { setSearchResults([]); return; }
    setSearching(true);
    searchTimeout.current = setTimeout(async () => {
      try {
        const res = await fetch(`/api/users/search?q=${encodeURIComponent(q)}`);
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
      if (res.ok) setSelectedProfile(await res.json());
    } finally {
      setLoadingProfile(false);
    }
  };

  const handleCloseProfile = () => {
    setSelectedProfile(null);
  };

  if (!user) return null;

  return (
    <div className="settings-page">
      <div className="vignette" />
      <div className="scanlines" />
      <div className="grain" />

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

        <p className="section-label f3">— Member Settings —</p>

        {/* Avatar */}
        <div className="avatar-section f3">
          <div className="avatar-wrap">
            {user.profile_picture ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={user.profile_picture} alt="Portrait" className="avatar-img" />
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
            Change Portrait
          </button>
          <input ref={fileInputRef} type="file" accept="image/*" style={{ display: "none" }} onChange={handleAvatarChange} />
          {avatarError && <p className="error-msg" style={{ marginTop: "12px", marginBottom: 0 }}>⚠ {avatarError}</p>}
        </div>

        <hr className="section-divider" />

        {/* Profile form */}
        <p className="section-label f4">— Personal Information —</p>

        {profileError && <p className="error-msg">⚠ {profileError}</p>}
        {profileSuccess && <p className="success-msg">✓ {profileSuccess}</p>}

        <form onSubmit={handleProfileSave} className="settings-form f4">
          <div className="field-row">
            <div className="field">
              <label className="field-label">First Name</label>
              <input type="text" className="field-input" placeholder="FIRST" value={firstName} onChange={(e) => setFirstName(e.target.value)} required />
            </div>
            <div className="field">
              <label className="field-label">Last Name</label>
              <input type="text" className="field-input" placeholder="LAST" value={lastName} onChange={(e) => setLastName(e.target.value)} required />
            </div>
          </div>
          <div className="field">
            <label className="field-label">Username</label>
            <input type="text" className="field-input" placeholder="YOUR HANDLE" value={username} onChange={(e) => setUsername(e.target.value)} required />
          </div>
          <div className="field">
            <label className="field-label">Electronic Mail</label>
            <input type="email" className="field-input" placeholder="YOUR ADDRESS" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div className="field">
            <label className="field-label">Preferred Language</label>
            <select className="field-input field-select" value={language} onChange={(e) => setLanguage(e.target.value)}>
              {LANGUAGES.map((l) => (
                <option key={l.code} value={l.code}>{l.label}</option>
              ))}
            </select>
          </div>
          <div className="f5">
            <button type="submit" className="submit-btn" disabled={saving}>
              {saving ? "Saving…" : "Save Changes"}
            </button>
          </div>
        </form>

        <hr className="section-divider" />

        {/* Member search */}
        <p className="section-label f5">— Find a Member —</p>

        <div className="search-section f5">
          <div className="search-wrap">
            <svg className="search-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.35-4.35" />
            </svg>
            <input
              type="text"
              className="search-input"
              placeholder="SEARCH BY USERNAME"
              value={searchQuery}
              onChange={handleSearchChange}
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
                  <img src={selectedProfile.profile_picture} alt={selectedProfile.username} className="profile-avatar-img" />
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
                <span className="profile-meta-label">Language</span>
                <span className="profile-meta-value">{LANG_LABELS[selectedProfile.preferred_language] ?? selectedProfile.preferred_language}</span>
              </div>
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
                      <img src={r.profile_picture} alt={r.username} className="result-avatar-img" />
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
            <p className="search-empty">No members found</p>
          )}
        </div>

        <div className="back-link-wrap f6">
          <Link href="/home" className="back-link">← Return to Home</Link>
          <button className="logout-btn" onClick={handleLogout}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <polyline points="16 17 21 12 16 7" />
              <line x1="21" y1="12" x2="9" y2="12" />
            </svg>
            Logout
          </button>
        </div>
      </div>
    </div>
  );
}
