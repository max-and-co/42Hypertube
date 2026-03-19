"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import "./home.css";

const LANGUAGES = [
  { value: "en", label: "English" },
  { value: "fr", label: "Français" },
  { value: "es", label: "Español" },
];

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
  const [username, setUsername] = useState("");
  const [profilePicture, setProfilePicture] = useState<string | null>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [language, setLanguage] = useState("en");

  const [searchInput, setSearchInput] = useState("");
  const [activeQuery, setActiveQuery] = useState("");

  const [sortBy, setSortBy] = useState("downloads");
  const [sortDir, setSortDir] = useState("desc");
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

      const params = new URLSearchParams({
        q: activeQuery.trim(),
        page: String(targetPage),
        limit: "24",
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
        if (reset) {
          setMovies([]);
          setHasMore(false);
        }
      } finally {
        if (reset) {
          setIsLoadingInitial(false);
        } else {
          setIsLoadingMore(false);
        }
      }
    },
    [activeQuery, effectiveSort.sortBy, effectiveSort.sortDir, genre, yearMin, yearMax, imdbMin]
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
      setIsAuthReady(true);
    });
  }, [router]);

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
            placeholder="Search movies..."
          />
          <button className="search-btn" aria-label="Search" onClick={handleSearch}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.35-4.35" />
            </svg>
          </button>
        </div>

        <div className="header-right">
          <button className="header-logout-btn" onClick={handleLogout}>Logout</button>
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
                  <select className="lang-select" value={language} onChange={(e) => setLanguage(e.target.value)}>
                    {LANGUAGES.map((l) => (
                      <option key={l.value} value={l.value}>
                        {l.label}
                      </option>
                    ))}
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
          <p className="hero-eyebrow">Featured Selection</p>
          <h1 className="hero-title metallic">{heroMovie?.title ?? "Most Popular Videos"}</h1>
          <p className="hero-meta">
            {heroMovie?.year ?? "N/A"}
            {heroMovie?.imdb_rating ? `  ·  IMDb ${heroMovie.imdb_rating.toFixed(1)}` : ""}
          </p>
          <p className="hero-desc">
            {activeQuery.trim()
              ? `Search results for "${activeQuery}" sorted by ${effectiveSort.sortBy}.`
              : "No search selected. Showing popular videos from external sources."}
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
              Watch Now
            </button>
            <button className="hero-btn hero-btn-secondary" onClick={() => fetchMovies(1, true)}>
              Refresh
            </button>
          </div>
        </div>
      </section>

      <main className="home-main">
        <section className="filters-panel f3">
          <div className="filters-grid">
            <label className="filter-field">
              <span>Sort</span>
              <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
                <option value="downloads">Popularity</option>
                <option value="title">Name</option>
                <option value="imdb_rating">IMDb</option>
                <option value="year">Year</option>
                <option value="seeders">Seeders</option>
                <option value="peers">Peers</option>
              </select>
            </label>
            <label className="filter-field">
              <span>Direction</span>
              <select value={sortDir} onChange={(e) => setSortDir(e.target.value)}>
                <option value="desc">Desc</option>
                <option value="asc">Asc</option>
              </select>
            </label>
            <label className="filter-field">
              <span>Genre</span>
              <input value={genre} onChange={(e) => setGenre(e.target.value)} placeholder="Drama" />
            </label>
            <label className="filter-field">
              <span>Year Min</span>
              <input value={yearMin} onChange={(e) => setYearMin(e.target.value)} inputMode="numeric" placeholder="1990" />
            </label>
            <label className="filter-field">
              <span>Year Max</span>
              <input value={yearMax} onChange={(e) => setYearMax(e.target.value)} inputMode="numeric" placeholder="2026" />
            </label>
            <label className="filter-field">
              <span>IMDb Min</span>
              <input value={imdbMin} onChange={(e) => setImdbMin(e.target.value)} inputMode="decimal" placeholder="7.5" />
            </label>
          </div>
          <div className="filters-actions">
            <button className="row-more" onClick={() => setActiveQuery(searchInput.trim())}>Apply</button>
            <button className="row-more" onClick={handleClearFilters}>Reset</button>
          </div>
        </section>

        {isLoadingInitial && <p className="search-status">Loading catalog...</p>}
        {searchError && <p className="search-status search-status-error">{searchError}</p>}
        {!isLoadingInitial && !searchError && movies.length === 0 && (
          <p className="search-status">No results match your criteria.</p>
        )}

        <section className="movie-grid-section">
          <div className="grid-heading">
            <h2>{activeQuery.trim() ? "Search Results" : "Popular Right Now"}</h2>
            <p>
              Sort: {effectiveSort.sortBy} ({effectiveSort.sortDir})
            </p>
          </div>

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
                    {movie.watched ? "Watched" : "Unwatched"}
                  </span>
                </button>
                <p className="movie-title">{movie.title}</p>
                <p className="movie-info">
                  {movie.year ?? "N/A"} · IMDb {movie.imdb_rating?.toFixed(1) ?? "N/A"}
                </p>
                <div className="card-actions">
                  <button className="row-more" onClick={() => handleToggleWatched(movie)}>
                    Mark {movie.watched ? "Unwatched" : "Watched"}
                  </button>
                </div>
              </article>
            ))}
          </div>

          <div ref={sentinelRef} className="scroll-sentinel" />
          {isLoadingMore && <p className="search-status">Loading next page...</p>}
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
          <p className="footer-copy">© MMXXV Lumiere — All Rights Reserved</p>
          <p className="footer-ornament">Pictures &amp; Entertainment</p>
        </div>
      </footer>
    </div>
  );
}
