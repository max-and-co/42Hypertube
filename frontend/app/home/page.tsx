"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import "./home.css";

const LANGUAGES = [
  { value: "en", label: "English" },
  { value: "fr", label: "Français" },
  { value: "es", label: "Español" },
];

type MovieResult = {
  id: string;
  identifier: string;
  title: string;
  year: string;
  creator?: string | null;
  description?: string | null;
  thumbnail?: string | null;
  archive_url?: string | null;
};

const POSTER_GRADIENTS = [
  "linear-gradient(160deg, #0d0d0d 0%, #111 50%, #0a0a0a 100%)",
  "linear-gradient(160deg, #0a0a10 0%, #0d0d15 50%, #080810 100%)",
  "linear-gradient(160deg, #100a0a 0%, #150d0d 50%, #0a0808 100%)",
  "linear-gradient(160deg, #0a100a 0%, #0d150d 50%, #08100a 100%)",
  "linear-gradient(160deg, #0d0d0d 0%, #161616 50%, #0a0a0a 100%)",
  "linear-gradient(160deg, #100d0a 0%, #151208 50%, #0a0d08 100%)",
  "linear-gradient(160deg, #0a0a0d 0%, #0d0d12 50%, #08080f 100%)",
];

export default function Home() {
  const [username, setUsername] = useState("");
  const [profilePicture, setProfilePicture] = useState<string | null>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [language, setLanguage] = useState("en");
  const [searchQuery, setSearchQuery] = useState("classic cinema");
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [movies, setMovies] = useState<MovieResult[]>([]);
  const router = useRouter();
  const dropdownRef = useRef<HTMLDivElement>(null);

  const runSearch = async (query: string) => {
    const normalized = query.trim();
    setIsSearching(true);
    setSearchError(null);
    try {
      const params = new URLSearchParams({ q: normalized, limit: "24" });
      const res = await fetch(`/api/torrent/search?${params.toString()}`);
      if (!res.ok) {
        throw new Error(`Search failed (${res.status})`);
      }
      const data = await res.json();
      setMovies(Array.isArray(data.results) ? data.results : []);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown error";
      setSearchError(message);
      setMovies([]);
    } finally {
      setIsSearching(false);
    }
  };

  useEffect(() => {
    fetch("/api/users/me").then(async (res) => {
      if (!res.ok) {
        router.replace("/login");
      } else {
        const data = await res.json();
        setUsername(data.username);
        setProfilePicture(data.profile_picture ?? null);
        runSearch("classic cinema");
      }
    });
  }, [router]);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleLogout = async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    router.replace("/login");
  };

  const handleSearch = () => {
    runSearch(searchQuery);
  };

  const heroMovie = movies[0];
  const rows = [
    { title: "Top Results", movies: movies.slice(0, 8) },
    { title: "More to Explore", movies: movies.slice(8, 16) },
    { title: "From the Archive", movies: movies.slice(16, 24) },
  ].filter((row) => row.movies.length > 0);

  return (
    <div className="home-page">
      <div className="vignette" />
      <div className="scanlines" />
      <div className="grain" />

      {/* ── Header ── */}
      <header className="site-header f1">
        <div className="header-brand">
          <span className="metallic flicker">LUMIÈRE</span>
        </div>

        <div className="header-search">
          <input
            className="search-input"
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSearch();
            }}
            placeholder="Search titles, directors, genres…"
          />
          <button className="search-btn" aria-label="Search" onClick={handleSearch}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.35-4.35" />
            </svg>
          </button>
        </div>

        <div className="header-user" ref={dropdownRef}>
          <button
            className={`user-btn${profilePicture ? " user-btn-avatar" : ""}`}
            onClick={() => setDropdownOpen((v) => !v)}
            aria-label="User menu"
          >
            {profilePicture ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={profilePicture} alt="avatar" className="header-avatar" />
            ) : (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <circle cx="12" cy="8" r="4" />
                <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
              </svg>
            )}
          </button>

          {dropdownOpen && (
            <div className="user-dropdown">
              {username && (
                <div className="dropdown-item" style={{ cursor: "default", pointerEvents: "none", color: "#444" }}>
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <circle cx="12" cy="8" r="4" />
                    <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
                  </svg>
                  {username}
                </div>
              )}

              <a href="/settings" className="dropdown-item" onClick={() => setDropdownOpen(false)}>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <circle cx="12" cy="12" r="3" />
                  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
                </svg>
                Settings
              </a>

              <div className="lang-item">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#555" strokeWidth="1.5" style={{ flexShrink: 0 }}>
                  <circle cx="12" cy="12" r="10" />
                  <path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
                </svg>
                <span className="lang-label">Lang</span>
                <select
                  className="lang-select"
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                >
                  {LANGUAGES.map((l) => (
                    <option key={l.value} value={l.value}>{l.label}</option>
                  ))}
                </select>
              </div>

              <button className="dropdown-item dropdown-logout" onClick={handleLogout}>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                  <polyline points="16 17 21 12 16 7" />
                  <line x1="21" y1="12" x2="9" y2="12" />
                </svg>
                Logout
              </button>
            </div>
          )}
        </div>
      </header>

      {/* ── Hero ── */}
      <section className="hero f2">
        <div className="hero-bg">
          <div className="hero-bg-pattern" />
        </div>
        <div className="hero-overlay" />
        <div className="hero-content">
          <p className="hero-eyebrow">✦ &nbsp; Featured Presentation &nbsp; ✦</p>
          <h1 className="hero-title metallic">{heroMovie?.title ?? "Archive Search"}</h1>
          <p className="hero-meta">
            {heroMovie?.year ?? "N/A"}
            {heroMovie?.creator ? `  ·  ${heroMovie.creator}` : ""}
          </p>
          <p className="hero-desc">
            {heroMovie?.description ?? "Search public-domain movies from archive.org and explore cinema history."}
          </p>
          <div className="hero-actions">
            <button
              className="hero-btn"
              onClick={() => {
                if (heroMovie?.archive_url) window.open(heroMovie.archive_url, "_blank", "noopener,noreferrer");
              }}
            >
              Open on Archive.org
            </button>
            <button className="hero-btn hero-btn-secondary" onClick={handleSearch}>Refresh Results</button>
          </div>
        </div>
      </section>

      {/* ── Movie rows ── */}
      <main className="home-main">
        {isSearching && <p className="search-status">Searching archive.org...</p>}
        {searchError && <p className="search-status search-status-error">{searchError}</p>}
        {!isSearching && !searchError && rows.length === 0 && (
          <p className="search-status">No results found for this query.</p>
        )}

        {rows.map((row, rowIdx) => (
          <section key={row.title} className="movie-row f3" style={{ animationDelay: `${0.4 + rowIdx * 0.1}s` }}>
            <div className="row-header">
              <h2 className="row-title">{row.title}</h2>
              <div className="row-divider" />
              <button className="row-more">View All</button>
            </div>
            <div className="row-scroll">
              {row.movies.map((movie, i) => (
                <a
                  key={movie.id}
                  className="movie-card"
                  href={movie.archive_url ?? "#"}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <div className="movie-poster">
                    {movie.thumbnail ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={movie.thumbnail} alt={movie.title} className="movie-poster-image" loading="lazy" />
                    ) : (
                      <div
                        className="movie-poster-inner"
                        style={{ background: POSTER_GRADIENTS[i % POSTER_GRADIENTS.length] }}
                      >
                        <p className="movie-poster-year">{movie.year}</p>
                        <p className="movie-poster-num">{String(i + 1).padStart(2, "0")}</p>
                      </div>
                    )}
                  </div>
                  <p className="movie-title">{movie.title}</p>
                  <p className="movie-info">{movie.creator ?? "Archive.org"} · {movie.year}</p>
                </a>
              ))}
            </div>
          </section>
        ))}
      </main>

      {/* ── Footer ── */}
      <footer className="site-footer f5">
        <div className="footer-top">
          <div>
            <p className="footer-brand metallic">LUMIÈRE</p>
            <p className="footer-tagline">Pictures &amp; Entertainment</p>
          </div>
          <div className="footer-links">
            <div>
              <p className="footer-col-title">Discover</p>
              <div className="footer-col-links">
                <a href="#" className="footer-link">Browse All</a>
                <a href="#" className="footer-link">New Releases</a>
                <a href="#" className="footer-link">Classics</a>
              </div>
            </div>
            <div>
              <p className="footer-col-title">Account</p>
              <div className="footer-col-links">
                <a href="/settings" className="footer-link">Settings</a>
                <a href="#" className="footer-link">Watch History</a>
                <a href="#" className="footer-link">Favourites</a>
              </div>
            </div>
            <div>
              <p className="footer-col-title">Legal</p>
              <div className="footer-col-links">
                <a href="#" className="footer-link">Privacy</a>
                <a href="#" className="footer-link">Terms</a>
                <a href="#" className="footer-link">Contact</a>
              </div>
            </div>
          </div>
        </div>
        <div className="footer-bottom">
          <p className="footer-copy">© MMXXV Lumière — All Rights Reserved</p>
          <p className="footer-ornament">✦ &nbsp; Pictures &amp; Entertainment &nbsp; ✦</p>
        </div>
      </footer>
    </div>
  );
}
