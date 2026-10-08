"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import "./watch.css";
import { useLanguage } from "../../../i18n/LanguageContext";
import { getSessionUser, logout } from "../../../lib/api";
import { localize } from "../../../lib/messages";
import { commentError, MAX_COMMENT_LENGTH } from "../../../lib/validation";
import SiteFooter from "../../../components/SiteFooter";

type MovieDetails = {
  id: number;
  title: string;
  year: number | null;
  imdb_rating: string | null;
  duration_minutes: number | null;
  genres: string[];
  thumbnail: string | null;
  cover_image: string | null;
  description: string | null;
  producer: string | null;
  director: string | null;
  main_cast: string[];
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

type StreamSubtitleTrack = { language: string; label: string; url: string };

type StreamSession = {
  session_id: string;
  status: string;
  mode: "direct" | "live" | null;
  progress: number;
  error: string | null;
  stream_url: string | null;
  subtitle_tracks: StreamSubtitleTrack[];
  default_subtitle_language: string | null;
};

const PLAYABLE = new Set(["ready", "complete"]);

function posterUrl(raw: string | null | undefined): string | undefined {
  if (!raw) return undefined;
  if (!/^https:\/\//i.test(raw)) return undefined;
  return `/api/movies/thumbnail?url=${encodeURIComponent(raw)}`;
}

export default function WatchPage() {
  const params = useParams<{ source: string; id: string }>();
  const router = useRouter();
  const { lang, t } = useLanguage();

  const source = useMemo(() => decodeURIComponent(params.source || ""), [params.source]);
  const externalId = useMemo(() => decodeURIComponent(params.id || ""), [params.id]);

  const [movieId, setMovieId] = useState<number | null>(null);
  const [movie, setMovie] = useState<MovieDetails | null>(null);
  const [comments, setComments] = useState<MovieComment[]>([]);
  const [session, setSession] = useState<StreamSession | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [commentDraft, setCommentDraft] = useState("");
  const [commentError_, setCommentError] = useState<string | null>(null);
  const [commentSubmitting, setCommentSubmitting] = useState(false);
  const markedWatched = useRef(false);

  const fetchComments = useCallback(async (targetMovieId: number) => {
    const response = await fetch(`/api/movies/${targetMovieId}/comments?page=1&limit=50`);
    if (!response.ok) throw new Error(t("watch.load-failed"));
    const payload = (await response.json()) as MovieComment[];
    setComments(Array.isArray(payload) ? payload : []);
  }, [t]);

  const startSession = useCallback(async () => {
    const response = await fetch("/api/torrent/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source, external_id: externalId }),
    });
    if (!response.ok) throw new Error(t("watch.stream-failed"));
    setSession((await response.json()) as StreamSession);
  }, [externalId, source, t]);

  const bootstrap = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const user = await getSessionUser();
      if (!user) {
        router.replace("/login");
        return;
      }

      // Only the film's identity is sent: its details are read by the server.
      const ingestResponse = await fetch("/api/movies/external/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source, external_id: externalId }),
      });
      const ingest = (await ingestResponse.json().catch(() => ({}))) as { ok?: boolean; movie_id?: number };
      if (!ingestResponse.ok || ingest.ok === false || !ingest.movie_id) throw new Error(t("watch.not-found"));
      const movie_id = ingest.movie_id;
      setMovieId(movie_id);

      const movieResponse = await fetch(`/api/movies/${movie_id}`);
      if (!movieResponse.ok) throw new Error(t("watch.load-failed"));
      setMovie((await movieResponse.json()) as MovieDetails);
      await fetchComments(movie_id);
      await startSession();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("error.generic"));
    } finally {
      setLoading(false);
    }
  }, [externalId, fetchComments, router, source, startSession, t]);

  useEffect(() => {
    if (!/^(archive|peertube)$/.test(source) || !externalId) {
      setError(t("watch.invalid-url"));
      setLoading(false);
      return;
    }
    bootstrap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, externalId]);

  // Poll until the download is complete (not just playable): subtitles found
  // later in the download are then added to the player too.
  useEffect(() => {
    if (!session?.session_id) return;
    if (session.status === "complete" || session.status === "error") return;
    const delay = PLAYABLE.has(session.status) ? 5000 : 1500;
    const timer = window.setTimeout(async () => {
      try {
        const response = await fetch(`/api/torrent/sessions/${session.session_id}`);
        if (response.ok) setSession((await response.json()) as StreamSession);
      } catch {
        // Next render retries.
      }
    }, delay);
    return () => window.clearTimeout(timer);
  }, [session]);

  useEffect(() => {
    if (!session || !PLAYABLE.has(session.status) || markedWatched.current) return;
    markedWatched.current = true;
    fetch(`/api/movies/${encodeURIComponent(externalId)}/watched-toggle?source=${encodeURIComponent(source)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ watched: true }),
    }).catch(() => undefined);
  }, [externalId, session, source]);

  const streamSrc = session && PLAYABLE.has(session.status) ? `/api/stream/${session.session_id}` : null;

  const handleRetry = async () => {
    setError(null);
    try {
      await startSession();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("error.generic"));
    }
  };

  const handleSubmitComment = async (event: FormEvent) => {
    event.preventDefault();
    if (!movieId) return;
    const invalid = commentError(commentDraft);
    setCommentError(invalid);
    if (invalid) return;

    setCommentSubmitting(true);
    try {
      const response = await fetch(`/api/movies/${movieId}/comments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ comment: commentDraft.trim() }),
      });
      if (!response.ok) throw new Error(t("watch.failed-comment"));
      setCommentDraft("");
      await fetchComments(movieId);
    } catch (err) {
      setCommentError(err instanceof Error ? err.message : t("watch.failed-comment"));
    } finally {
      setCommentSubmitting(false);
    }
  };

  const handleLogout = async () => {
    await logout();
    router.replace("/login");
  };

  const statusLabel = session ? t(`watch.status-${session.status}`) : t("watch.status-queued");

  return (
    <div className="watch-page page-shell">
      <header className="watch-header">
        <button className="watch-back" onClick={() => router.push("/home")}>{t("back")}</button>
        <Link href="/home" className="watch-brand">LUMIERE</Link>
        <button className="watch-logout" onClick={handleLogout}>{t("logout")}</button>
      </header>

      <main>
        {loading && <p className="watch-status">{t("watch.preparing")}</p>}
        {error && <p className="watch-status watch-status-error" role="alert">{error}</p>}

        {!loading && movie && (
          <div className="watch-main">
            <section className="watch-player-panel">
              {streamSrc ? (
                <video key={streamSrc} className="watch-player" controls playsInline poster={posterUrl(movie.cover_image || movie.thumbnail)}>
                  <source src={streamSrc} type="video/mp4" />
                  {(session?.subtitle_tracks || []).map((track) => (
                    <track
                      key={track.url}
                      src={track.url}
                      label={track.label}
                      srcLang={track.language === "und" ? undefined : track.language}
                      kind="subtitles"
                      default={track.language === session?.default_subtitle_language}
                    />
                  ))}
                </video>
              ) : (
                <div className="watch-player watch-player-placeholder">
                  <p>{t("watch.stream-status")} {statusLabel}</p>
                  {session?.status === "error" ? (
                    <>
                      <p className="watch-status watch-status-error">{session.error || t("watch.stream-failed")}</p>
                      <button className="watch-retry" type="button" onClick={handleRetry}>{t("watch.retry")}</button>
                    </>
                  ) : (
                    <p>
                      {session?.status === "transcoding" ? t("watch.converting") : t("watch.buffering")}
                      {session && session.progress > 0 ? ` · ${Math.round(session.progress * 100)}%` : ""}
                    </p>
                  )}
                </div>
              )}
              {streamSrc && session?.status !== "complete" && (
                <p className="watch-progress">
                  {t("watch.progress")} {Math.round((session?.progress ?? 0) * 100)}%
                  {session?.mode === "live" ? ` · ${t("watch.live-note")}` : ""}
                </p>
              )}
            </section>

            <section className="watch-details-panel">
              <div className="watch-cover-wrap">
                {movie.cover_image || movie.thumbnail ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img className="watch-cover" src={posterUrl(movie.cover_image || movie.thumbnail)} alt={movie.title} />
                ) : (
                  <div className="watch-cover watch-cover-fallback" />
                )}
              </div>

              <div className="watch-meta">
                <h1 className="watch-title">{movie.title}</h1>
                <p className="watch-meta-line">
                  {movie.year || "N/A"} · {movie.duration_minutes ? `${movie.duration_minutes} min` : t("watch.duration-unknown")} · IMDb {movie.imdb_rating || "N/A"}
                </p>
                <p className="watch-meta-line">{(movie.genres || []).join(" · ") || t("watch.genre-unknown")}</p>
                {movie.description ? <p className="watch-summary">{movie.description}</p> : null}
                <p className="watch-credit"><strong>{t("watch.director")}:</strong> {movie.director || t("watch.unknown")}</p>
                <p className="watch-credit"><strong>{t("watch.producer")}:</strong> {movie.producer || t("watch.unknown")}</p>
                <p className="watch-credit"><strong>{t("watch.cast")}:</strong> {(movie.main_cast || []).join(", ") || t("watch.unknown")}</p>
                <p className="watch-credit"><strong>{t("watch.subtitles")}:</strong> {(session?.subtitle_tracks || []).map((tr) => tr.label).join(", ") || t("watch.none-detected")}</p>
              </div>
            </section>

            <section className="watch-comments-panel">
              <h2>{t("watch.comments")}</h2>
              <form className="watch-comment-form" onSubmit={handleSubmitComment} noValidate>
                <textarea
                  value={commentDraft}
                  onChange={(e) => setCommentDraft(e.target.value)}
                  placeholder={t("watch.comment-placeholder")}
                  maxLength={MAX_COMMENT_LENGTH}
                  aria-label={t("watch.comment-placeholder")}
                  rows={3}
                />
                <p className="field-hint">{commentDraft.trim().length} / {MAX_COMMENT_LENGTH}</p>
                {commentError_ && <p className="filter-error" role="alert">{localize(commentError_, t)}</p>}
                <button type="submit" disabled={commentSubmitting || !commentDraft.trim()}>
                  {commentSubmitting ? t("watch.posting") : t("watch.post")}
                </button>
              </form>

              <div className="watch-comment-list">
                {comments.length === 0 ? <p className="watch-empty">{t("watch.no-comments")}</p> : null}
                {comments.map((comment) => (
                  <article key={comment.id} className="watch-comment">
                    <p className="watch-comment-author">
                      <Link href={`/users/${comment.author_id}`}>{comment.author_username}</Link>
                      <span className="watch-comment-date"> · {new Date(comment.created_at).toLocaleDateString(lang)}</span>
                    </p>
                    <p>{comment.content}</p>
                  </article>
                ))}
              </div>
            </section>
          </div>
        )}
      </main>

      <SiteFooter />
    </div>
  );
}
