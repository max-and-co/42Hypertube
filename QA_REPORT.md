# Hypertube — QA Report, pass 2 (subject v7)

Tester: Claude (browser QA in the in-app Chromium browser + curl for the API)
Branch: `qa/subject-pass-2` (one commit per fixed bug)
Stack: `docker-compose down -v && docker-compose up --build` (fresh volumes) → http://localhost:8080
Previous report kept as `QA_REPORT.old.md`.

Legend: ✅ pass · ❌ fail · 🔧 failed → fixed → retested OK · ⚠️ partial / note · ⏭️ not testable here · ⏳ not run yet

Not testable here: Firefox (only Chromium in this environment).

## Summary

- **~150 checks** in 12 groups (general/eliminatory, registration, login, reset, OAuth, profile & language, library, video, comments, REST API, security, layout), driven through the real UI in the browser, plus curl for the API and security probes.
- **20 bug fixes (#1–#19 + #3b), each re-tested and committed** on `qa/subject-pass-2`. The ones that would cost the defence:
  - **Eliminatory, legality (#3/#3b)**: the front page showed pirated films (Sultan 2016 Blu-ray rip, My Little Pony 2017, anime fansub, Jackie Chan rips "CC BY 4.0").
  - **Mandatory, video (#8)**: PeerTube videos never downloaded.
  - **Mandatory, library (#6)**: search results were not sorted by name past the first page.
  - **Security (#13, #15)**: avatars only magic-byte checked (polyglots stored); reset tokens in plain text + timing enumeration.
  - **Console errors, eliminatory (#1, #10, #11, #12)**: 429, 404/422, 404, 413 reachable in normal use.
  - **Phones (#18)**: no logout button on the library at 375 px.
- Still pending, they need you: real reset e-mail (F2), 42 + GitHub logins (O3/O4/O7), watching frames play with the pane visible (V5 visual). See section 4.

---

## 1. Checklist

### G — General & eliminatory rules
| ID | Requirement | Result | Notes |
|---|---|---|---|
| G1 | Fresh `docker-compose up --build` on empty volumes starts every service with no error in the logs | ✅ | fresh volumes, all 5 containers up, no errors in logs (only pip-as-root build notice) |
| G2 | `.env` is git-ignored and no secret is in tracked files | ✅ | `.env` ignored; no real secret value found anywhere in `git log --all -p` |
| G3 | Every page has a header, a main section and a footer | 🔧 | #19: default Next 404 had none; every other page (login, register, forgot, reset, home, watch, settings, profile) has all three |
| G4 | 0 errors / 0 warnings in the browser console, on every page, logged in and out | 🔧 | #1 (429), #10 (ingest 404/422), #11 (profile 404), #12 (413): all fixed. Remaining by design: a typed unknown URL gets a real HTTP 404 document, which Chrome always logs |
| G5 | 0 failed network requests (4xx/5xx) during normal use of every page | 🔧 | same fixes as G4; normal use of every page: 0 failed requests |
| G6 | No server errors (tracebacks, 500) in container logs during the whole test | ✅ | no traceback / 5xx in user-service, torrent-service, nextjs; nginx entries are my rate-limit floods and restarts |
| G7 | Layout works at 375 px (phone): no horizontal scroll, everything usable | 🔧 | #18: logout hidden on phones, uneven poster grid, filter overflow. All pages now 375 px wide, no horizontal scroll |
| G8 | Layout works at 768 px (tablet) and on desktop | ✅ | 768 px: no overflow, 4–5 even columns; desktop OK |
| G9 | No forbidden streaming library (webtorrent, peerflix, pulsar…) | ✅ | libtorrent + own streaming code; no webtorrent/peerflix/pulsar |
| G10 | Sources are royalty-free / legally distributable only | 🔧 | #3: pirated films (Sultan 2016 Blu-ray rip, My Little Pony, anime fansub) on the front page |
| G11 | Library and video pages refuse logged-out visitors (redirect to login) | ✅ | /home, /watch/…, /settings, /users/2 → /login when logged out |
| G12 | Unknown frontend route shows a proper 404 page without console errors | 🔧 | #19: custom translated 404 with header/main/footer; status 404 |

### R — Registration
| ID | Requirement | Result | Notes |
|---|---|---|---|
| R1 | Form asks for email, username, first name, last name, password | ✅ |  |
| R2 | Valid registration succeeds and leads to login (or logs in) | ✅ | redirects to /login (no "account created" message — UX note) |
| R3 | Password is hashed in the DB (bcrypt), never plain text | ✅ | bcrypt `$2b$12$`, 60 chars |
| R4 | Weak password refused (short, no digit, no letter) with a readable message | ✅ | client + server |
| R5 | Invalid email refused | ✅ | `notanemail`, `a@b`, reserved domains refused |
| R6 | Empty / whitespace-only fields refused | ✅ | client + server (whitespace-only) |
| R7 | Username with HTML / spaces / too short / too long refused | ✅ | `<script>`, `ab`, `qa ada`, `<img src=x>` refused |
| R8 | Names with digits / HTML refused; accented and hyphenated names accepted | ✅ | `Ada2`, `<b>x</b>` refused; `Zoé Saint-Exupéry` accepted |
| R9 | Duplicate email refused, case-insensitively | ✅ | `qa_ada@EXAMPLE.com` → "Email already registered"; stored lower-case |
| R10 | Duplicate username refused, case-insensitively | ✅ | `QA_ADA` → "Username already taken" |
| R11 | Very long inputs (10 000 chars) refused without crash | ✅ | 10 000-char name → validation message, no crash; non-JSON / array bodies handled |
| R12 | Error messages are shown inline, no console error, no crash | ✅ | inline messages, 0 console errors |
| R13 | Already logged-in user visiting /register is sent to the library | ✅ | /register and /login → /home when logged in |

### L — Login / logout
| ID | Requirement | Result | Notes |
|---|---|---|---|
| L1 | Login with username + password works | ✅ |  |
| L2 | Login with email + password works (email case-insensitive) | ✅ | `QA_ADA@example.COM` works |
| L3 | Wrong password → generic error, no console error | ✅ | "Incorrect credentials" |
| L4 | Unknown user → same generic error (no account enumeration) | ✅ | identical message |
| L5 | Empty fields refused client side | ✅ | "Login failed", no request sent |
| L6 | SQL-injection strings in login fields do not log in and do not crash | ✅ | `' OR '1'='1`, `qa_ada'--`, `" OR 1=1;--` → refused, no error |
| L7 | Session cookie is HttpOnly, SameSite | ✅ | `HttpOnly; SameSite=lax; Max-Age=604800` |
| L8 | Session survives a page reload | ✅ |  |
| L9 | One-click logout available on every logged-in page (home, watch, settings, profile) | 🔧 | home, watch, settings, profile: one click → /login. On phones the home logout was hidden (#18) |
| L10 | After logout, library / watch / settings redirect to login; back button doesn't show private data | ✅ | private pages redirect; Back shows the login page. Note: JWT is stateless, a copied token stays valid until expiry |
| L11 | Login brute force is rate-limited (429) and the UI shows a readable message | 🔧 | #1: raw 429 → console error + "Request failed" |

### F — Forgot / reset password
| ID | Requirement | Result | Notes |
|---|---|---|---|
| F1 | "Forgot password" link reachable from login | ✅ | "Forgot passphrase?" link on login |
| F2 | Submitting a registered email sends a reset email (real inbox) | ⏳ | needs your inbox — see section 4 |
| F3 | Same answer and same timing for unknown email (no enumeration) | 🔧 | #15: SMTP ran inside the request (timing leak); unknown e-mail now 3 ms |
| F4 | Reset link opens the reset form; new password must be strong; confirmation must match | ✅ | mismatch / weak password refused (translated); seeded token → "password changed" → redirect |
| F5 | After reset, old password fails and new password works | ✅ | old password refused, new one works |
| F6 | Reset token is single-use and expires | ✅ | reused token → "invalid or expired"; expired token → "Reset token has expired"; DB token cleared |
| F7 | Reset token is not stored in plain text in the DB | 🔧 | #15: token stored in plain text → now sha256 |
| F8 | Invalid / missing token shows a readable error, no crash | ✅ | no token / wrong token → readable translated message |

### O — OAuth (42 + another)
| ID | Requirement | Result | Notes |
|---|---|---|---|
| O1 | "Sign in with 42" button redirects to intra with client_id, redirect_uri, state | ✅ | 307 to api.intra.42.fr with client_id, encoded redirect_uri, response_type=code, random state + HttpOnly 10-min cookie |
| O2 | "Sign in with GitHub" button redirects to GitHub with client_id, redirect_uri, state | ✅ | same for GitHub (scope user:email) |
| O3 | Full 42 login creates an account and lands in the library | ⏳ | needs your 42 login — see section 4 |
| O4 | Full GitHub login creates an account and lands in the library | ⏳ | needs your GitHub login — see section 4 |
| O5 | Callback with missing / forged state → back to login with readable error | ✅ | missing / forged state, bogus code → /login?error=oauth_failed with translated message |
| O6 | Callback with `error=access_denied` → back to login with readable error | ✅ | ?error=access_denied → same |
| O7 | OAuth user can use the site normally (settings, comments); password change handled sensibly | ⏳ | after O3/O4 |

### P — Profile, settings, language
| ID | Requirement | Result | Notes |
|---|---|---|---|
| P1 | Settings shows current username, email, first/last name, language, picture | ✅ |  |
| P2 | Edit first/last name, username → saved, persists after reload | ✅ | name/username saved and kept after reload |
| P3 | Edit email → saved; duplicate email refused; invalid email refused | ✅ | `Ada.L@Example.com` saved lower-case; duplicate (any case) and invalid refused |
| P4 | Duplicate username refused (case-insensitive) | ✅ | `QA_Bob` → taken |
| P5 | Upload PNG / JPEG avatar → shown in settings and header | ✅ | PNG/JPEG/GIF/WebP; shown in settings and header |
| P6 | Upload non-image (txt renamed .png, HTML, SVG) refused | 🔧 | #13: `\x89PNG`+text and PNG+HTML were stored; now Pillow-verified and re-encoded. txt-as-png, HTML, SVG refused |
| P7 | Upload too-big image refused with readable message, no console error | 🔧 | #12: 1.99 MB → raw nginx 413. >2 MB refused client-side, no request |
| P8 | Uploaded avatar served with an image MIME type and nosniff | ✅ | `image/png` / `image/jpeg` + nosniff; served only by extension we chose |
| P9 | Preferred language defaults to English for a new user | ✅ | new account `en` |
| P10 | Changing language translates the whole UI (home, watch, settings, auth pages) | 🔧 | #14: all form/server errors stayed English. Labels on every page were already translated |
| P11 | Language choice persists across reload and logout/login | ✅ | header choice saved to profile (DB), survives reload and logout/login |
| P12 | Change password: wrong current password refused, weak new refused, valid works | ⚠️ | no change-password form in the UI (API route exists); not required by the subject (reset by e-mail is) |
| P13 | User search finds other members; `%` / `_` treated literally | ✅ | case-insensitive; `__`, `%%`, `<script>` → "No members found" |
| P14 | Other user's profile shows picture, username, names — never the email | ✅ | picture, names, username, language; never the e-mail |
| P15 | Comment author link opens that user's profile | ✅ | author link → /users/:id |
| P16 | Unknown / invalid user id shows "not found" without console error | 🔧 | #11: /users/9999 logged a 404; /users/abc OK |
| P17 | HTML in names / comments is rendered as text, never executed | ✅ | names/usernames refuse HTML; comment `<img onerror>`/`<script>` rendered as text, no alert |

### B — Library: search & thumbnails
| ID | Requirement | Result | Notes |
|---|---|---|---|
| B1 | Library only reachable when logged in | ✅ |  |
| B2 | Has a search field and a list of thumbnails | ✅ |  |
| B3 | No search: shows the most popular videos, sorted by a stated criterion | ✅ | popularity = archive.org downloads interleaved with PeerTube views |
| B4 | Search queries at least two external sources at once | ✅ | archive.org + PeerTube (3 trusted instances) on every search |
| B5 | Search results sorted by name | 🔧 | #6: order restarted at every scroll page; now merged with a cursor (5 pages, 0 breaks) |
| B6 | Each thumbnail shows name, year (if available), IMDb rating (if available), cover image | ✅ | title, year, IMDb (OMDb/TMDb) or N/A, cover via same-origin proxy |
| B7 | Watched vs unwatched clearly distinguishable | ✅ | "WATCHED" rule + poster at 45 % opacity; toggle persists |
| B8 | Watching a film marks it watched in the library | ✅ | opening a film marks it watched (His Girl Friday) |
| B9 | Infinite scroll loads the next page asynchronously; no "next page" link | ✅ | IntersectionObserver, 11 pages loaded, no link/button |
| B10 | Infinite scroll stops cleanly at the end, no duplicates | 🔧 | #4: same film twice (two archive uploads); deduped |
| B11 | Sort by name / year / IMDb / popularity, both directions, works | ✅ | name/year/IMDb/popularity × asc/desc |
| B12 | Filter by genre works | 🔧 | #5: Horror gave 2 films per request; now in the archive query (3 575) |
| B13 | Filter by year range works; invalid years refused with message | ✅ | 1930–1940 correct; `abc`, 1950>1940 refused with message, 0 requests |
| B14 | Filter by minimum IMDb grade works; invalid grade refused | ✅ | ≥7 correct; `11`, `7.55` refused, 0 requests |
| B15 | Source filter (all / archive / peertube) works | ✅ |  |
| B16 | Search with no results shows a clean "no results" message | ✅ | "No results match your criteria." |
| B17 | Special characters in search (`<script>`, `%`, `'`, emoji) don't break anything | ✅ | `<img onerror>`, `' OR 1=1 --`, `%_%` harmless |
| B18 | Broken / missing posters fall back cleanly (no broken-image icon, no console error) | ✅ | dead posters → transparent pixel from the proxy, never a console error |
| B19 | Rapid filter / search changes never show stale results | ✅ | request-id guard in fetchMovies (code review); no stale grid seen |
| B20 | Reset filters works | ✅ |  |

### V — Video page
| ID | Requirement | Result | Notes |
|---|---|---|---|
| V1 | Only reachable when logged in | ✅ |  |
| V2 | Shows summary, cast, director, producer, year, length, IMDb grade, cover | ✅ | summary, director, producer, cast, year, length, IMDb, genres, cover, subtitles |
| V3 | Player present; download starts on the server when the page opens | 🔧 | #8: PeerTube never downloaded (magnet, no metadata). archive.org OK |
| V4 | Playback starts before the download is complete (streaming while downloading) | ✅ | player at 13 % downloaded (575 MB film); 206 ranges; PeerTube 257 MB talk ready in ~4 s |
| V5 | Seeking works (inside and ahead of downloaded part) | ✅ | seek to 1:00:00 at 39 % → readyState 4 in 3.5 s. Actual frame playback: ⏳ needs the pane visible (section 4) |
| V6 | Downloading is non-blocking: rest of the site stays responsive | ✅ | API latency < 10 ms during two downloads |
| V7 | Finished film is kept on the server; reopening plays instantly without re-downloading | ✅ | `.complete.json` marker; after restart the film is "complete" at once, no torrent |
| V8 | Films unwatched for a month are deleted (retention job exists and is correct) | ✅ | `last_watched_at` 40 days → folder erased + DB reset; 5 days → kept; reopening re-downloads. Runs 60 s after start, then every 6 h |
| V9 | English subtitles downloaded and selectable when available | 🔧 | #7: archive `.asr.srt` labelled "Unknown"; now "English (auto)", 1 286 cues load |
| V10 | Preferred-language subtitles when film language differs | ✅ | pref. `es`, English film → Español (default, showing) + English (PeerTube captions) |
| V11 | Non-native formats (mkv…) converted on the fly | ✅ | no in-scope source ships MKV-only (archive always derives MP4), so `_convert_live` was run in the container on a real MKV: fMP4 while converting, then H.264/AAC faststart MP4 + marker |
| V12 | Invalid source / id in URL shows a clean error | 🔧 | #10: messages fine, but 404/422 in the console |
| V13 | Stream errors show a readable message and a retry | ✅ | session error shows message + Retry (PeerTube failure before #8) |
| V14 | No console errors/warnings during load, playback, seek, leaving the page | ✅ | 0 console entries on watch pages (archive + PeerTube) |

### C — Comments
| ID | Requirement | Result | Notes |
|---|---|---|---|
| C1 | Logged-in user can post a comment; it appears in the list | ✅ |  |
| C2 | Previous comments are listed with author and date | ✅ | newest first, author link, localised date |
| C3 | Empty / whitespace comment refused | ✅ | button disabled + message |
| C4 | Over-long comment refused (1000 chars max) | ✅ | client and API (422) |
| C5 | HTML / script in a comment shown as text | ✅ |  |
| C6 | Comment count on the movie updates | ✅ | comment_count 3 in GET /movies/1 |

### API — RESTful API (OAuth2)
| ID | Requirement | Result | Notes |
|---|---|---|---|
| A1 | `POST /api/oauth/token` with client + secret returns a bearer token; wrong creds → 401 | ✅ | form + JSON; 401 wrong secret; 400 missing/malformed |
| A2 | `GET /api/users` (auth) → list of id + username; no token → 401 | ✅ | id + username; 401 without/with bad token |
| A3 | `GET /api/users/:id` → username, email, picture URL; unknown → 404 | ✅ | username, email, profile_picture; 404 unknown |
| A4 | `PATCH /api/users/:id` → username, email, password, picture URL; validated | ✅ | anyone: username/picture; e-mail/password owner only (403); 409 duplicate; 422 `javascript:`/`http:` picture, `<script>` username |
| A5 | `GET /api/movies` (public) → front-page movies with id + name | ✅ | public, id + name |
| A6 | `GET /api/movies/:id` → name, id, IMDb, year, length, subtitles, comment count | ✅ | name, id, IMDb, year, length, available_subtitles, comment_count (+cast, cover…) |
| A7 | `GET /api/comments` → latest comments with author username, date, content, id | 🔧 | #16: field was `content` only; now `comment` too |
| A8 | `GET /api/comments/:id` → comment, author username, id, date | 🔧 | #16 |
| A9 | `PATCH /api/comments/:id` (author only) | ✅ | 403 other author, 200 own |
| A10 | `DELETE /api/comments/:id` (author only) | ✅ | 403 other, 204 own, then 404 |
| A11 | `POST /api/comments` and `POST /api/movies/:id/comments` | ✅ | 201; 400 no movie_id; 404 unknown movie; 422 blank |
| A12 | `GET /api/movies/:id/comments` | ✅ | 401 anonymous |
| A13 | Any other API call → appropriate HTTP code (404 / 405) | 🔧 | #17: /api/torrent/search & /details were open; now 404. /admin, /docs, /openapi.json → 404 |
| A14 | Wrong methods return 405, bad payloads 400/422, JSON everywhere | ✅ | DELETE /movies/1, PUT /users/1, POST /movies → 405; JSON everywhere |

### S — Security
| ID | Requirement | Result | Notes |
|---|---|---|---|
| S1 | No plain-text password or reset token in DB | 🔧 | passwords bcrypt; reset token plain text → #15 |
| S2 | SQL injection attempts in every input (login, search, user search, filters, ids) have no effect | ✅ | login, register, user search, discover, ids: parameterised (SQLAlchemy); DB intact |
| S3 | Stored XSS impossible (names, username, comments, avatars) | ✅ | validated names/usernames, React escaping, avatars re-encoded (#13) |
| S4 | Upload accepts only real images | 🔧 | #13 |
| S5 | Private endpoints refuse anonymous calls | ✅ | every private route 401 anonymous |
| S6 | Thumbnail proxy refuses internal / non-image URLs (no SSRF) | ✅ | user-service, 127.0.0.1, 169.254.169.254, [::1], db, file://, non-image → same 1×1 pixel; real posters proxied |
| S7 | Path traversal on avatars / subtitles / stream refused | ✅ | avatars/subtitles/stream traversal → 404 |
| S8 | Security headers present (nosniff, frame-options) | ✅ | nosniff, X-Frame-Options DENY, Referrer-Policy, server_tokens off |

---

## 2. Bug log (bug → fix → retest)

| # | Req | Bug | Fix | Commit | Retest |
|---|---|---|---|---|---|
| 1 | L11, G4 | After ~10 form posts/min from one IP (login, register, forgot, reset share one nginx zone) nginx answers a raw **429** → red console error (eliminatory) and the form only says "Request failed" | nginx `error_page 429 = @form_rate_limited` on the 4 browser-form routes → 200 `{"ok":false,"detail":"Too many attempts. Please wait a minute and try again."}` (same convention as every other form refusal). `/api/oauth/token` (REST API) keeps a real 429 | `1751b56` | 🔧 14 rapid posts from the page: all 200, message shown inline, no new console entry; token endpoint still 429 |
| 2 | L1 | Usernames are unique case-insensitively, but login (and `/oauth/token`) compared usernames case-sensitively → `QA_ADA` could not log in as `qa_ada` | `func.lower()` on both sides in `routers/auth.py` login and `routers/oauth.py` token | `b9a8cc8` | 🔧 `QA_ADA` login OK, `Qa_Bob` token OK, wrong password still refused |
| 3 | G10 (**eliminatory**) | Front page showed pirated, copyrighted films: **"Sultan (2016) 1080p Blu Ray [HDmi Zone]"** (archive.org community upload), **"My Little Pony 2017 Movie"** (pony.tube), an Ojamajo Doremi **fansub**. archive.org query matched any `mediatype:movies` upload; PeerTube relied on uploader-declared licences, which are faked (pony.tube marks MLP films "Public Domain Dedication"). Even archive `feature_films` contains Jackie Chan rips labelled "CC BY 4.0" | archive.org: `collection:feature_films AND licenseurl:*publicdomain*` (7 669 PD films), also checked in `fetch_details` so the film page / stream refuse other items. PeerTube: only `PEERTUBE_TRUSTED_HOSTS` (Blender, Debian, Framasoft), one SepiaSearch query per host, host enforced in `validate_external_id` (ingest + stream). Stale `external_movie_cache` rows cleared | `161a224` | 🔧 browse: PD classics + Blender/Debian/Framasoft only; "sultan"/"supercop"/"pony"/"doremi" → no rips; ingest of the Sultan rip → 404, pony.tube session → 422 |
| 3b | G10 | Sorting by year still showed copyrighted rips with a "public domain" mark (Haider 2014, Lady Vengeance 2005, 1080p kung-fu re-uploads from 2025) | archive.org scope also requires `year:[1870 TO 1977]` and `publicdate` before 2020 (2 097 PD classics); enforced in `fetch_details` | `fc6528a` | 🔧 year-desc tops out at 1977 classics; Haider rip ingest → refused |
| 4 | B10 | Same film twice in the grid ("Sex Madness", "Night of the Living Dead": separate archive uploads) | grid dedupes by source id **and** title+year | `08468cb` | 🔧 119 cards / 5 pages, 0 duplicates |
| 5 | B12 | Genre/year filtered each fetched 12-item page afterwards → "Horror" 2 films per request, 23 requests for 31 films | `subject:"…"` and `year:[a TO b]` inside the archive.org query (post-filter kept as safety net) | `d8cb93a` | 🔧 Horror: 12 per page, 3 575 total; Horror 1930–39 correct |
| 6 | **B5 – mandatory** | Search results not sorted by name across pages: page 1 ended at "The Java Packaging Nightmare", page 2 restarted at "Back-Room Boy" (each page = page N of every source glued together) | name/year sorts merged server-side across streams (archive.org + each PeerTube instance) with a cursor of per-stream offsets; archive sorts on `titleSorter`/`year` to match the merge key; empty batch ends a stream (no infinite loop) | `aa7eda3` | 🔧 API: 5 pages / 120 titles, 0 order breaks, 0 dups; UI: 92 cards, 0 breaks |
| 7 | V9, A6 | archive `his_girl_friday.asr.srt` published as "Unknown" (`und`): not treated as English, `available_subtitles` empty in the API; once converted, `.srt` and `.vtt` both listed (two identical `<track>`s) | auto captions labelled with the film's language ("English (auto)"); tracks deduped by file | `1c7661e` | 🔧 1 track, `en`, 1 286 cues; `GET /movies/1` → `available_subtitles: ["en"]` |
| 8 | **V3 – mandatory** | **PeerTube videos never played**: "No peer or webseed sent the torrent metadata within 90s" (magnet; peers are WebTorrent/WebRTC, unreachable by libtorrent). Pre-v6 torrents also point at a 404 webseed | use the file's published `.torrent` (same host, 4 MB cap) + API `fileUrl` as extra webseed | `d724c01` | 🔧 framatube 1080p and a 257 MB Debian talk download via BitTorrent and play |
| 9 | V2 | 1 min 54 s PeerTube video shown as "1 min" | round to nearest minute | `2551bc3` | 🔧 "2 min" |
| 10 | G4, V12 | Unknown / refused / malformed film link: page OK but **404/422 in the console** | ingest answers 200 `{ok:false}` like other browser forms | `0771c65` | 🔧 3 bad links, 0 console entries; valid film still 201 |
| 11 | G4, P16 | `/users/9999` → console 404 | browser-only `/api/users/profile/:id` → 200 `{ok:false}` (REST `/api/users/:id` keeps 404) | `1fc47cd` | 🔧 0 console entries |
| 12 | G4, P7 | 1.99 MB picture accepted by client but nginx `client_max_body_size 2m` → raw **413** in console, "Upload failed" | nginx 3m (app still caps 2 MB) | `76843ec` | 🔧 near-limit upload OK |
| 13 | **P6 / security** | Avatar check = magic bytes only: `\x89PNG`+text stored (broken image), PNG+HTML polyglot stored byte-for-byte; old files never deleted | Pillow verify + re-encode (JPEG→JPEG, others→PNG), 4096 px cap, bomb guard; old upload deleted unless still referenced | `11b8d63` | 🔧 garbage & 5000 px refused; jpg/png/gif/webp OK; no payload left in stored files |
| 14 | P10 | In FR/ES, every validation and server message stayed English | `lib/messages.ts` maps all known messages → translated keys (en/fr/es); `<html lang>` follows UI | `733472d` | 🔧 FR: "Ce nom d'utilisateur est déjà pris", "Le commentaire ne peut pas dépasser 1000 caractères"… |
| 15 | **F3/F7 – security** | Reset token stored in **plain text**; SMTP send inside the request → registered e-mail seconds slower (enumeration) | store/compare `sha256(token)`; send in `BackgroundTasks` | `f62b94d` | 🔧 seeded hashed token flow OK; unknown e-mail 3 ms |
| 16 | A7/A8 | Comment responses only had `content`; subject API names it `comment` (and POST/PATCH take `comment`) | both fields returned | `b75b171` | 🔧 |
| 17 | A13 | `/api/torrent/search` and `/details` usable by any logged-in user (internal only) | nginx → 404 | `1ed970d` | 🔧 search/details 404; sessions/health/discover OK |
| 18 | G7, L9 | Phone (375 px): **no logout button** on the library, posters in 140/240 px columns, filter selects overflowing | logout kept visible; `minmax(0,1fr)` columns, `min-width:0` fields | `10a0ed8` | 🔧 cards 160/160, no overflow at 375 and 768 px |
| 19 | G3, G12 | Unknown URL → bare Next 404: no header/main/footer, English only | `app/not-found.tsx` with site header/footer, translated; status stays 404 | `664169c` | 🔧 |

---

## 3. Console log (warnings/errors seen, per page)

| Page | Console before fixes | Console after |
|---|---|---|
| /login, /register, /forgot-password, /reset-password | 429 after ~10 posts (#1) | 0 |
| /home (scroll 11 pages, filters, search, watched toggle) | 0 | 0 |
| /watch (archive + PeerTube, play/seek, subtitles, comments) | 0 | 0 |
| /watch with unknown / refused / malformed id | 404 / 422 (#10) | 0 |
| /settings (profile, avatar, member search) | 413 on 1.99 MB avatar (#12) | 0 |
| /users/:id unknown | 404 (#11) | 0 |
| unknown URL | bare 404 document (#19) | Chrome's own line for an HTTP-404 document (correct status, see notes) |

---

## 4. Steps that need you (pending)

- **F2** — real reset e-mail: request a reset for an account with your own address, open the link, set a new password.
- **O3 / O4 / O7** — log in with 42 and with GitHub in the browser pane; then check settings + a comment as that user.
- **V5 (visual)** — with the browser pane visible, confirm frames actually play and English subtitles show on His Girl Friday.

## 5. Notes

- **Untracked leftovers** (not in git, so not in a fresh clone, but copied into the local Docker build): `frontend/app/profile/[id]/page.tsx` (duplicate of `users/[id]`, still uses the old 404 lookup), `frontend/app/lib/session.ts`, `torrent-service/services/torrent_engine.py`, `frontend/.claude-launch-tmp`. Nothing tracked imports them; delete them or commit them on purpose.
- **Catalogue scope (#3)**: archive.org = `feature_films` + public-domain licence + produced ≤ 1977 + uploaded before 2020; PeerTube = `PEERTUBE_TRUSTED_HOSTS` (Blender, Debian, Framasoft). Legal-first trade-off: fewer, safer titles. Adjust in `torrent-service/config.py` / `.env`.
- **MKV (V11)**: conversion code works but no in-scope source ever selects an MKV (MP4 derivative always exists). For a defence demo you may want a way to force the original file.
- **404 console line**: a typed unknown URL returns a real 404 document; Chrome prints that. Turning it into a 200 would be a "soft 404" — left as is.
- **Sessions**: JWTs are stateless — logout and password reset don't revoke a token already issued (7-day expiry).
- Each download opens its own libtorrent session (`_download`); fine for a few users, a shared session would scale better.
- `JWT_SECRET_KEY` in `.env` is still the placeholder; fine locally, change it for any shared deployment.
- Usernames are shown upper-cased by CSS (`@QA_ADA` for `qa_ada`) — purely visual.
