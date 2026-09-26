import asyncio
import base64
import ipaddress
import logging
import os
import socket
import time
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy import select, func, tuple_, cast, Float as SAFloat
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user_id, get_db, create_service_token
from models import Movie, Comment, ExternalMovieCache, MovieWatchState, User
from ratings import normalize_title, rating_of, ratings_for
from schemas import CommentCreate, WatchToggleRequest, ExternalMovieIngestRequest

router = APIRouter()
logger = logging.getLogger(__name__)

TORRENT_SERVICE_URL = os.getenv("TORRENT_SERVICE_URL", "http://torrent-service:8001")
OMDB_API_KEY = os.getenv("OMDB_API_KEY", "").strip()
OMDB_BASE_URL = "https://www.omdbapi.com/"
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()
TMDB_BASE_URL = "https://api.themoviedb.org/3"

# Sources must stay in sync with torrent-service/config.py. Both are
# royalty-free / legally distributable, as the subject requires. "all" queries
# both at once (subject III.2.1: the search engine queries at least two sources).
SUPPORTED_SOURCES = {"archive", "peertube"}
SearchSource = Literal["all", "archive", "peertube"]
SortBy = Literal["downloads", "title", "year", "imdb_rating"]
SortDir = Literal["asc", "desc"]

FRONT_PAGE_SIZE = 24
FRONT_PAGE_TTL_SECONDS = 600
_front_page_cache: dict[str, object] = {"at": 0.0, "items": []}

# ── Thumbnail proxy ───────────────────────────────────────────────────────────
# Posters live on archive.org and on arbitrary federated PeerTube instances.
# Letting the browser load them directly sets third-party cookies (DDoS-Guard
# sends __ddg*) and trips Firefox's OpaqueResponseBlocking when a host answers
# an <img> with an HTML challenge page. Fetching them here keeps every request
# same-origin and lets us reject anything that is not actually an image.

MAX_THUMBNAIL_BYTES = 5 * 1024 * 1024
MAX_THUMBNAIL_REDIRECTS = 3
ALLOWED_THUMBNAIL_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/avif"}

# A poster that cannot be fetched degrades to a transparent pixel rather than
# a 404. A failed <img> logs "Failed to load resource" in Chrome, and the
# subject forbids any console error.
_TRANSPARENT_PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _placeholder_image() -> Response:
    return Response(
        content=_TRANSPARENT_PIXEL,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )


async def _is_publicly_routable(hostname: str) -> bool:
    """Reject anything resolving to a private, loopback or link-local address.

    The URL originates from a third-party search result, so without this the
    endpoint would be an SSRF gateway into the compose network.
    """
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(hostname, None)
    except (socket.gaierror, UnicodeError):
        return False

    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            return False
    return bool(infos)


async def _validate_thumbnail_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Only https image URLs are allowed")
    if not await _is_publicly_routable(parsed.hostname):
        raise HTTPException(status_code=400, detail="Host is not publicly routable")
    return url


@router.get("/movies/thumbnail")
async def proxy_thumbnail(request: Request, url: str = Query(..., max_length=2048)):
    """Same-origin passthrough for remote poster images."""
    get_current_user_id(request)

    try:
        target = await _validate_thumbnail_url(url)
    except HTTPException:
        return _placeholder_image()

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        for _ in range(MAX_THUMBNAIL_REDIRECTS + 1):
            try:
                request_ctx = client.stream("GET", target, headers={"Accept": "image/*"})
                response = await request_ctx.__aenter__()
            except httpx.HTTPError:
                return _placeholder_image()

            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                await request_ctx.__aexit__(None, None, None)
                if not location:
                    return _placeholder_image()
                # Re-validate every hop: a redirect must not land on an internal host.
                try:
                    target = await _validate_thumbnail_url(str(response.url.join(location)))
                except HTTPException:
                    return _placeholder_image()
                continue
            break
        else:
            return _placeholder_image()

        try:
            media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if response.status_code != 200 or media_type not in ALLOWED_THUMBNAIL_TYPES:
                return _placeholder_image()
            # Read at most the size limit: a huge "image" is never held in memory.
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_THUMBNAIL_BYTES:
                    return _placeholder_image()
        except httpx.HTTPError:
            return _placeholder_image()
        finally:
            await request_ctx.__aexit__(None, None, None)

    return Response(
        content=bytes(body),
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"},
    )


# ── Small helpers ─────────────────────────────────────────────────────────────


def _as_int(value: object) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_genres(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return []


def _to_csv(values: list[str] | None) -> str | None:
    if not values:
        return None
    normalized = [v.strip() for v in values if isinstance(v, str) and v.strip()]
    if not normalized:
        return None
    return ",".join(normalized)


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def _parse_runtime_minutes(runtime: str | None) -> int | None:
    if not runtime:
        return None
    text = runtime.strip().lower()
    if not text:
        return None
    first = text.split(" ")[0]
    return _as_int(first)


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _str_list(value: object) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _auth_headers(request: Request | None) -> dict[str, str]:
    """Forward the caller's identity to torrent-service, or use a service token
    for public endpoints called without one (the front page)."""
    if request is not None:
        token = request.cookies.get("access_token")
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            return {"Authorization": header}
        if token:
            return {"Authorization": f"Bearer {token}"}
    return {"Authorization": f"Bearer {create_service_token()}"}


# ── Metadata enrichment (details page) ────────────────────────────────────────


async def _fetch_omdb_details(imdb_id: str | None, title: str | None, year: int | None) -> dict[str, object]:
    if not OMDB_API_KEY:
        return {}
    params: dict[str, str] = {"apikey": OMDB_API_KEY, "r": "json"}
    if imdb_id:
        params["i"] = imdb_id
    elif title:
        params["t"] = title
        params["type"] = "movie"
        if year:
            params["y"] = str(year)
    else:
        return {}

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(OMDB_BASE_URL, params=params)
            response.raise_for_status()
            payload = response.json()
            if payload.get("Response") != "True":
                return {}
            return {
                "imdb_id": payload.get("imdbID"),
                "imdb_rating": _as_float(payload.get("imdbRating")),
                "description": payload.get("Plot") if payload.get("Plot") != "N/A" else None,
                "duration_minutes": _parse_runtime_minutes(payload.get("Runtime")),
                "producer": payload.get("Production") if payload.get("Production") not in (None, "N/A") else None,
                "director": payload.get("Director") if payload.get("Director") != "N/A" else None,
                "main_cast": [c.strip() for c in str(payload.get("Actors") or "").split(",") if c.strip() and c.strip() != "N/A"],
                "cover_image": payload.get("Poster") if payload.get("Poster") not in (None, "N/A") else None,
                "genres": [g.strip() for g in str(payload.get("Genre") or "").split(",") if g.strip() and g.strip() != "N/A"],
                "year": _as_int(payload.get("Year")),
                "original_language": payload.get("Language") if payload.get("Language") != "N/A" else None,
            }
    except Exception:
        return {}


async def _fetch_tmdb_details(imdb_id: str | None, title: str | None, year: int | None) -> dict[str, object]:
    if not TMDB_API_KEY:
        return {}

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            tmdb_movie = None
            if imdb_id:
                find_resp = await client.get(
                    f"{TMDB_BASE_URL}/find/{imdb_id}",
                    params={"api_key": TMDB_API_KEY, "external_source": "imdb_id"},
                )
                find_resp.raise_for_status()
                find_payload = find_resp.json()
                results = find_payload.get("movie_results") if isinstance(find_payload, dict) else []
                if isinstance(results, list) and results:
                    tmdb_movie = results[0]

            if tmdb_movie is None and title:
                search_params = {"api_key": TMDB_API_KEY, "query": title}
                if year:
                    search_params["year"] = str(year)
                search_resp = await client.get(f"{TMDB_BASE_URL}/search/movie", params=search_params)
                search_resp.raise_for_status()
                search_payload = search_resp.json()
                results = search_payload.get("results") if isinstance(search_payload, dict) else []
                # Exact title only: a fuzzy first hit would attach the wrong film's cast.
                for candidate in results if isinstance(results, list) else []:
                    names = {str(candidate.get("title") or "").lower(), str(candidate.get("original_title") or "").lower()}
                    if title.lower() in names:
                        tmdb_movie = candidate
                        break

            if not tmdb_movie:
                return {}

            tmdb_id = _as_int(tmdb_movie.get("id"))
            if not tmdb_id:
                return {}

            details_resp = await client.get(f"{TMDB_BASE_URL}/movie/{tmdb_id}", params={"api_key": TMDB_API_KEY})
            details_resp.raise_for_status()
            details = details_resp.json()

            credits_resp = await client.get(f"{TMDB_BASE_URL}/movie/{tmdb_id}/credits", params={"api_key": TMDB_API_KEY})
            credits_resp.raise_for_status()
            credits = credits_resp.json()

            crew = credits.get("crew") if isinstance(credits, dict) else []
            cast = credits.get("cast") if isinstance(credits, dict) else []
            director = None
            producer = None
            if isinstance(crew, list):
                for item in crew:
                    if not isinstance(item, dict):
                        continue
                    job = str(item.get("job") or "")
                    if not director and job.lower() == "director":
                        director = item.get("name")
                    if not producer and job.lower() == "producer":
                        producer = item.get("name")

            main_cast: list[str] = []
            if isinstance(cast, list):
                main_cast = [str(item.get("name") or "").strip() for item in cast[:8] if str(item.get("name") or "").strip()]

            genres = details.get("genres") if isinstance(details, dict) else []
            genre_names = [str(g.get("name") or "").strip() for g in genres if isinstance(g, dict) and str(g.get("name") or "").strip()]

            poster_path = details.get("poster_path") if isinstance(details, dict) else None
            cover_image = f"https://image.tmdb.org/t/p/w780{poster_path}" if poster_path else None

            return {
                "tmdb_id": str(tmdb_id),
                "imdb_rating_fallback": _as_float(details.get("vote_average")) if isinstance(details, dict) else None,
                "description": details.get("overview") if isinstance(details, dict) else None,
                "duration_minutes": _as_int(details.get("runtime") if isinstance(details, dict) else None),
                "producer": producer,
                "director": director,
                "main_cast": main_cast,
                "cover_image": cover_image,
                "genres": genre_names,
                "original_language": details.get("original_language") if isinstance(details, dict) else None,
            }
    except Exception:
        return {}


# ── Discover (library search) ─────────────────────────────────────────────────


def _cache_sort_clause(sort_by: str, sort_dir: str):
    desc = sort_dir.lower() != "asc"
    if sort_by == "title":
        col = ExternalMovieCache.title
    elif sort_by == "year":
        col = ExternalMovieCache.year
    elif sort_by == "imdb_rating":
        col = ExternalMovieCache.imdb_rating
    else:
        col = ExternalMovieCache.downloads
    return col.desc().nulls_last() if desc else col.asc().nulls_last()


async def _watched_pairs(db: AsyncSession, user_id: int, pairs: list[tuple[str, str]]) -> set[tuple[str, str]]:
    if not pairs:
        return set()
    result = await db.execute(
        select(MovieWatchState.source, MovieWatchState.external_id)
        .where(MovieWatchState.user_id == user_id)
        .where(tuple_(MovieWatchState.source, MovieWatchState.external_id).in_(pairs))
        .where(MovieWatchState.watched.is_(True))
    )
    return set(result.all())


async def _fallback_discover_results(
    db: AsyncSession,
    user_id: int,
    q: str,
    page: int,
    limit: int,
    source: str,
    sort_by: str,
    sort_dir: str,
    genre: str | None,
    year_min: int | None,
    year_max: int | None,
    imdb_min: float | None,
) -> tuple[list[dict[str, object]], int, bool]:
    """Serve the last known results from the cache when every provider is down."""
    cache_query = select(ExternalMovieCache)
    if source in SUPPORTED_SOURCES:
        cache_query = cache_query.where(ExternalMovieCache.source == source)
    if q.strip():
        cache_query = cache_query.where(ExternalMovieCache.title.ilike(f"%{q.strip()}%"))
    if genre:
        cache_query = cache_query.where(ExternalMovieCache.genres.ilike(f"%{genre.strip()}%"))
    if year_min is not None:
        cache_query = cache_query.where(ExternalMovieCache.year >= year_min)
    if year_max is not None:
        cache_query = cache_query.where(ExternalMovieCache.year <= year_max)
    if imdb_min is not None:
        cache_query = cache_query.where(ExternalMovieCache.imdb_rating >= imdb_min)

    total = (await db.execute(select(func.count()).select_from(cache_query.subquery()))).scalar() or 0
    rows = (
        await db.execute(
            cache_query.order_by(_cache_sort_clause(sort_by, sort_dir)).offset((page - 1) * limit).limit(limit)
        )
    ).scalars().all()

    watched = await _watched_pairs(db, user_id, [(r.source, r.external_id) for r in rows])
    results = [
        {
            "id": row.external_id,
            "source": row.source,
            "title": row.title,
            "year": row.year,
            "imdb_id": row.imdb_id,
            "imdb_rating": row.imdb_rating,
            "thumbnail": row.thumbnail,
            "genres": _normalize_genres(row.genres),
            "downloads": row.downloads,
            "watched": (row.source, row.external_id) in watched,
        }
        for row in rows
    ]
    return results, int(total), page * limit < int(total)


@router.get("/movies/discover")
async def discover_movies(
    request: Request,
    q: str = Query("", max_length=100),
    page: int = Query(1, ge=1, le=500),
    limit: int = Query(24, ge=1, le=50),
    source: SearchSource = "all",
    sort_by: SortBy = "downloads",
    sort_dir: SortDir = "desc",
    genre: str | None = Query(None, max_length=50),
    year_min: int | None = Query(None, ge=1870, le=2100),
    year_max: int | None = Query(None, ge=1870, le=2100),
    imdb_min: float | None = Query(None, ge=0, le=10),
    db: AsyncSession = Depends(get_db),
):
    user_id = get_current_user_id(request)
    q = q.strip()

    # Subject III.2.2: search results are sorted by name; without a search the
    # most popular videos come first.
    if q and sort_by == "downloads":
        sort_by, sort_dir = "title", "asc"

    # Ratings do not exist at the sources: ask them for popularity order, then
    # sort and filter by rating here, once ratings are attached.
    params: dict[str, str | int] = {
        "q": q,
        "page": page,
        "limit": limit,
        "source": source,
        "sort_by": "downloads" if sort_by == "imdb_rating" else sort_by,
        "sort_dir": sort_dir,
    }
    if genre and genre.strip():
        params["genre"] = genre.strip()
    if year_min is not None:
        params["year_min"] = year_min
    if year_max is not None:
        params["year_max"] = year_max

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(f"{TORRENT_SERVICE_URL}/search", params=params, headers=_auth_headers(request))
            response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("unexpected search payload")
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Search providers unreachable, serving cache: %s", exc)
        results, total, has_more = await _fallback_discover_results(
            db, user_id, q, page, limit, source, sort_by, sort_dir, genre, year_min, year_max, imdb_min
        )
        return {
            "query": q,
            "page": page,
            "limit": limit,
            "total": total,
            "has_more": has_more,
            "applied_sort": {"sort_by": sort_by, "sort_dir": sort_dir},
            "sources": [],
            "results": results,
            "warning": "Sources are unreachable; showing saved results.",
        }

    raw_results = [item for item in payload.get("results") or [] if isinstance(item, dict)]
    items: list[dict[str, object]] = []
    for item in raw_results:
        external_id = str(item.get("id") or item.get("external_id") or "")
        item_source = str(item.get("source") or "")
        if not external_id or item_source not in SUPPORTED_SOURCES:
            continue
        items.append(
            {
                "id": external_id,
                "source": item_source,
                "title": str(item.get("title") or "Untitled"),
                "year": _as_int(item.get("year")),
                "thumbnail": _str_or_none(item.get("thumbnail")),
                "genres": _normalize_genres(item.get("genres")),
                "downloads": _as_int(item.get("downloads")),
            }
        )

    # Subject III.2.2: IMDb rating (OMDb / TMDb) on every thumbnail when available.
    ratings = await ratings_for(db, [(str(i["title"]), i["year"]) for i in items])  # type: ignore[misc]
    for item in items:
        imdb_id, rating = rating_of(ratings, str(item["title"]), item["year"])  # type: ignore[arg-type]
        item["imdb_id"] = imdb_id
        item["imdb_rating"] = rating

    if items:
        cache_rows = [
            {
                "source": i["source"],
                "external_id": i["id"],
                "imdb_id": i["imdb_id"],
                "title": i["title"],
                "year": i["year"],
                "genres": ",".join(i["genres"]) or None,  # type: ignore[arg-type]
                "imdb_rating": i["imdb_rating"],
                "thumbnail": i["thumbnail"],
                "downloads": i["downloads"],
            }
            for i in items
        ]
        stmt = insert(ExternalMovieCache).values(cache_rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["source", "external_id"],
            set_={
                col: getattr(stmt.excluded, col)
                for col in ("imdb_id", "title", "year", "genres", "imdb_rating", "thumbnail", "downloads")
            },
        )
        await db.execute(stmt)
        await db.commit()

    watched = await _watched_pairs(db, user_id, [(str(i["source"]), str(i["id"])) for i in items])
    for item in items:
        item["watched"] = (item["source"], item["id"]) in watched

    if imdb_min is not None:
        items = [i for i in items if i["imdb_rating"] is not None and i["imdb_rating"] >= imdb_min]  # type: ignore[operator]
    if sort_by == "imdb_rating":
        rated = sorted(
            (i for i in items if i["imdb_rating"] is not None),
            key=lambda i: i["imdb_rating"],  # type: ignore[arg-type,return-value]
            reverse=sort_dir == "desc",
        )
        items = rated + [i for i in items if i["imdb_rating"] is None]

    return {
        "query": q,
        "page": page,
        "limit": limit,
        "total": _as_int(payload.get("total")) or 0,
        # Filters are applied per page, so a page may come back short or even
        # empty while later pages still hold matches: has_more stays the source's.
        "has_more": bool(payload.get("has_more")),
        "applied_sort": {"sort_by": sort_by, "sort_dir": sort_dir},
        "sources": payload.get("sources") or [],
        "warning": payload.get("warning"),
        "results": items,
    }


# ── Movies ────────────────────────────────────────────────────────────────────


async def _upsert_basic_movie(db: AsyncSession, item: dict[str, object]) -> Movie:
    """Make sure a search result has a local row, so it has a stable integer id
    for the public API. Full details are filled in when someone opens it."""
    source, external_id = str(item["source"]), str(item["id"])
    movie = (
        await db.execute(select(Movie).where(Movie.external_source == source, Movie.external_id == external_id))
    ).scalars().first()
    if movie is None:
        movie = Movie(
            title=str(item.get("title") or "Untitled"),
            year=_as_int(item.get("year")),
            thumbnail=_str_or_none(item.get("thumbnail")),
            cover_image=_str_or_none(item.get("thumbnail")),
            genres=_to_csv(_normalize_genres(item.get("genres"))),
            external_source=source,
            external_id=external_id,
            stream_status="not_started",
        )
        db.add(movie)
    if item.get("imdb_rating") is not None and not movie.imdb_rating:
        movie.imdb_rating = str(item["imdb_rating"])
    return movie


@router.get("/movies")
async def list_movies(db: AsyncSession = Depends(get_db)):
    """GET /api/movies — public. The front page's movies: the most popular videos
    across both sources, each with its id and name."""
    now = time.monotonic()
    if now - float(_front_page_cache["at"]) < FRONT_PAGE_TTL_SECONDS and _front_page_cache["items"]:
        return _front_page_cache["items"]

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{TORRENT_SERVICE_URL}/search",
                params={"page": 1, "limit": FRONT_PAGE_SIZE, "source": "all", "sort_by": "downloads", "sort_dir": "desc"},
                headers=_auth_headers(None),
            )
            response.raise_for_status()
        raw = [r for r in response.json().get("results") or [] if isinstance(r, dict)]
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Front page providers unreachable, serving local movies: %s", exc)
        raw = []

    items: list[dict[str, object]] = []
    for r in raw:
        if str(r.get("source")) in SUPPORTED_SOURCES and r.get("id"):
            items.append({"source": r["source"], "id": r["id"], "title": r.get("title"), "year": _as_int(r.get("year")),
                          "thumbnail": r.get("thumbnail"), "genres": r.get("genres")})

    if items:
        ratings = await ratings_for(db, [(str(i["title"] or ""), i["year"]) for i in items])  # type: ignore[misc]
        for item in items:
            item["imdb_rating"] = rating_of(ratings, str(item["title"] or ""), item["year"])[1]  # type: ignore[arg-type]
        movies = [await _upsert_basic_movie(db, item) for item in items]
        await db.commit()
        listing = [{"id": m.id, "name": m.title} for m in movies]
        _front_page_cache.update(at=now, items=listing)
        return listing

    result = await db.execute(
        select(Movie).order_by(Movie.last_accessed_at.desc().nulls_last(), Movie.id.desc()).limit(FRONT_PAGE_SIZE)
    )
    return [{"id": m.id, "name": m.title} for m in result.scalars().all()]


@router.get("/movies/{movie_id:int}")
async def get_movie(movie_id: int, db: AsyncSession = Depends(get_db)):
    """GET /api/movies/:id — full movie info, public."""
    result = await db.execute(select(Movie).where(Movie.id == movie_id))
    movie = result.scalars().first()
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")

    count_result = await db.execute(
        select(func.count(Comment.id)).where(Comment.movie_id == movie_id)
    )
    comment_count = count_result.scalar()

    return {
        "id": movie.id,
        "name": movie.title,
        "title": movie.title,
        "year": movie.year,
        "imdb_rating": movie.imdb_rating,
        "imdb_id": movie.imdb_id,
        "tmdb_id": movie.tmdb_id,
        "duration_minutes": movie.duration_minutes,
        "available_subtitles": _split_csv(movie.subtitle_languages or movie.available_subtitles),
        "genres": _split_csv(movie.genres),
        "thumbnail": movie.thumbnail,
        "cover_image": movie.cover_image or movie.thumbnail,
        "description": movie.description,
        "producer": movie.producer,
        "director": movie.director,
        "main_cast": _split_csv(movie.main_cast),
        "original_language": movie.original_language,
        "source": movie.external_source,
        "external_id": movie.external_id,
        "stream_status": movie.stream_status,
        "comment_count": comment_count,
    }


async def _fetch_source_details(request: Request, source: str, external_id: str) -> dict[str, object] | None:
    """Film metadata straight from its source, via torrent-service. Never from
    the browser: a client could otherwise rename any film for every user."""
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{TORRENT_SERVICE_URL}/details",
                params={"source": source, "external_id": external_id},
                headers=_auth_headers(request),
            )
        if response.status_code != 200:
            return None
        payload = response.json()
        return payload if isinstance(payload, dict) else None
    except (httpx.HTTPError, ValueError):
        return None


@router.post("/movies/external/ingest", status_code=status.HTTP_201_CREATED)
async def ingest_external_movie(
    request: Request,
    data: ExternalMovieIngestRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Canonicalize an external movie into a local `movies` row so watch/comments
    APIs can always target a stable local movie id. The body only names the
    film; every displayed field comes from the source and OMDb/TMDb.
    """
    get_current_user_id(request)
    source = data.source
    external_id = data.external_id.strip()

    movie = (
        await db.execute(select(Movie).where(Movie.external_source == source, Movie.external_id == external_id))
    ).scalars().first()

    details = await _fetch_source_details(request, source, external_id)
    if details is None and movie is None:
        raise HTTPException(status_code=404, detail="This video could not be found at its source")
    details = details or {}

    source_title = _str_or_none(details.get("title")) or (movie.title if movie else "Untitled")
    source_year = _as_int(details.get("year")) or (movie.year if movie else None)
    lookup_title, lookup_year = normalize_title(source_title, source_year)

    omdb = await _fetch_omdb_details(imdb_id=None, title=lookup_title, year=lookup_year)
    tmdb = await _fetch_tmdb_details(imdb_id=_str_or_none(omdb.get("imdb_id")), title=lookup_title, year=lookup_year)

    merged_year = source_year or _as_int(omdb.get("year"))
    merged_rating = _as_float(omdb.get("imdb_rating"))
    if merged_rating is None:
        merged_rating = _as_float(tmdb.get("imdb_rating_fallback"))
    merged_imdb_id = _str_or_none(omdb.get("imdb_id"))
    merged_tmdb_id = _str_or_none(tmdb.get("tmdb_id"))
    merged_duration = _as_int(details.get("duration_minutes")) or _as_int(tmdb.get("duration_minutes")) or _as_int(omdb.get("duration_minutes"))
    merged_description = _str_or_none(tmdb.get("description")) or _str_or_none(omdb.get("description")) or _str_or_none(details.get("description"))
    source_thumb = _str_or_none(details.get("thumbnail"))
    merged_cover = _str_or_none(tmdb.get("cover_image")) or _str_or_none(omdb.get("cover_image")) or source_thumb
    merged_genres = _str_list(details.get("genres")) or _str_list(tmdb.get("genres")) or _str_list(omdb.get("genres"))
    merged_producer = _str_or_none(tmdb.get("producer")) or _str_or_none(omdb.get("producer"))
    merged_director = _str_or_none(tmdb.get("director")) or _str_or_none(omdb.get("director"))
    merged_cast = _str_list(tmdb.get("main_cast")) or _str_list(omdb.get("main_cast"))
    merged_language = _str_or_none(details.get("original_language")) or _str_or_none(tmdb.get("original_language")) or _str_or_none(omdb.get("original_language"))

    # `movies.imdb_id` is globally unique. If this external pair is new but imdb_id
    # already exists on another row, keep this row without the imdb id.
    if merged_imdb_id:
        owner = (await db.execute(select(Movie).where(Movie.imdb_id == merged_imdb_id))).scalars().first()
        if owner is not None and (movie is None or owner.id != movie.id):
            merged_imdb_id = None

    now = datetime.now(timezone.utc)
    if movie is None:
        movie = Movie(external_source=source, external_id=external_id, stream_status="not_started")
        db.add(movie)

    movie.title = source_title
    movie.year = merged_year if merged_year is not None else movie.year
    if merged_rating is not None:
        movie.imdb_rating = str(merged_rating)
    movie.imdb_id = merged_imdb_id or movie.imdb_id
    movie.tmdb_id = merged_tmdb_id or movie.tmdb_id
    movie.duration_minutes = merged_duration if merged_duration is not None else movie.duration_minutes
    movie.thumbnail = source_thumb or movie.thumbnail
    movie.cover_image = merged_cover or movie.cover_image
    movie.description = merged_description or movie.description
    movie.genres = _to_csv(merged_genres) or movie.genres
    movie.producer = merged_producer or movie.producer
    movie.director = merged_director or movie.director
    movie.main_cast = _to_csv(merged_cast) or movie.main_cast
    movie.original_language = merged_language or movie.original_language
    movie.last_accessed_at = now

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        movie = (
            await db.execute(select(Movie).where(Movie.external_source == source, Movie.external_id == external_id))
        ).scalars().first()
        if movie is None:
            raise HTTPException(status_code=409, detail="Movie ingest conflict, please retry") from exc

    await db.refresh(movie)
    return {"movie_id": movie.id, "source": source, "external_id": external_id}


# ── Comments on a movie ───────────────────────────────────────────────────────


@router.get("/movies/{movie_id:int}/comments")
async def list_comments_for_movie(
    movie_id: int,
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    get_current_user_id(request)

    movie_result = await db.execute(select(Movie.id).where(Movie.id == movie_id))
    if movie_result.scalar() is None:
        raise HTTPException(status_code=404, detail="Movie not found")

    stmt = (
        select(Comment, User.username.label("author_username"))
        .join(User, User.id == Comment.author_id)
        .where(Comment.movie_id == movie_id)
        .order_by(Comment.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.all()
    return [
        {
            "id": row.Comment.id,
            "content": row.Comment.content,
            "author_id": row.Comment.author_id,
            "author_username": row.author_username,
            "movie_id": row.Comment.movie_id,
            "created_at": row.Comment.created_at,
        }
        for row in rows
    ]


@router.post("/movies/{movie_id:int}/comments", status_code=status.HTTP_201_CREATED)
async def create_comment_for_movie(
    movie_id: int,
    request: Request,
    data: CommentCreate,
    db: AsyncSession = Depends(get_db),
):
    """POST /api/movies/:movie_id/comments — create a comment (authenticated)."""
    author_id = get_current_user_id(request)

    result = await db.execute(select(Movie).where(Movie.id == movie_id))
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail="Movie not found")

    comment = Comment(content=data.comment, movie_id=movie_id, author_id=author_id)
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    author_result = await db.execute(select(User.username).where(User.id == author_id))
    author_username = author_result.scalar() or "unknown"

    return {
        "id": comment.id,
        "content": comment.content,
        "author_id": comment.author_id,
        "author_username": author_username,
        "movie_id": comment.movie_id,
        "created_at": comment.created_at,
    }


# ── Watched state ─────────────────────────────────────────────────────────────


@router.get("/movies/watched")
async def list_watched_movies(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_current_user_id(request)
    result = await db.execute(
        select(MovieWatchState.source, MovieWatchState.external_id, MovieWatchState.watched, MovieWatchState.updated_at)
        .where(MovieWatchState.user_id == user_id)
    )
    return [
        {
            "source": row.source,
            "id": row.external_id,
            "watched": row.watched,
            "updated_at": row.updated_at,
        }
        for row in result.all()
    ]


@router.post("/movies/{external_id}/watched-toggle")
async def toggle_watched_state(
    external_id: str,
    request: Request,
    data: WatchToggleRequest,
    source: Literal["archive", "peertube"] = "archive",
    db: AsyncSession = Depends(get_db),
):
    user_id = get_current_user_id(request)
    if not 1 <= len(external_id) <= 128:
        raise HTTPException(status_code=422, detail="Invalid video id")
    result = await db.execute(
        select(MovieWatchState).where(
            MovieWatchState.user_id == user_id,
            MovieWatchState.source == source,
            MovieWatchState.external_id == external_id,
        )
    )
    current = result.scalars().first()

    if current:
        current.watched = (not current.watched) if data.watched is None else bool(data.watched)
        await db.commit()
        watched = current.watched
    else:
        watched = True if data.watched is None else bool(data.watched)
        row = MovieWatchState(user_id=user_id, source=source, external_id=external_id, watched=watched)
        db.add(row)
        await db.commit()

    if watched:
        movie_result = await db.execute(
            select(Movie).where(Movie.external_source == source, Movie.external_id == external_id)
        )
        movie = movie_result.scalars().first()
        if movie:
            now = datetime.now(timezone.utc)
            movie.last_watched_at = now
            movie.last_accessed_at = now
            await db.commit()

    return {"source": source, "id": external_id, "watched": watched}
