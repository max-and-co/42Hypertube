# Hypertube — QA Report (subject v7.1)

Tester: Claude (automated browser QA, Chromium-based in-app browser)
Date: 2026-10-08
Stack: `docker-compose up --build` → http://localhost:8080
Scope: mandatory part + general/eliminatory rules. External OAuth logins and the real reset-email inbox are **out of scope** (only redirects / token generation verified).
Not testable here: Firefox compatibility (only Chromium available).

Legend: ✅ pass · ❌ fail · 🔧 fixed & retested · ⚠️ partial / note · ⏭️ skipped (out of scope)

---

## Summary

* **~110 checks** across the subject (general rules, UI/auth, profile/language, library, video, REST API) – driven through the real UI in the browser, plus API scripts.
* **44 bugs found → all fixed and re-tested** (see Bug log). Severity highlights:
  * **Eliminatory / security**: stored XSS via avatar upload (#23), crash on any 422 (#3), console errors on every logged-out page (#2), OAuth login-CSRF (#18), reset-email timing enumeration + plain-text reset tokens (#17), server path leaks (#34).
  * **Mandatory video part was not met before**: archive.org never used BitTorrent nor stored files (#27), torrent "ready" on sparse files (#28), AVI never converted / MKV not on the fly (#29), retention by file age (#31), subtitles never loaded (#32/#33). The streaming engine was rewritten (`torrent-service/services/{torrent_engine,session_service,media_service}.py`).
  * **Search**: only one source per search (#7), "popular" not popular and no covers (#8), filters broken / racy (#13–#15).
  * **Stack didn't start** from a fresh build (#1).
* Final state: **0 console errors/warnings and 0 failed requests** on every page; API suite 44/44 green; no server errors in normal use.

## Bug log (bug → fix → retest)

| # | Requirement | Bug | Fix | Retest |
|---|---|---|---|---|
| 1 | G1 | Fresh `docker compose up --build`: user-service & torrent-service crash on import — `sqlalchemy` (unpinned) no longer pulls `greenlet`, required by `sqlalchemy.ext.asyncio` → nginx 502 on all API calls | `sqlalchemy[asyncio]` in both `requirements.txt` | 🔧 both `/health` → 200, DB connected |
| 2 | G4 | Every logged-out page load logs 2× `401 (Unauthorized)` console errors (session probe `GET /api/users/me`) | New `GET /api/auth/session` (always 200, `{authenticated, user}`) + `frontend/app/lib/session.ts`; login/register/home/settings/watch use it | 🔧 login page: only `/api/auth/session → 200`, no console errors |
| 3 | U2/G4 | **Crash**: any 422 validation error (e.g. reserved email domain) → `setError(data.detail)` gets an array → "Objects are not valid as a React child" → full-page Next error overlay. Same pattern in login, register, forgot, reset, settings (×2) | `frontend/app/lib/api.ts` `readErrorMessage()` flattens FastAPI errors to a string; used in all 6 places | 🔧 register with `x@test.local` shows readable inline error, no crash |
| 4 | U3/U6/U9, G8 | Server accepted whitespace-only first/last name & username, HTML in username (`<script>`), 10k-char fields, any `preferred_language`, password `password` | Validators in `user-service/schemas.py` (username `[A-Za-z0-9_.-]{3,30}`, names letters only ≤50, password 8–128 w/ letter+digit, lang ∈ en/fr/es, email ≤254, comment 1–1000, avatar ref restricted) + mirrored client checks (`pattern`, `maxLength`, `isStrongPassword`) | 🔧 all bad payloads → inline errors (UI) / 422 (API) |
| 5 | U7/U8 | Duplicate check case-sensitive: `QA1@EXAMPLE.COM` / `QA_USER1` registered alongside `qa1@example.com` / `qa_user1` | Emails lower-cased in schema; all email/username lookups use `func.lower()` (auth, users, oauth) | 🔧 both → 400 "already registered/taken"; login with `QA1@Example.com` works |
| 6 | dev env | `next dev` / `uvicorn --reload` in Docker didn't pick up file edits (bind-mount events not delivered) → stale code served | `WATCHPACK_POLLING=true` (nextjs), `WATCHFILES_FORCE_POLLING=true` (both FastAPI services) in `docker-compose.yml` | 🔧 edits recompiled & served |
| 7 | S3 | Search queried **one** source at a time (dropdown PDT *or* archive.org); subject requires ≥ 2 sources per search | New `source=all` (default) in torrent-service `search_movies` → `_search_all` queries PDT + archive.org concurrently, merges & sorts; user-service + UI accept/default to `all` ("All sources") | 🔧 provider banner "PDT+ARCHIVE", results from both |
| 8 | S2/S5 | "Popular" list = PDT only, `downloads` null for every item → effectively reverse-alphabetical ("Zorro's Fighting Legion 9, 8, 7…"); 0/24 cards had cover, year or rating (only first 12 enriched, all obscure serials) | Popular = merged sort by archive.org downloads (+rating tiebreak); enrichment of every result via OMDb → TMDb fallback, cached per title | 🔧 page 1: classics by downloads; 32/45 covers, 30/45 ratings |
| 9 | S8 | archive.org search: `total = len(page)` → `has_more` always false → infinite scroll stopped after page 1 | total from `numFound` | 🔧 "night" p2 returns 24 more |
| 10 | G13 | archive.org queries hit **all** `mediatype:movies` (arbitrary user uploads: vlogs, conference talks, "Dr. Sex (2010)") – licensing unknown | Restricted to `collection:(feature_films)` (curated public-domain films); query matches titles; sort by `titleSorter` | 🔧 "night" → 398 relevant films |
| 11 | S5 | Wrong metadata: title-only OMDb lookup → "The Fast and the Furious (1955)" showed 2001 Vin Diesel poster, "Jungle Book (1942)" the 2016 Disney poster | Pass known year (`y`) to OMDb / TMDb | 🔧 correct 1942 poster; 1955 film keeps its own frame |
| 12 | G4/S5 | 3 dead OMDb poster URLs → 3× `Failed to load resource: 404` console errors + broken image icons | Server HEAD-checks poster URLs once (cached) and falls back to TMDb; client `onError` → placeholder | 🔧 0 broken images, 0 console errors |
| 13 | S11 | Genre filter: PDT got `Horror` but slugs are lowercase (`horror`, `scifi`, `westerns`…) → 0 PDT results; archive.org filtered genre *after* fetching 24 → 2 results while total said 28 517 | PDT slug mapping; genre + year range pushed into archive.org query (`subject:`/`year:[a TO b]`); free-text genre → `<select>` of supported genres | 🔧 Horror 1930–40 → 26 films from both sources |
| 14 | S12/S13 | Filter text inputs fired a request **per keystroke**; invalid values (`abc`, min>max, IMDb 11) sent to API → 422 → console error + raw "Discover failed (422)" | Draft inputs committed on Apply/Enter with validation + translated messages | 🔧 0 requests while typing / for invalid input; clear messages |
| 15 | S11/S12 | **Race**: older (genre-only) response arrived after newer (genre+year) one and overwrote the grid → wrong results shown | Request sequence guard + `AbortController` in `fetchMovies` | 🔧 same scenario → only 1931–1940 horror |
| 16 | S6 | Watched vs unwatched barely distinguishable: tiny transparent badge unreadable on posters, cards otherwise identical | Badge solid backdrop; watched posters desaturated/dimmed | 🔧 screenshot: watched card clearly greyed |
| 17 | L8 / security | Forgot-password: registered email answered in **1.84 s** (synchronous SMTP) vs **0.01 s** for unknown → account enumeration by timing; reset token stored **in plain text** in DB | Email sent via `BackgroundTasks` after the response; only `sha256(token)` stored and compared | 🔧 unknown 0.003 s; full reset flow re-verified with hashed token |
| 18 | L17 / security | OAuth had **no `state`** → login CSRF (attacker can log a victim into the attacker's account) | Random `state` + 10-min HttpOnly `oauth_state` cookie, constant-time compare on callback | 🔧 forged/missing state → `/login?error=oauth_failed` |
| 19 | L16 | User denying access on 42/GitHub (`?error=access_denied`, no `code`) → raw JSON **422** page; GitHub callback didn't check `/user` status (→ 500 on `d["id"]`); `redirect_uri` not URL-encoded | `code`/`state` optional → graceful redirect; status/`id` checks; only verified primary GitHub email; `urlencode` for authorize URLs | 🔧 all bad callbacks → login page with "OAuth authentication failed" |
| 20 | P2/P3 | Language picked in the home header only went to localStorage; home re-applied the profile language on load → **choice reverted on every refresh** | Header picker also `PATCH /api/users/me {preferred_language}` (`savePreferredLanguage`) | 🔧 ES survives reload and logout/login; logged-out default EN |
| 21 | P2 | Untranslated UI strings: "Source", "Provider used:", genre names, sort label showed raw API key ("downloads (desc)") | Translation keys for all of them (en/fr/es) | 🔧 home fully Spanish |
| 22 | P5 | Settings form lacked client-side username/name/email constraints (server rejected, but no native feedback) | `pattern` / `maxLength` like registration | 🔧 |
| 23 | **G10 / P7 – security (eliminatory)** | Avatar upload trusted client filename & content-type: `evil.html` sent as `image/png` was stored and **served as `text/html` from our origin → stored XSS**; SVG with `<script>` served as `image/svg+xml`; text file named `.png` accepted; no size limit | Pillow: verify + **re-encode** (PNG/JPEG/GIF/WebP only), extension from detected format, 5 MB cap, decompression-bomb guard, old avatar deleted; avatars served only with image MIME; site-wide `X-Content-Type-Options: nosniff` (nginx); malicious test files removed from disk | 🔧 html/svg/fake → "must be a PNG, JPEG, GIF or WebP"; PNG+HTML polyglot re-encoded (script stripped) |
| 24 | P6/P7 | nginx default `client_max_body_size 1m` → any normal photo >1 MB rejected with nginx HTML 413 → generic "Upload failed" + console error | `client_max_body_size 6m`; client checks type & size before uploading (no request, translated message) | 🔧 4.9 MB photo uploads; 15 MB → "must be at most 5 MB", 0 requests |
| 25 | P8 / security | User search `ILIKE '%q%'` didn't escape `%`/`_` → `__` matched every user | `_escape_like()` + `escape='\\'` | 🔧 `__` → [] |
| 26 | G2 | Login, register, forgot, reset, settings had **no header/main/footer**; watch page had no footer | Brand block → `<header>`, card → `<main>`, shared `components/SiteFooter.tsx` (+ styles in globals.css) | 🔧 header+main+footer on every page |
| 27 | **V6/V8 – mandatory** | **archive.org videos never used BitTorrent**: `/api/stream` 307-redirected to `https://archive.org/download/…mp4` (plain HTTP, nothing saved on server) | archive.org's official `<item>_archive.torrent` (web-seeded) downloaded with libtorrent like PDT; file stored under `/data/media/<source>-<id>/` | 🔧 his_girl_friday downloaded via BitTorrent, served from server |
| 28 | **V6 – mandatory** | Torrent readiness = "file size ≥ 20 MB" on a **sparse** file (no sequential mode) → "ready" with holes / never ready; partially-downloaded data served as zeros | New `services/torrent_engine.py`: shared libtorrent session, only the video file wanted, sequential + time-critical head pieces, ready = first 20 MB of pieces present; piece-aware Range reader waits/boosts missing pieces (`piece_priority` + deadline, 6-piece look-ahead) | 🔧 plays at 3 % downloaded; seek to 60:00 mid-download resumes in 15 s |
| 29 | **V12 – mandatory** | MKV "conversion" = full ffmpeg transcode **before** playback, run on an incomplete file; **AVI (all PDT files) never converted → unplayable** | Non-native formats streamed through ffmpeg → fragmented MP4 **on the fly** (fed from the piece-aware reader while downloading); after completion a background job builds a seekable faststart MP4 for later views; ffmpeg killed on disconnect | 🔧 PDT Nosferatu.avi plays (368×288) at 9 % downloaded; MKV test → fMP4 with `moof`; no leaked ffmpeg |
| 30 | V8 | Completion never recorded; partially downloaded files were treated as complete on next visit | `.complete` marker + DB `video_path`; reuse only when marker & file exist | 🔧 after service restart: ready instantly, no torrent added, Range 13 ms |
| 31 | **V9 – mandatory** | Retention deleted files by **file mtime**, not "unwatched for a month" (a film watched yesterday but downloaded 31 days ago was erased; a never-rewatched one could survive) | `purge_unwatched_movies()`: movies whose `last_watched_at` > 30 days → delete their top-level folder + subtitles, reset DB; live sessions recreated if file vanished | 🔧 40-day-old film purged (folder + subs), 5-day-old kept |
| 32 | V10 | Subtitle language detected by substring → `his_girl_friday.asr.srt` (English ASR) labelled **FR** ("fr" in "friday") | Token-based detection; archive `.asr.` captions = English | 🔧 labelled English |
| 33 | V10 | Subtitle `<track>` pointed cross-origin to raw `.srt` → never loaded (browsers need same-origin/CORS **WebVTT**) | Server downloads, converts SRT→VTT (incl. 1–2-digit fractions used by archive ASR), serves `/api/subtitles/<session>/en.vtt` as `text/vtt` | 🔧 1286 cues loaded |
| 34 | security | Stream session API exposed server paths (`selected_file`, `local_path`) and `GET /movies/:id` exposed `video_path`; `external_id` used unvalidated in archive URLs/paths; client-supplied `movie_id` could overwrite another movie's stream state | Public session view; `video_path` removed; `external_id` regex per source; `movie_id` must match (source, external_id) | 🔧 mismatched movie_id → 400 |
| 35 | A14 | Leftover debug route `GET /api/torrent/protected` | Removed | 🔧 |
| 36 | V2/V3/P10 | Comments: no date shown; overlong comment → raw "Comment submission failed (422)" page banner + console error; author not linkable to a profile | `maxLength=1000` + counter, inline translated errors, `<time>` with locale date, author → new `/profile/[id]` page (picture, names, language, never email) | 🔧 |
| 37 | V14 / A11 | Invalid watch URLs (`/watch/foo/bar`, `/watch/pdt/abc`, `../../etc`) still called ingest → **junk movie rows created in DB**; page showed raw "Failed to create stream session (400)" next to a "queued / buffering" placeholder; non-existent archive item showed the raw internal error (with internal URL + MDN link) | Client validates source/id before any request; ingest validates format and that the archive.org item exists (404 otherwise); session errors reduced to codes (`unavailable`/`failed`) shown as translated messages, details only in server log | 🔧 invalid → "invalid URL", 0 API calls; missing item → "not available from its source" |
| 38 | V7 / A11 | One watch-page visit fired ingest ×3 + stream-session ×3 (effect re-ran on language load + StrictMode) and `watched-toggle` on **every 1.5 s poll** | Bootstrap and mark-watched guarded per film with refs | 🔧 each call exactly once |
| 39 | S5 | PDT titles have no year → title-only match picked remakes ("Nosferatu" → **2024**, "A Star is Born" → 2018) | For PDT, OMDb search → oldest exact-title match (public-domain catalogue) | 🔧 Nosferatu 1922, A Star is Born 1937 |
| 40 | G3 | Mobile 375 px: home footer 3rd column clipped; placeholder posters 5 px too wide; card pages (row flex) put the new footer *beside* the card and cards overflowed once stacked | Footer links wrap ≤640 px; `box-sizing: border-box` on posters/cards; card pages stack column (scoped `body .x-page` overrides) | 🔧 0 overflowing elements on all pages at 375 & 1280 px |
| 41 | A5 / G13 | `GET /movies` ("front page") sorted the **text** rating desc with NULLs first → junk first; listed startup-seeded **copyrighted** titles (Shawshank, Godfather, Inception…) that have no legal source | Only archive/pdt films, not errored, numeric rating desc NULLS LAST, limit 100; seeding of the copyrighted sample movies removed from `main.py` (existing rows left in DB, filtered out) | 🔧 18 real films, best rated first |
| 42 | A14 | Unknown `/api/*` routes fell through to Next.js → HTML 404 page | nginx `location /api/` → JSON `{"detail":"Not Found"}` 404 | 🔧 |
| 43 | G5 | Server errors during normal use: concurrent `watched-toggle` → `UniqueViolation` → **500 + traceback**; nginx `upstream timed out` on `/api/stream` (60 s default while waiting for pieces); full traceback logged for an expected "item not found" | Atomic `INSERT … ON CONFLICT DO UPDATE` (+ source validation); `proxy_read/send_timeout 600s` for streams; unavailable videos logged as one warning line | 🔧 10 concurrent toggles → 10×200, 0 tracebacks |
| 44 | P1 | Register page shown in French/Spanish (saved UI language) but its language select defaulted to English → new account silently English | Select pre-filled with current UI language | 🔧 FR UI → "fr" preselected |

---

## Requirements & results

### G — General instructions / eliminatory rules
| ID | Requirement | Result | Notes |
|---|---|---|---|
| G1 | `docker compose up --build` starts all services from scratch, no errors | 🔧 | after bug #1 fix all 5 containers up, health OK |
| G2 | Every page has header, main section, footer | 🔧 | bug #26 |
| G3 | Usable on mobile (375px): no horizontal scroll, readable, all controls reachable | 🔧 | bug #40 – home, watch, settings, profile, forgot, reset checked at 375 px; screenshots OK |
| G4 | No errors/warnings/notices in browser console on any page (eliminatory) | 🔧 | bugs #2/#3/#12/#14/#24/#36/#37 – final sweep: **0 console errors/warnings, 0 failed requests** on all 13 page states (see below). ⚠️ residual risks listed in Recommendations |
| G5 | No errors/warnings in server logs during normal use (eliminatory) | 🔧 | bug #43; remaining log lines are only dev `WatchFiles … Reloading` |
| G6 | `.env` is git-ignored, no credentials committed | ✅ | `.env` in `.gitignore`, `git ls-files` doesn't list it |
| G7 | Passwords hashed in DB (no plain text) | ✅ | bcrypt `$2b$12$` hashes in `users.hashed_password` |
| G8 | HTML/JS injection rendered inert everywhere user text is shown | 🔧 | usernames/names restricted (bug #4); comments & search render as text; avatar XSS fixed (bug #23) |
| G9 | SQL injection attempts in all inputs have no effect | ✅ | SQLAlchemy bound parameters everywhere; SQLi strings in login/search/comments inert; LIKE wildcards escaped (bug #25) |
| G10 | Upload accepts only real images (no html/svg/script/oversized files) | 🔧 | bug #23/#24 |
| G11 | Library & video pages only reachable when authenticated (redirect to login) | ✅ | all protected pages redirect to /login; APIs 401 (see A13) |
| G12 | Forbidden torrent-stream libraries not used (webtorrent, peerflix, pulsar) | ✅ | no webtorrent/peerflix/pulsar; streaming implemented in-house over python-libtorrent (BitTorrent client library) + ffmpeg |
| G13 | Only legal sources used (royalty-free / public domain) | 🔧 | PDT + archive.org `feature_films` only (bug #10); copyrighted seed removed from front page (bug #41) |

### U — User interface: registration
| ID | Requirement | Result | Notes |
|---|---|---|---|
| U1 | Register form asks email, username, last name, first name, password | ✅ | first, last, username, email, password+confirm, language |
| U2 | Empty required fields are rejected (client + server) | 🔧 | native `required` blocks empty; bug #3 (crash on 422) fixed |
| U3 | Whitespace-only names/username rejected | 🔧 | bug #4: server now rejects whitespace-only names/username |
| U4 | Invalid email format rejected | ✅ | native type=email + server EmailStr (reserved domains rejected) |
| U5 | Password < 8 chars rejected; mismatch with confirm rejected | ✅ | client: "do not match" / length messages |
| U6 | Weak password policy ("somehow protected") | 🔧 | bug #4: letter+digit required, `password` rejected |
| U7 | Duplicate email rejected with clear error | 🔧 | exact dup ✅; case-variant dup was accepted → bug #5 fixed |
| U8 | Duplicate username rejected with clear error | 🔧 | same as U7 |
| U9 | Overlong inputs (e.g. 10k-char username) rejected | 🔧 | bug #4: 300-char name rejected (maxLength client, ≤50 server) |
| U10 | Successful registration → redirected to login, can log in | ✅ | redirected to /login; login with new account works |
| U11 | Already-logged-in user visiting /register is redirected to /home | ✅ | logged-in user on /register → /home |

### L — Login / logout / password reset
| ID | Requirement | Result | Notes |
|---|---|---|---|
| L1 | Login with username + password works | ✅ | `qa_user1` → /home |
| L2 | Login with wrong password shows error, no crash | ✅ | "Incorrect credentials" |
| L3 | Login with unknown user shows same generic error | ✅ | identical generic message (no enumeration) |
| L4 | Login with empty fields blocked | ✅ | native required |
| L5 | Auth cookie is HttpOnly + SameSite | ✅ | `HttpOnly; SameSite=lax; Max-Age=604800` (no `Secure` – OK on http localhost) |
| L6 | Logout in one click from every logged-in page (home, settings, watch) | ✅ | one click → /login and session cleared from home (header), settings, profile, watch |
| L7 | After logout, protected pages redirect to login; back button doesn't expose data | ✅ | /home, /settings, /watch → /login when logged out; back button shows nothing |
| L8 | "Forgot password" form validates email & shows neutral message (no user enumeration) | 🔧 | native email validation; same neutral message for known/unknown; bug #17 timing |
| L9 | Reset token generated; reset page with valid token sets new password | ✅ | token link → new password set, success + redirect |
| L10 | Reset with invalid / reused token rejected | ✅ | bogus / reused / expired token → 400 with message |
| L11 | Reset page without token shows error, form disabled | ✅ | "Invalid reset link", inputs + button disabled |
| L12 | Reset new password validation (length, mismatch) | ✅ | mismatch & weak password messages |
| L13 | Old password stops working after reset; new one works | ✅ | old password → 401, new → 200 |
| L14 | OAuth 42 button redirects to intra authorize URL with correct params | 🔧 | 307 → intra authorize with client_id, encoded redirect_uri, response_type=code, state |
| L15 | OAuth GitHub button redirects to GitHub authorize URL with correct params | 🔧 | 307 → GitHub authorize with client_id, encoded redirect_uri, scope, state |
| L16 | OAuth callback without/with bad `code` fails gracefully (no 500) | 🔧 | bug #19 |
| L17 | OAuth uses `state` param (CSRF protection) | 🔧 | bug #18 |
| L18 | Full 42 / GitHub login round-trip | ⏭️ | out of scope (external accounts) |

### P — Profile / language
| ID | Requirement | Result | Notes |
|---|---|---|---|
| P1 | Preferred language selectable, defaults to English | ✅ | register/settings/header selectors, default English |
| P2 | Changing language translates the whole UI (all pages) | 🔧 | bug #21 (plot/metadata text stays in provider language) |
| P3 | Language choice persists (saved to profile, survives logout/login) | 🔧 | bug #20 |
| P4 | User can modify email (with validation + duplicate check) | ✅ | duplicate (case-insensitive) & invalid email rejected; change saved |
| P5 | User can modify first/last name, username (validation, duplicates) | ✅🔧 | server validation ✅; client attrs bug #22 |
| P6 | User can upload a profile picture; it shows in header & settings | ✅ | avatar shown in settings & header; 4.9 MB photo OK |
| P7 | Upload rejects non-image files / fake image content / oversized | 🔧 | bug #23/#24 |
| P8 | Can view another user's profile (picture + info) | ✅ | member search → profile card; `/profile/:id` page |
| P9 | Other user's email never shown (UI + API) | ✅ | no email in UI, `/users/:id`, `/users/profile/:id` |
| P10 | Profile reachable from comment author name | 🔧 | bug #36 |

### S — Library: search & thumbnails
| ID | Requirement | Result | Notes |
|---|---|---|---|
| S1 | Library has a search field and a list of thumbnails | ✅ | header search field + thumbnail grid |
| S2 | No search → most popular videos shown, sorted by a popularity criterion | 🔧 | bug #8 – now sorted by archive.org downloads |
| S3 | Search queries ≥ 2 external sources | 🔧 | bug #7 – PDT + archive.org per search |
| S4 | Search results displayed as thumbnails, sorted by name | ✅ | "night" → titles ascending, checked monotonic |
| S5 | Thumbnail shows name, year (if any), IMDb rating (if any), cover image | ⚠️🔧 | bugs #8/#11/#12; obscure PDT titles with no OMDb/TMDb match still show styled placeholder (no cover exists anywhere) |
| S6 | Watched vs unwatched visually differentiated | 🔧 | bug #16 |
| S7 | Watching a video marks it watched in the library | ✅ | after a stream starts, card shows "Watched" in library |
| S8 | Infinite scroll: next page loads asynchronously, no "load more" link | 🔧 | 45 → 91 → 137 cards on scroll, no load-more link; bug #9 fixed archive pagination |
| S9 | No duplicate cards across pages | ✅ | no duplicate keys; ⚠️ archive.org itself has 2 uploads of "Sex Madness" (different ids) |
| S10 | Sort by name / IMDb / year / popularity, asc & desc | ✅ | name ↑/↓, IMDb ↓ monotonic, year, popularity; ⚠️ rating/year sort is per fetched page (providers have no global rating) |
| S11 | Filter by genre | 🔧 | bugs #13/#15 |
| S12 | Filter by year range (incl. invalid input like "abc", min>max) | 🔧 | bugs #14/#15 |
| S13 | Filter by IMDb minimum (incl. invalid input) | 🔧 | ≥7 → all ratings ≥7, monotonic; ⚠️ post-filtered per page |
| S14 | Reset filters | ✅ | all selects/inputs back to default, list reloaded |
| S15 | Empty search results → friendly message | ✅ | "No results match your criteria." |
| S16 | Search with special chars / injection payloads handled | ✅ | `' OR 1=1 --` and `<img onerror>` → no results, rendered as text |

### V — Video page
| ID | Requirement | Result | Notes |
|---|---|---|---|
| V1 | Details: player, summary, cast (producer, director, main cast), year, length, IMDb grade, cover | ✅ | player, cover, year, length, IMDb, genres, summary, director, producer, cast, subtitles |
| V2 | Comment form: post comment, appears in list with author & date | 🔧 | bug #36 |
| V3 | Empty / whitespace / overlong comment rejected | 🔧 | whitespace blocked; length bug #36 |
| V4 | HTML/JS in comment rendered as text | ✅ | `<img onerror>`/`<script>` rendered as text, not executed |
| V5 | Prior comments listed | ✅ | listed newest first with author & date |
| V6 | Torrent launched server-side; stream starts once enough buffered (before full download) | 🔧 | bugs #27/#28 – playable at 3 % downloaded |
| V7 | Download/processing is non-blocking (site usable meanwhile) | ✅ | API latency 2–11 ms while downloading; all work in asyncio tasks / libtorrent threads |
| V8 | Fully downloaded movie saved; re-opening doesn't re-download | 🔧 | bug #30 |
| V9 | Movies unwatched for 1 month are deleted (cleanup job exists) | 🔧 | bug #31 |
| V10 | English subtitles downloaded & selectable when available | 🔧 | bugs #32/#33 |
| V11 | Subtitles in user's preferred language selectable when video language differs | ⚠️ | logic downloads `en` + preferred language when the item has them and turns the preferred track on when film language differs; few public-domain items ship fr/es subtitles (no external subtitle provider configured) |
| V12 | Non-native formats (mkv) converted on the fly | 🔧 | bug #29 (AVI + MKV) |
| V13 | Video seekable (Range requests) | ✅ | Range 206 everywhere; mid-download seek works (bug #28) |
| V14 | Invalid watch URL (bad source/id) handled gracefully | 🔧 | bug #37 |

### A — RESTful API (subject III.4)
| ID | Requirement | Result | Notes |
|---|---|---|---|
| A1 | POST /oauth/token with client+secret returns a token | ✅ | form & JSON, bad secret 401, missing fields 400 |
| A2 | GET /users → list id + username (auth) | ✅ | id + username only |
| A3 | GET /users/:id → username + picture, email only for owner | ✅ | email only for owner; 404 unknown |
| A4 | PATCH /users/:id own profile OK; other user → 403 | ✅ | own 200, other 403, invalid picture URL / weak password 422 |
| A5 | GET /movies → front page movies (id + name), public | 🔧 | bug #41; public (no token) |
| A6 | GET /movies/:id → name, id, rating, year, length, subtitles, comment count | ✅ | name, id, rating, year, length, subtitles, comment_count (+ more); 404 unknown |
| A7 | GET /comments → latest comments (author username, date, content, id) | ✅ | latest comments with author username, date, content, id |
| A8 | GET /comments/:id → comment, author username, id, date | ✅ | comment, author, id, date |
| A9 | PATCH /comments/:id own only (403 otherwise) | ✅ | own 200, others 403 |
| A10 | DELETE /comments/:id own only (403 otherwise) | ✅ | own 204, others 403, then 404 |
| A11 | POST /comments and POST /movies/:id/comments | ✅ | both endpoints 201; empty 422; missing movie_id 400 |
| A12 | GET /movies/:id/comments | ✅ | |
| A13 | Unauthenticated access to protected routes → 401 | ✅ | all protected endpoints 401 without / with forged token |
| A14 | Unknown routes / wrong methods → proper 404 / 405 | 🔧 | 404 unknown (JSON, bug #42), 405 wrong method, debug route removed (bug #35) |
| A15 | Validation errors → 400/422, never 500 | ✅ | bad types → 422/404, never 500 |

---

## Console & server-log findings

Final sweep (fresh load of each page in an isolated frame, console `error`/`warn` hooked, failed resources collected):

| Page | Console errors/warnings | Failed requests |
|---|---|---|
| /login, /login?error=oauth_failed, /register, /forgot-password (logged out) | 0 | 0 |
| /home, /settings, /profile/:id, /forgot-password, /reset-password?token=… | 0 | 0 |
| /watch/archive/his_girl_friday, /watch/pdt/1074 (AVI, transcoded), /watch/foo/bar | 0 | 0 |

Only remaining console output is **Next.js dev-mode noise**: `[info] Download the React DevTools…` and `[log] [Fast Refresh] rebuilding` (see recommendations).

Server logs after fixes: no tracebacks/errors in normal use; only dev `WatchFiles … Reloading` warnings caused by editing files.

---

## Not verified / out of scope

* **42 & GitHub OAuth full round-trip** (needs real external accounts) – redirects, `state`, error handling verified only.
* **Reset email delivery** (real SMTP inbox) – token generation/reset flow verified with a DB-seeded token. ⚠️ One test request was sent through the configured Gmail SMTP to `qa1@example.com` before I noticed SMTP was live; a bounce notice may appear in that mailbox.
* **Firefox** – only Chromium available here.
* **Playback progression while the browser pane was hidden** – Chrome suspends media in hidden tabs; readiness/seek were verified via `readyState`, Range responses and decoded frame size instead.

## Recommendations / residual risks (not changed – your call)

1. **Run the defense on a production build** (`next build && next start`, `NODE_ENV=production`). `next dev` prints `Download the React DevTools` (info) and `[Fast Refresh]` (log) lines in the console – a strict evaluator may count them as "notices".
2. **Expected 4xx network lines**: a wrong password (401) or an already-taken username (400) makes Chrome print a red `Failed to load resource` line. Client-side validation now prevents nearly all other 4xx; the remaining ones are inherent to a RESTful API.
3. **PDT swarms are mostly dead** (3 of 4 popular titles had 0 seeders; UI now shows a "no seeders yet" notice after 90 s). For the defense, demo with archive.org titles (web-seeded, ~2 MB/s) or Nosferatu (PDT, seeded).
4. **Subtitles in fr/es** are rare in public-domain items; an external subtitle provider (e.g. OpenSubtitles API) would make V11 demonstrable.
5. The old copyrighted seed rows (Shawshank, Godfather, …) are still in your DB (just hidden from the API) – consider deleting them.
6. Home footer has 8 placeholder `href="#"` links (Browse all, Privacy, …) – remove or wire them.
7. Pin Python/JS dependency versions (bug #1 came from an unpinned `sqlalchemy`).

## Test data left in the DB

Local test accounts (created via the UI/API): `qa_user1b` / `Newpass456`, `qa_user2` / `Testpass123`, `qa_final` / `Final2026pass`. Test comments were deleted. Downloaded media in the `torrent_media` volume: His Girl Friday, Plan 9 from Outer Space (archive.org), Nosferatu (PDT).
