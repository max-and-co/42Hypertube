"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import "./home.css";
import { useLanguage } from "../i18n/LanguageContext";
import type { Lang } from "../i18n/translations";
import { getSessionUser, logout, sendForm, avatarUrl } from "../lib/api";
import SiteFooter from "../components/SiteFooter";

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
  watched: boolean;
};

type DiscoverResponse = {
  page: number;
  has_more: boolean;
  sources?: string[];
  warning?: string | null;
  results: DiscoverMovie[];
};

type Filters = {
  query: string;
  source: string;
  sortBy: string;
  sortDir: string;
  genre: string;
  yearMin: string;
  yearMax: string;
  imdbMin: string;
};

const DEFAULT_FILTERS: Filters = {
  query: "",
  source: "all",
  sortBy: "downloads",
  sortDir: "desc",
  genre: "",
  yearMin: "",
  yearMax: "",
  imdbMin: "",
};

const POSTER_GRADIENTS = [
  "linear-gradient(160deg, #444444 0%, #474747 50%, #424242 100%)",
  "linear-gradient(160deg, #434343 0%, #3f3f4f 50%, #39394d 100%)",
  "linear-gradient(160deg, #434343 0%, #4f3f3f 50%, #414141 100%)",
  "linear-gradient(160deg, #434343 0%, #3f4f3f 50%, #394d3e 100%)",
];

// Remote posters are proxied through our own origin. Loading them directly
// sets third-party cookies and lets a host answer an <img> with an HTML
// challenge page, which Firefox then blocks (OpaqueResponseBlocking).
function posterUrl(raw: string | null | undefined): string | undefined {
  if (!raw) return undefined;
  if (!/^https:\/\//i.test(raw)) return undefined;
  return `/api/movies/thumbnail?url=${encodeURIComponent(raw)}`;
}

// Invalid values are caught here, before any request: a 422 from the API
// would print an error in the browser console.
function filterError(f: Filters, t: (key: string) => string): string | null {
  const year = (v: string) => /^\d{4}$/.test(v) && Number(v) >= 1870 && Number(v) <= 2100;
  if (f.yearMin && !year(f.yearMin)) return t("home.invalid-year");
  if (f.yearMax && !year(f.yearMax)) return t("home.invalid-year");
  if (f.yearMin && f.yearMax && Number(f.yearMin) > Number(f.yearMax)) return t("home.invalid-range");
  if (f.imdbMin && !(/^\d{1,2}(\.\d)?$/.test(f.imdbMin) && Number(f.imdbMin) <= 10)) return t("home.invalid-rating");
  if (f.query.length > 100 || f.genre.length > 50) return t("home.invalid-text");
  return null;
}

export default function Home() {
  const { lang, setLang, t } = useLanguage();

  const [username, setUsername] = useState("");
  const [profilePicture, setProfilePicture] = useState<string | null>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);

  // `draft` is what the controls show; `applied` is what was last searched.
  const [draft, setDraft] = useState<Filters>(DEFAULT_FILTERS);
  const [applied, setApplied] = useState<Filters>(DEFAULT_FILTERS);
  const [formError, setFormError] = useState<string | null>(null);

  const [movies, setMovies] = useState<DiscoverMovie[]>([]);
  const [isAuthReady, setIsAuthReady] = useState(false);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [isLoadingInitial, setIsLoadingInitial] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);

  const router = useRouter();
  const dropdownRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const requestId = useRef(0);

  const effectiveSort = applied.query.trim() && applied.sortBy === "downloads"
    ? { sortBy: "title", sortDir: "asc" }
    : { sortBy: applied.sortBy, sortDir: applied.sortDir };

  const fetchMovies = useCallback(
    async (targetPage: number, reset: boolean) => {
      // Only the latest request may update the grid, so a slow earlier
      // answer cannot overwrite newer results.
      const id = ++requestId.current;
      if (reset) setIsLoadingInitial(true);
      else setIsLoadingMore(true);
      setSearchError(null);

      const params = new URLSearchParams({
        q: applied.query.trim(),
        page: String(targetPage),
        limit: "24",
        source: applied.source,
        sort_by: applied.sortBy,
        sort_dir: applied.sortDir,
      });
      if (applied.genre.trim()) params.set("genre", applied.genre.trim());
      if (applied.yearMin) params.set("year_min", applied.yearMin);
      if (applied.yearMax) params.set("year_max", applied.yearMax);
      if (applied.imdbMin) params.set("imdb_min", applied.imdbMin);

      try {
        const res = await fetch(`/api/movies/discover?${params.toString()}`);
        if (!res.ok) throw new Error(t("home.search-failed"));
        const data = (await res.json()) as DiscoverResponse;
        if (id !== requestId.current) return;

        const incoming = Array.isArray(data.results) ? data.results : [];
        setWarning(data.warning || null);
        // archive.org often holds several uploads of one film: show it once.
        setMovies((prev) => {
          const known = new Set<string>();
          const fresh = (m: DiscoverMovie) => {
            const keys = [`${m.source}:${m.id}`, `${m.title.trim().toLowerCase()}|${m.year ?? ""}`];
            if (keys.some((k) => known.has(k))) return false;
            keys.forEach((k) => known.add(k));
            return true;
          };
          return [...(reset ? [] : prev), ...incoming].filter(fresh);
        });
        setPage(targetPage);
        setHasMore(Boolean(data.has_more));
      } catch (error) {
        if (id !== requestId.current) return;
        setSearchError(error instanceof Error ? error.message : t("error.generic"));
        if (reset) {
          setMovies([]);
          setHasMore(false);
        }
      } finally {
        if (id === requestId.current) {
          setIsLoadingInitial(false);
          setIsLoadingMore(false);
        }
      }
    },
    [applied, t]
  );

  useEffect(() => {
    getSessionUser().then((user) => {
      if (!user) {
        router.replace("/login");
        return;
      }
      setUsername(user.username);
      setProfilePicture(user.profile_picture ?? null);
      if (user.preferred_language === "fr" || user.preferred_language === "en" || user.preferred_language === "es") {
        setLang(user.preferred_language as Lang);
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

  // Infinite scroll: a marker under the grid loads the next page when it comes
  // into view. The observer is recreated after each page, and a new observer
  // reports at once if the marker is still visible - so a page that filters
  // left short keeps loading until the screen is full or the source ends.
  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries[0].isIntersecting) return;
        if (!hasMore || isLoadingInitial || isLoadingMore) return;
        fetchMovies(page + 1, false);
      },
      { rootMargin: "250px 0px" }
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [page, hasMore, isLoadingInitial, isLoadingMore, fetchMovies]);

  // Ratings are attached per page, so the IMDb order is applied to everything
  // loaded so far, not only within each page.
  const displayed = useMemo(() => {
    if (effectiveSort.sortBy !== "imdb_rating") return movies;
    const dir = effectiveSort.sortDir === "asc" ? 1 : -1;
    const rated = movies.filter((m) => m.imdb_rating !== null);
    const unrated = movies.filter((m) => m.imdb_rating === null);
    return [...rated.sort((a, b) => dir * ((a.imdb_rating ?? 0) - (b.imdb_rating ?? 0))), ...unrated];
  }, [movies, effectiveSort.sortBy, effectiveSort.sortDir]);

  const handleLogout = async () => {
    await logout();
    router.replace("/login");
  };

  const apply = (next: Filters) => {
    const invalid = filterError(next, t);
    setFormError(invalid);
    if (invalid) return;
    setApplied({ ...next, query: next.query.trim() });
  };

  const handleClearFilters = () => {
    const cleared = { ...DEFAULT_FILTERS, query: draft.query };
    setDraft(cleared);
    apply(cleared);
  };

  const handleLanguageChange = (next: Lang) => {
    setLang(next);
    // Saved to the profile, so the choice follows the user to other devices.
    sendForm("/api/users/me", { preferred_language: next }, "PATCH");
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
      if (!res.ok) throw new Error();
    } catch {
      setMovies((prev) => prev.map((m) => (`${m.source}:${m.id}` === key ? { ...m, watched: movie.watched } : m)));
    }
  };

  const openWatchPage = (movie: DiscoverMovie) => {
    router.push(`/watch/${encodeURIComponent(movie.source)}/${encodeURIComponent(movie.id)}`);
  };

  const setField = (field: keyof Filters) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setDraft((prev) => ({ ...prev, [field]: e.target.value }));

  const heroMovie = displayed.find((movie) => Boolean(movie.thumbnail)) ?? displayed[0] ?? null;

  if (!isAuthReady) return null;

  return (
    <div className="home-page">
      <header className="site-header f1">
        <div className="header-brand">
          <span className="metallic flicker">LUMIERE</span>
        </div>

        <form
          className="header-search"
          role="search"
          onSubmit={(e) => {
            e.preventDefault();
            apply(draft);
          }}
        >
          <input
            className="search-input"
            type="search"
            value={draft.query}
            onChange={setField("query")}
            maxLength={100}
            placeholder={t("home.search-placeholder")}
            aria-label={t("home.search-placeholder")}
          />
          <button className="search-btn" aria-label="Search" type="submit">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.35-4.35" />
            </svg>
          </button>
        </form>

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
                <img src={avatarUrl(profilePicture)} alt="avatar" className="header-avatar" />
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
                  <div className="dropdown-item" style={{ cursor: "default", pointerEvents: "none", color: "#6f6f6f" }}>
                    {username}
                  </div>
                )}
                <a href="/settings" className="dropdown-item" onClick={() => setDropdownOpen(false)}>
                  {t("settings")}
                </a>
                <div className="lang-item">
                  <span className="lang-label">{t("lang")}</span>
                  <select className="lang-select" value={lang} onChange={(e) => handleLanguageChange(e.target.value as Lang)}>
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

      <main>
        <section className="hero f2">
          <div className="hero-bg">
            {heroMovie?.thumbnail ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={posterUrl(heroMovie.thumbnail)} alt={heroMovie.title} className="hero-bg-image" />
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
              {applied.query ? `${t("home.search-results")} — "${applied.query}"` : t("home.no-search-desc")}
            </p>
            <div className="hero-actions">
              <button className="hero-btn" disabled={!heroMovie} onClick={() => heroMovie && openWatchPage(heroMovie)}>
                {t("home.watch-now")}
              </button>
              <button className="hero-btn hero-btn-secondary" onClick={() => fetchMovies(1, true)}>
                {t("home.refresh")}
              </button>
            </div>
          </div>
        </section>

        <div className="home-main">
          <form
            className="filters-panel f3"
            onSubmit={(e) => {
              e.preventDefault();
              apply(draft);
            }}
            noValidate
          >
            <div className="filters-grid">
              <label className="filter-field">
                <span>{t("home.sort")}</span>
                <select value={draft.sortBy} onChange={setField("sortBy")}>
                  <option value="downloads">{t("home.sort-popularity")}</option>
                  <option value="title">{t("home.sort-name")}</option>
                  <option value="imdb_rating">{t("home.sort-imdb")}</option>
                  <option value="year">{t("home.sort-year")}</option>
                </select>
              </label>
              <label className="filter-field">
                <span>{t("home.direction")}</span>
                <select value={draft.sortDir} onChange={setField("sortDir")}>
                  <option value="desc">{t("home.desc")}</option>
                  <option value="asc">{t("home.asc")}</option>
                </select>
              </label>
              <label className="filter-field">
                <span>{t("home.source")}</span>
                <select value={draft.source} onChange={setField("source")}>
                  <option value="all">{t("home.source-all")}</option>
                  <option value="archive">Archive.org</option>
                  <option value="peertube">PeerTube</option>
                </select>
              </label>
              <label className="filter-field">
                <span>{t("home.genre")}</span>
                <input value={draft.genre} onChange={setField("genre")} maxLength={50} placeholder="Drama" />
              </label>
              <label className="filter-field">
                <span>{t("home.year-min")}</span>
                <input value={draft.yearMin} onChange={setField("yearMin")} inputMode="numeric" maxLength={4} placeholder="1920" />
              </label>
              <label className="filter-field">
                <span>{t("home.year-max")}</span>
                <input value={draft.yearMax} onChange={setField("yearMax")} inputMode="numeric" maxLength={4} placeholder="1960" />
              </label>
              <label className="filter-field">
                <span>{t("home.imdb-min")}</span>
                <input value={draft.imdbMin} onChange={setField("imdbMin")} inputMode="decimal" maxLength={4} placeholder="7.5" />
              </label>
            </div>
            {formError && <p className="filter-error" role="alert">{formError}</p>}
            <div className="filters-actions">
              <button className="row-more" type="submit">{t("home.apply")}</button>
              <button className="row-more" type="button" onClick={handleClearFilters}>{t("home.reset-filters")}</button>
            </div>
          </form>

          {isLoadingInitial && <p className="search-status">{t("home.loading")}</p>}
          {searchError && <p className="search-status search-status-error">{searchError}</p>}
          {!isLoadingInitial && !searchError && displayed.length === 0 && !hasMore && (
            <p className="search-status">{t("home.no-results")}</p>
          )}

          <section className="movie-grid-section">
            <div className="grid-heading">
              <h2>{applied.query ? t("home.search-results") : t("home.popular-now")}</h2>
            </div>
            {warning ? <p className="provider-banner provider-banner-warning">{warning}</p> : null}

            <div className="movie-grid">
              {displayed.map((movie, i) => (
                <article key={`${movie.source}:${movie.id}`} className={`movie-card ${movie.watched ? "movie-card-watched" : "movie-card-unwatched"}`}>
                  <button type="button" className="movie-poster" onClick={() => openWatchPage(movie)}>
                    {movie.thumbnail ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={posterUrl(movie.thumbnail)} alt={movie.title} className="movie-poster-image" loading="lazy" />
                    ) : (
                      <div className="movie-poster-inner" style={{ background: POSTER_GRADIENTS[i % POSTER_GRADIENTS.length] }}>
                        <p className="movie-poster-year">{movie.year ?? "N/A"}</p>
                      </div>
                    )}
                    <span className={`watched-badge ${movie.watched ? "is-watched" : "is-unwatched"}`}>
                      {movie.watched ? t("home.watched") : t("home.unwatched")}
                    </span>
                  </button>
                  <p className="movie-title">{movie.title}</p>
                  <p className="movie-info">
                    {movie.year ?? "N/A"} · IMDb {movie.imdb_rating !== null ? movie.imdb_rating.toFixed(1) : "N/A"} · {movie.source === "peertube" ? "PeerTube" : "Archive.org"}
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
        </div>
      </main>

      <SiteFooter />
    </div>
  );
}
