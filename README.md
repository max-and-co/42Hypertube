# Hypertube (Lumière)

A web app to search and watch public-domain and Creative Commons films. Films are
downloaded on the server with BitTorrent and play in the browser while they
download. 42 school project, see `hypertube.subject.pdf`.

## Run it

1. Copy the environment file and fill in the keys you have:
   ```bash
   cp .env.example .env
   ```
   - `FT_CLIENT_*`, `GITHUB_CLIENT_*`: OAuth apps (42 intra, GitHub).
   - `SMTP_*`: password-reset e-mails. Left empty, the reset link is printed in the user-service logs.
   - `OMDB_API_KEY` and/or `TMDB_API_KEY`: IMDb ratings, cast and summaries. Without them, films show no rating.
   - `OPENSUBTITLES_API_KEY` (optional): extra English / preferred-language subtitles.
   - `JWT_SECRET_KEY`: any long random string.
2. Start everything:
   ```bash
   docker compose up --build
   ```
3. Open http://localhost:8080

`.env` is ignored by git: never commit it.

## Services

| Container | Role |
|---|---|
| `nginx` | The only entry point (port 8080). Routes `/api/...` to the services, everything else to Next.js. Rate-limits login forms. |
| `nextjs` | Frontend (Next.js 14, production build). |
| `user-service` | FastAPI: accounts, OAuth, profiles, film metadata and ratings, comments, the public REST API. |
| `torrent-service` | FastAPI: source search (archive.org + PeerTube), BitTorrent download with libtorrent, streaming, FFmpeg conversion, subtitles. |
| `db` | PostgreSQL 16, reachable only by the two services. |

## How playing while downloading works

- libtorrent downloads the chosen video file in order; the pieces right after
  what is already on disk get deadlines, so HTTP webseeds follow the order too.
- A film is "ready" once the first 20 MB are on disk without gaps.
- `/api/stream/:session` answers byte ranges. A range the download has not
  reached yet waits for its pieces (it never sends missing bytes).
- mp4/webm are served as they are. Other formats (mkv, avi…) are piped through
  FFmpeg as they download and played as fragmented mp4 while converting; the
  result is then kept as a normal mp4 for later viewers.
- Finished downloads are kept (`torrent_media` volume). Films nobody watched for
  30 days (`MEDIA_RETENTION_DAYS`) are erased by a background task.

## Public API

Get a token with `POST /api/oauth/token` (`client_id` = username or e-mail,
`client_secret` = password), then send `Authorization: Bearer <token>`.

| Route | Auth |
|---|---|
| `GET /api/users`, `GET /api/users/:id`, `PATCH /api/users/:id` | token (e-mail and password: owner only) |
| `GET /api/movies`, `GET /api/movies/:id` | public |
| `GET /api/comments`, `GET/PATCH/DELETE /api/comments/:id` | token (changes: author only) |
| `POST /api/comments`, `GET/POST /api/movies/:id/comments` | token |

Anything else under `/api` answers `404`.

## Health checks

- http://localhost:8080/api/torrent/health
- http://localhost:8080/api/torrent/health/providers (archive.org, PeerTube, OMDb reachability)
