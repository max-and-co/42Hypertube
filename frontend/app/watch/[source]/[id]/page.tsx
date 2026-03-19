"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import "./watch.css";

type MovieDetails = {
  id: number;
  title: string;
  year: number | null;
  imdb_rating: string | null;
  imdb_id: string | null;
  tmdb_id: string | null;
  duration_minutes: number | null;
  available_subtitles: string[];
  subtitle_languages: string[];
  genres: string[];
  thumbnail: string | null;
  cover_image: string | null;
  description: string | null;
  producer: string | null;
  director: string | null;
  main_cast: string[];
  original_language: string | null;
  stream_status: string;
  comment_count: number;
};

type MovieComment = {
  id: number;
  content: string;
  author_id: number;
  author_username: string;
  movie_id: number;
  created_at: string;
};

type StreamSubtitleTrack = {
  language: string;
  label: string;
  url: string;
};

type StreamSession = {
  session_id: string;
  status: string;
  error: string | null;
  stream_url: string | null;
  selected_file: string | null;
  subtitle_tracks: StreamSubtitleTrack[];
  default_subtitle_language?: string;
  source: string;
  external_id: string;
  movie_id: number;
};

function parseFloatOrNull(value: string | null): number | null {
  if (!value) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function parseIntOrNull(value: string | null): number | null {
  if (!value) return null;
  const n = Number(value);
  return Number.isInteger(n) ? n : null;
}

export default function WatchPage() {
  const params = useParams<{ source: string; id: string }>();
  const query = useSearchParams();
  const router = useRouter();

  const source = useMemo(() => decodeURIComponent(params.source || ""), [params.source]);
  const externalId = useMemo(() => decodeURIComponent(params.id || ""), [params.id]);

  const [movieId, setMovieId] = useState<number | null>(null);
  const [movie, setMovie] = useState<MovieDetails | null>(null);
  const [comments, setComments] = useState<MovieComment[]>([]);
  const [session, setSession] = useState<StreamSession | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [commentDraft, setCommentDraft] = useState("");
  const [commentSubmitting, setCommentSubmitting] = useState(false);

  const fetchComments = useCallback(async (targetMovieId: number) => {
    const response = await fetch(`/api/movies/${targetMovieId}/comments?page=1&limit=30`);
    if (!response.ok) {
      throw new Error(`Failed to fetch comments (${response.status})`);
    }
    const payload = (await response.json()) as MovieComment[];
    setComments(Array.isArray(payload) ? payload : []);
  }, []);

  const fetchMovie = useCallback(async (targetMovieId: number) => {
    const response = await fetch(`/api/movies/${targetMovieId}`);
    if (!response.ok) {
      throw new Error(`Failed to fetch movie (${response.status})`);
    }
    const payload = (await response.json()) as MovieDetails;
    setMovie(payload);
  }, []);

  const bootstrap = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const meResponse = await fetch("/api/users/me");
      if (!meResponse.ok) {
        router.replace("/login");
        return;
      }

      const ingestPayload = {
        source,
        external_id: externalId,
        title: query.get("title") || `Movie ${externalId}`,
        year: parseIntOrNull(query.get("year")),
        imdb_id: query.get("imdb_id"),
        imdb_rating: parseFloatOrNull(query.get("imdb_rating")),
        duration_minutes: parseIntOrNull(query.get("duration_minutes")),
        genres: (query.get("genres") || "").split(",").map((v) => v.trim()).filter(Boolean),
        thumbnail: query.get("thumbnail"),
        cover_image: query.get("cover_image"),
        description: query.get("description"),
        torrent_hash: query.get("torrent_hash"),
      };

      const ingestResponse = await fetch("/api/movies/external/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(ingestPayload),
      });
      if (!ingestResponse.ok) {
        throw new Error(`Failed to ingest movie (${ingestResponse.status})`);
      }

      const ingestData = (await ingestResponse.json()) as { movie_id: number };
      setMovieId(ingestData.movie_id);

      await Promise.all([fetchMovie(ingestData.movie_id), fetchComments(ingestData.movie_id)]);

      const sessionResponse = await fetch("/api/torrent/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          movie_id: ingestData.movie_id,
          source,
          external_id: externalId,
          title: ingestPayload.title,
          torrent_hash: ingestPayload.torrent_hash,
        }),
      });

      if (!sessionResponse.ok) {
        throw new Error(`Failed to create stream session (${sessionResponse.status})`);
      }

      const sessionData = (await sessionResponse.json()) as StreamSession;
      setSession(sessionData);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [externalId, fetchComments, fetchMovie, query, router, source]);

  useEffect(() => {
    if (!source || !externalId) {
      setError("Invalid watch URL");
      setLoading(false);
      return;
    }
    bootstrap();
  }, [bootstrap, externalId, source]);

  useEffect(() => {
    if (!session?.session_id) return;
    if (session.status === "ready" || session.status === "error") return;

    const interval = window.setInterval(async () => {
      try {
        const response = await fetch(`/api/torrent/sessions/${session.session_id}`);
        if (!response.ok) {
          throw new Error(`Session polling failed (${response.status})`);
        }
        const payload = (await response.json()) as StreamSession;
        setSession(payload);
      } catch {
        window.clearInterval(interval);
      }
    }, 1500);

    return () => window.clearInterval(interval);
  }, [session?.session_id, session?.status]);

  useEffect(() => {
    if (!session || session.status !== "ready") return;
    fetch(`/api/movies/${encodeURIComponent(externalId)}/watched-toggle?source=${encodeURIComponent(source)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ watched: true }),
    }).catch(() => {
      // Best effort; watch page should not fail if tracking update fails.
    });
  }, [externalId, session, source]);

  const streamSrc = session?.status === "ready" ? `/api/stream/${session.session_id}` : null;

  const handleSubmitComment = async (event: FormEvent) => {
    event.preventDefault();
    if (!movieId || !commentDraft.trim()) return;

    setCommentSubmitting(true);
    try {
      const response = await fetch(`/api/movies/${movieId}/comments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ comment: commentDraft.trim() }),
      });
      if (!response.ok) {
        throw new Error(`Comment submission failed (${response.status})`);
      }
      setCommentDraft("");
      await fetchComments(movieId);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to submit comment";
      setError(message);
    } finally {
      setCommentSubmitting(false);
    }
  };

  const handleLogout = async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    router.replace("/login");
  };

  return (
    <div className="watch-page">
      <header className="watch-header">
        <button className="watch-back" onClick={() => router.push("/home")}>Back</button>
        <h1 className="watch-brand">LUMIERE</h1>
        <button className="watch-logout" onClick={handleLogout}>Logout</button>
      </header>

      {loading && <p className="watch-status">Preparing watch page...</p>}
      {error && <p className="watch-status watch-status-error">{error}</p>}

      {!loading && movie && (
        <main className="watch-main">
          <section className="watch-player-panel">
            {streamSrc ? (
              <video key={streamSrc} className="watch-player" controls playsInline poster={movie.cover_image || movie.thumbnail || undefined}>
                <source src={streamSrc} />
                {(session?.subtitle_tracks || []).map((track) => (
                  <track
                    key={`${track.language}-${track.url}`}
                    src={track.url}
                    label={track.label}
                    srcLang={track.language}
                    kind="subtitles"
                    default={track.language === (session?.default_subtitle_language || "en")}
                  />
                ))}
              </video>
            ) : (
              <div className="watch-player watch-player-placeholder">
                <p>Stream status: {session?.status || "queued"}</p>
                {session?.error ? <p className="watch-status watch-status-error">{session.error}</p> : <p>Buffering video in background...</p>}
              </div>
            )}
          </section>

          <section className="watch-details-panel">
            <div className="watch-cover-wrap">
              {movie.cover_image || movie.thumbnail ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img className="watch-cover" src={movie.cover_image || movie.thumbnail || undefined} alt={movie.title} />
              ) : (
                <div className="watch-cover watch-cover-fallback" />
              )}
            </div>

            <div className="watch-meta">
              <h2>{movie.title}</h2>
              <p className="watch-meta-line">
                {movie.year || "N/A"} · {movie.duration_minutes ? `${movie.duration_minutes} min` : "Duration unknown"} · IMDb {movie.imdb_rating || "N/A"}
              </p>
              <p className="watch-meta-line">{(movie.genres || []).join(" · ") || "Genre unknown"}</p>
              {movie.description ? <p className="watch-summary">{movie.description}</p> : null}
              <p className="watch-credit"><strong>Director:</strong> {movie.director || "Unknown"}</p>
              <p className="watch-credit"><strong>Producer:</strong> {movie.producer || "Unknown"}</p>
              <p className="watch-credit"><strong>Main Cast:</strong> {(movie.main_cast || []).join(", ") || "Unknown"}</p>
              <p className="watch-credit"><strong>Subtitles:</strong> {(session?.subtitle_tracks || []).map((t) => t.label).join(", ") || "None detected yet"}</p>
            </div>
          </section>

          <section className="watch-comments-panel">
            <h3>Comments</h3>
            <form className="watch-comment-form" onSubmit={handleSubmitComment}>
              <textarea
                value={commentDraft}
                onChange={(e) => setCommentDraft(e.target.value)}
                placeholder="Leave your thoughts on this movie"
                rows={3}
              />
              <button type="submit" disabled={commentSubmitting || !commentDraft.trim()}>
                {commentSubmitting ? "Posting..." : "Post Comment"}
              </button>
            </form>

            <div className="watch-comment-list">
              {comments.length === 0 ? <p className="watch-empty">No comments yet.</p> : null}
              {comments.map((comment) => (
                <article key={comment.id} className="watch-comment">
                  <p className="watch-comment-author">{comment.author_username}</p>
                  <p>{comment.content}</p>
                </article>
              ))}
            </div>
          </section>
        </main>
      )}
    </div>
  );
}
