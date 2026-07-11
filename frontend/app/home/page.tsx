"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import "./home.css";
import { useLanguage } from "../i18n/LanguageContext";
import type { Lang } from "../i18n/translations";

type DiscoverMovie = {
  id: string;
  source: string;
  title: string;
  year: number | null;
  imdb_id?: string | null;
  imdb_rating: number | null;
  thumbnail: string | null;
  genres: string[];
  downloads: number | null;
  seeders: number | null;
  peers: number | null;
  torrent_hash?: string | null;
  watched: boolean;
  url?: string | null;
};

type DiscoverResponse = {
  query: string;
  page: number;
  limit: number;
  total: number;
  has_more: boolean;
  requested_source?: string;
  provider_used?: string;
  warning?: string;
  provider_error?: string;
  results: DiscoverMovie[];
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
  const { lang, setLang, t } = useLanguage();

  const [username, setUsername] = useState("");
  const [profilePicture, setProfilePicture] = useState<string | null>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);

  const [searchInput, setSearchInput] = useState("");
  const [activeQuery, setActiveQuery] = useState("");

  const [sortBy, setSortBy] = useState("downloads");
  const [sortDir, setSortDir] = useState("desc");
  const [sourceChoice, setSourceChoice] = useState("pdt");
  const [genre, setGenre] = useState("");
  const [yearMin, setYearMin] = useState("");
  const [yearMax, setYearMax] = useState("");
  const [imdbMin, setImdbMin] = useState("");

  const [movies, setMovies] = useState<DiscoverMovie[]>([]);
  const [isAuthReady, setIsAuthReady] = useState(false);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [isLoadingInitial, setIsLoadingInitial] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [providerUsed, setProviderUsed] = useState<string>("-");
  const [providerWarning, setProviderWarning] = useState<string | null>(null);

  const router = useRouter();
  const dropdownRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const effectiveSort = (() => {
    if (activeQuery.trim() && sortBy === "downloads") {
      return { sortBy: "title", sortDir: "asc" };
    }
    return { sortBy, sortDir };
  })();

  const fetchMovies = useCallback(
    async (targetPage: number, reset: boolean) => {
      if (reset) {
        setIsLoadingInitial(true);
      } else {
        setIsLoadingMore(true);
      }
      setSearchError(null);
      if (reset) {
        setProviderUsed("-");
        setProviderWarning(null);
      }

      const params = new URLSearchParams({
        q: activeQuery.trim(),
        page: String(targetPage),
        limit: "24",
        source: sourceChoice,
        sort_by: effectiveSort.sortBy,
        sort_dir: effectiveSort.sortDir,
      });

      if (genre.trim()) params.set("genre", genre.trim());
      if (yearMin.trim()) params.set("year_min", yearMin.trim());
      if (yearMax.trim()) params.set("year_max", yearMax.trim());
      if (imdbMin.trim()) params.set("imdb_min", imdbMin.trim());

      try {
        const res = await fetch(`/api/movies/discover?${params.toString()}`);
        if (!res.ok) {
          throw new Error(`Discover failed (${res.status})`);
        }

        const data = (await res.json()) as DiscoverResponse;
        const incoming = Array.isArray(data.results) ? data.results : [];
        const effectiveProvider = (data.provider_used || data.requested_source || sourceChoice || "-").toUpperCase();
        setProviderUsed(effectiveProvider);
        setProviderWarning(data.warning || null);

        setMovies((prev) => {
          if (reset) return incoming;
          const known = new Set(prev.map((m) => `${m.source}:${m.id}`));
          const merged = [...prev];
          for (const movie of incoming) {
            const key = `${movie.source}:${movie.id}`;
            if (!known.has(key)) {
              known.add(key);
              merged.push(movie);
            }
          }
          return merged;
        });

        setPage(targetPage);
        setHasMore(Boolean(data.has_more));
      } catch (error) {
        const message = error instanceof Error ? error.message : "Unknown error";
        setSearchError(message);
        setProviderWarning(null);
        if (reset) {
          setMovies([]);
          setHasMore(false);
          setProviderUsed("-");
        }
      } finally {
        if (reset) {
          setIsLoadingInitial(false);
        } else {
          setIsLoadingMore(false);
        }
      }
    },
    [activeQuery, effectiveSort.sortBy, effectiveSort.sortDir, sourceChoice, genre, yearMin, yearMax, imdbMin]
  );

  useEffect(() => {
    fetch("/api/users/me").then(async (res) => {
      if (!res.ok) {
        router.replace("/login");
        return;
      }
      const data = await res.json();
      setUsername(data.username);
      setProfilePicture(data.profile_picture ?? null);
      if (data.preferred_language === "fr" || data.preferred_language === "en" || data.preferred_language === "es") {
        setLang(data.preferred_language as Lang);
      }
      setIsAuthReady(true);
    });
  }, [router, setLang]);

  useEffect(() => {
    if (!isAuthReady) return;
    fetchMovies(1, true);
  }, [isAuthReady, fetchMovies]);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const first = entries[0];
        if (!first.isIntersecting) return;
        if (!hasMore || isLoadingInitial || isLoadingMore) return;
        fetchMovies(page + 1, false);
      },
      { rootMargin: "250px 0px" }
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [page, hasMore, isLoadingInitial, isLoadingMore, fetchMovies]);

  const handleLogout = async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    router.replace("/login");
  };

  const handleSearch = () => {
    setActiveQuery(searchInput.trim());
  };

  const handleClearFilters = () => {
    setSourceChoice("pdt");
    setGenre("");
    setYearMin("");
    setYearMax("");
    setImdbMin("");
    setSortBy("downloads");
    setSortDir("desc");
  };

  const handleToggleWatched = async (movie: DiscoverMovie) => {
    const key = `${movie.source}:${movie.id}`;
    setMovies((prev) => prev.map((m) => (`${m.source}:${m.id}` === key ? { ...m, watched: !m.watched } : m)));

    try {
      const res = await fetch(`/api/movies/${encodeURIComponent(movie.id)}/watched-toggle?source=${encodeURIComponent(movie.source)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ watched: !movie.watched }),
      });
      if (!res.ok) {
        throw new Error(`Watch toggle failed (${res.status})`);
      }
    } catch {
      setMovies((prev) => prev.map((m) => (`${m.source}:${m.id}` === key ? { ...m, watched: movie.watched } : m)));
    }
  };

  const openWatchPage = (movie: DiscoverMovie) => {
    const params = new URLSearchParams();
    params.set("title", movie.title);
    if (movie.year !== null) params.set("year", String(movie.year));
    if (movie.imdb_rating !== null) params.set("imdb_rating", String(movie.imdb_rating));
    if (movie.imdb_id) params.set("imdb_id", movie.imdb_id);
    if (movie.thumbnail) {
      params.set("thumbnail", movie.thumbnail);
      params.set("cover_image", movie.thumbnail);
    }
    if (movie.genres?.length) params.set("genres", movie.genres.join(","));
    if (movie.torrent_hash) params.set("torrent_hash", movie.torrent_hash);

    router.push(`/watch/${encodeURIComponent(movie.source)}/${encodeURIComponent(movie.id)}?${params.toString()}`);
  };

  const heroMovie = movies.find((movie) => Boolean(movie.thumbnail)) ?? movies[0] ?? null;

  return (
    <div className="home-page">
      <div className="vignette" />
      <div className="scanlines" />
      <div className="grain" />

      <header className="site-header f1">
        <div className="header-brand">
          <span className="metallic flicker">LUMIERE</span>
        </div>

        <div className="header-search">
          <input
            className="search-input"
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSearch();
            }}
            placeholder={t("home.search-placeholder")}
          />
          <button className="search-btn" aria-label="Search" onClick={handleSearch}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.35-4.35" />
            </svg>
          </button>
        </div>

        <div className="header-right">
          <button className="header-logout-btn" onClick={handleLogout}>{t("logout")}</button>
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
                  {t("settings")}
                </a>

                <div className="lang-item">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#555" strokeWidth="1.5" style={{ flexShrink: 0 }}>
                    <circle cx="12" cy="12" r="10" />
                    <path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
                  </svg>
                  <span className="lang-label">{t("lang")}</span>
                  <select className="lang-select" value={lang} onChange={(e) => setLang(e.target.value as Lang)}>
                    <option value="en">English</option>
                    <option value="fr">Français</option>
                    <option value="es">Español</option>
                  </select>
                </div>
              </div>
            )}
          </div>
        </div>
      </header>

      <section className="hero f2">
        <div className="hero-bg">
          {heroMovie?.thumbnail ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={heroMovie.thumbnail} alt={heroMovie.title} className="hero-bg-image" />
          ) : null}
          <div className="hero-bg-pattern" />
        </div>
        <div className="hero-overlay" />
        <div className="hero-content">
          <p className="hero-eyebrow">{t("home.featured")}</p>
          <h1 className="hero-title metallic">{heroMovie?.title ?? t("home.popular-title")}</h1>
          <p className="hero-meta">
            {heroMovie?.year ?? "N/A"}
            {heroMovie?.imdb_rating ? `  ·  IMDb ${heroMovie.imdb_rating.toFixed(1)}` : ""}
          </p>
          <p className="hero-desc">
            {activeQuery.trim()
              ? `${t("home.search-results")} — "${activeQuery}"`
              : t("home.no-search-desc")}
          </p>
          <div className="hero-actions">
            <button
              className="hero-btn"
              onClick={() => {
                if (heroMovie) {
                  openWatchPage(heroMovie);
                }
              }}
            >
              {t("home.watch-now")}
            </button>
            <button className="hero-btn hero-btn-secondary" onClick={() => fetchMovies(1, true)}>
              {t("home.refresh")}
            </button>
          </div>
        </div>
      </section>

      <main className="home-main">
        <section className="filters-panel f3">
          <div className="filters-grid">
            <label className="filter-field">
              <span>{t("home.sort")}</span>
              <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
                <option value="downloads">{t("home.sort-popularity")}</option>
                <option value="title">{t("home.sort-name")}</option>
                <option value="imdb_rating">{t("home.sort-imdb")}</option>
                <option value="year">{t("home.sort-year")}</option>
                <option value="seeders">{t("home.sort-seeders")}</option>
                <option value="peers">{t("home.sort-peers")}</option>
              </select>
            </label>
            <label className="filter-field">
              <span>{t("home.direction")}</span>
              <select value={sortDir} onChange={(e) => setSortDir(e.target.value)}>
                <option value="desc">{t("home.desc")}</option>
                <option value="asc">{t("home.asc")}</option>
              </select>
            </label>
            <label className="filter-field">
              <span>Source</span>
              <select value={sourceChoice} onChange={(e) => setSourceChoice(e.target.value)}>
                <option value="pdt">Public Domain Torrents</option>
                <option value="archive">Archive.org</option>
              </select>
            </label>
            <label className="filter-field">
              <span>{t("home.genre")}</span>
              <input value={genre} onChange={(e) => setGenre(e.target.value)} placeholder="Drama" />
            </label>
            <label className="filter-field">
              <span>{t("home.year-min")}</span>
              <input value={yearMin} onChange={(e) => setYearMin(e.target.value)} inputMode="numeric" placeholder="1990" />
            </label>
            <label className="filter-field">
              <span>{t("home.year-max")}</span>
              <input value={yearMax} onChange={(e) => setYearMax(e.target.value)} inputMode="numeric" placeholder="2026" />
            </label>
            <label className="filter-field">
              <span>{t("home.imdb-min")}</span>
              <input value={imdbMin} onChange={(e) => setImdbMin(e.target.value)} inputMode="decimal" placeholder="7.5" />
            </label>
          </div>
          <div className="filters-actions">
            <button className="row-more" onClick={() => setActiveQuery(searchInput.trim())}>{t("home.apply")}</button>
            <button className="row-more" onClick={handleClearFilters}>{t("home.reset-filters")}</button>
          </div>
        </section>

        {isLoadingInitial && <p className="search-status">{t("home.loading")}</p>}
        {searchError && <p className="search-status search-status-error">{searchError}</p>}
        {!isLoadingInitial && !searchError && movies.length === 0 && (
          <p className="search-status">{t("home.no-results")}</p>
        )}

        <section className="movie-grid-section">
          <div className="grid-heading">
            <h2>{activeQuery.trim() ? t("home.search-results") : t("home.popular-now")}</h2>
            <p>
              {t("home.sort-label")} {effectiveSort.sortBy} ({effectiveSort.sortDir})
            </p>
          </div>

          <p className="provider-banner">Provider used: {providerUsed}</p>
          {providerWarning ? <p className="provider-banner provider-banner-warning">{providerWarning}</p> : null}

          <div className="movie-grid">
            {movies.map((movie, i) => (
              <article key={`${movie.source}:${movie.id}`} className={`movie-card ${movie.watched ? "movie-card-watched" : "movie-card-unwatched"}`}>
                <button
                  type="button"
                  className="movie-poster"
                  onClick={() => {
                    openWatchPage(movie);
                  }}
                >
                  {movie.thumbnail ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={movie.thumbnail} alt={movie.title} className="movie-poster-image" loading="lazy" />
                  ) : (
                    <div className="movie-poster-inner" style={{ background: POSTER_GRADIENTS[i % POSTER_GRADIENTS.length] }}>
                      <p className="movie-poster-year">{movie.year ?? "N/A"}</p>
                      <p className="movie-poster-num">{String(i + 1).padStart(2, "0")}</p>
                    </div>
                  )}
                  <span className={`watched-badge ${movie.watched ? "is-watched" : "is-unwatched"}`}>
                    {movie.watched ? t("home.watched") : t("home.unwatched")}
                  </span>
                </button>
                <p className="movie-title">{movie.title}</p>
                <p className="movie-info">
                  {movie.year ?? "N/A"} · IMDb {movie.imdb_rating?.toFixed(1) ?? "N/A"} · {movie.source.toUpperCase()}
                </p>
                <div className="card-actions">
                  <button className="row-more" onClick={() => handleToggleWatched(movie)}>
                    {movie.watched ? t("home.mark-unwatched") : t("home.mark-watched")}
                  </button>
                </div>
              </article>
            ))}
          </div>

          <div ref={sentinelRef} className="scroll-sentinel" />
          {isLoadingMore && <p className="search-status">{t("home.loading-more")}</p>}
        </section>
      </main>

      <footer className="site-footer f5">
        <div className="footer-top">
          <div>
            <p className="footer-brand metallic">LUMIERE</p>
            <p className="footer-tagline">Pictures &amp; Entertainment</p>
          </div>
          <div className="footer-links">
            <div>
              <p className="footer-col-title">{t("home.discover")}</p>
              <div className="footer-col-links">
                <a href="#" className="footer-link">{t("home.browse-all")}</a>
                <a href="#" className="footer-link">{t("home.new-releases")}</a>
                <a href="#" className="footer-link">{t("home.classics")}</a>
              </div>
            </div>
            <div>
              <p className="footer-col-title">{t("home.account")}</p>
              <div className="footer-col-links">
                <a href="/settings" className="footer-link">{t("settings")}</a>
                <a href="#" className="footer-link">{t("home.watch-history")}</a>
                <a href="#" className="footer-link">{t("home.favourites")}</a>
              </div>
            </div>
            <div>
              <p className="footer-col-title">{t("home.legal")}</p>
              <div className="footer-col-links">
                <a href="#" className="footer-link">{t("home.privacy")}</a>
                <a href="#" className="footer-link">{t("home.terms")}</a>
                <a href="#" className="footer-link">{t("home.contact")}</a>
              </div>
            </div>
          </div>
        </div>
        <div className="footer-bottom">
          <p className="footer-copy">{t("home.copyright")}</p>
          <p className="footer-ornament">Pictures &amp; Entertainment</p>
        </div>
      </footer>
    </div>
  );
}
