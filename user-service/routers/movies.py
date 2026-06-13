import os
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, func, tuple_, cast, Float as SAFloat
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user_id, get_db
from models import Movie, Comment, ExternalMovieCache, MovieWatchState, User
from schemas import CommentCreate, WatchToggleRequest, ExternalMovieIngestRequest

router = APIRouter()

TORRENT_SERVICE_URL = os.getenv("TORRENT_SERVICE_URL", "http://torrent-service:8001")
OMDB_API_KEY = os.getenv("OMDB_API_KEY", "").strip()
OMDB_BASE_URL = "https://www.omdbapi.com/"
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()
TMDB_BASE_URL = "https://api.themoviedb.org/3"


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


async def _fetch_omdb_details(imdb_id: str | None, title: str | None, year: int | None) -> dict[str, object]:
    if not OMDB_API_KEY:
        return {}
    params: dict[str, str] = {"apikey": OMDB_API_KEY, "r": "json"}
    if imdb_id:
        params["i"] = imdb_id
    elif title:
        params["t"] = title
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
                "producer": payload.get("Production") if payload.get("Production") != "N/A" else None,
                "director": payload.get("Director") if payload.get("Director") != "N/A" else None,
                "main_cast": [c.strip() for c in str(payload.get("Actors") or "").split(",") if c.strip()],
                "cover_image": payload.get("Poster") if payload.get("Poster") not in (None, "N/A") else None,
                "genres": [g.strip() for g in str(payload.get("Genre") or "").split(",") if g.strip()],
                "year": _as_int(payload.get("Year")),
                "original_language": payload.get("Language"),
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
                if isinstance(results, list) and results:
                    tmdb_movie = results[0]

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


def _cache_sort_clause(sort_by: str, sort_dir: str):
    desc = sort_dir.lower() != "asc"
    if sort_by == "title":
        col = ExternalMovieCache.title
    elif sort_by == "year":
        col = ExternalMovieCache.year
    elif sort_by == "imdb_rating":
        col = ExternalMovieCache.imdb_rating
    elif sort_by == "seeders":
        col = ExternalMovieCache.seeders
    elif sort_by == "peers":
        col = ExternalMovieCache.peers
    else:
        col = ExternalMovieCache.downloads
    return col.desc() if desc else col.asc()


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
) -> tuple[list[dict[str, object]], int, bool, str]:
    cache_query = select(ExternalMovieCache)

    if source in {"yts", "archive"}:
        cache_query = cache_query.where(ExternalMovieCache.source == source)

    if q.strip():
        like = f"%{q.strip()}%"
        cache_query = cache_query.where(ExternalMovieCache.title.ilike(like))
    if genre:
        cache_query = cache_query.where(ExternalMovieCache.genres.ilike(f"%{genre.strip()}%"))
    if year_min is not None:
        cache_query = cache_query.where(ExternalMovieCache.year >= year_min)
    if year_max is not None:
        cache_query = cache_query.where(ExternalMovieCache.year <= year_max)
    if imdb_min is not None:
        cache_query = cache_query.where(ExternalMovieCache.imdb_rating >= imdb_min)

    total_cache = (await db.execute(select(func.count()).select_from(cache_query.subquery()))).scalar() or 0
    cache_rows = (
        await db.execute(
            cache_query
            .order_by(_cache_sort_clause(sort_by, sort_dir))
            .offset((page - 1) * limit)
            .limit(limit)
        )
    ).scalars().all()

    if cache_rows:
        pairs = [(r.source, r.external_id) for r in cache_rows]
        watched_rows = await db.execute(
            select(MovieWatchState.source, MovieWatchState.external_id)
            .where(MovieWatchState.user_id == user_id)
            .where(tuple_(MovieWatchState.source, MovieWatchState.external_id).in_(pairs))
            .where(MovieWatchState.watched.is_(True))
        )
        watched_pairs = set(watched_rows.all())
        results = [
            {
                "id": row.external_id,
                "source": row.source,
                "title": row.title,
                "year": row.year,
                "imdb_rating": row.imdb_rating,
                "thumbnail": row.thumbnail,
                "genres": _normalize_genres(row.genres),
                "downloads": row.downloads,
                "seeders": row.seeders,
                "peers": row.peers,
                "watched": (row.source, row.external_id) in watched_pairs,
                "url": None,
            }
            for row in cache_rows
        ]
        return results, int(total_cache), (page * limit < int(total_cache)), "cache"

    local_query = select(Movie)
    if q.strip():
        local_query = local_query.where(Movie.title.ilike(f"%{q.strip()}%"))
    if genre:
        local_query = local_query.where(Movie.genres.ilike(f"%{genre.strip()}%"))
    if year_min is not None:
        local_query = local_query.where(Movie.year >= year_min)
    if year_max is not None:
        local_query = local_query.where(Movie.year <= year_max)
    if imdb_min is not None:
        local_query = local_query.where(cast(Movie.imdb_rating, SAFloat) >= imdb_min)

    desc = sort_dir.lower() != "asc"
    if sort_by == "title":
        sort_col = Movie.title
    elif sort_by == "year":
        sort_col = Movie.year
    else:
        sort_col = cast(Movie.imdb_rating, SAFloat)

    total_local = (await db.execute(select(func.count()).select_from(local_query.subquery()))).scalar() or 0
    local_rows = (
        await db.execute(
            local_query.order_by(sort_col.desc() if desc else sort_col.asc()).offset((page - 1) * limit).limit(limit)
        )
    ).scalars().all()

    if not local_rows:
        return [], 0, False, "none"

    pairs = [("local", f"movie-{m.id}") for m in local_rows]
    watched_rows = await db.execute(
        select(MovieWatchState.source, MovieWatchState.external_id)
        .where(MovieWatchState.user_id == user_id)
        .where(tuple_(MovieWatchState.source, MovieWatchState.external_id).in_(pairs))
        .where(MovieWatchState.watched.is_(True))
    )
    watched_pairs = set(watched_rows.all())

    results = [
        {
            "id": f"movie-{m.id}",
            "source": "local",
            "title": m.title,
            "year": m.year,
            "imdb_rating": _as_float(m.imdb_rating),
            "thumbnail": m.thumbnail,
            "genres": _normalize_genres(m.genres),
            "downloads": None,
            "seeders": None,
            "peers": None,
            "watched": ("local", f"movie-{m.id}") in watched_pairs,
            "url": None,
        }
        for m in local_rows
    ]
    return results, int(total_local), (page * limit < int(total_local)), "local"


@router.get("/movies")
async def list_movies(db: AsyncSession = Depends(get_db)):
    """GET /api/movies — public frontpage movies list."""
    result = await db.execute(select(Movie).order_by(Movie.imdb_rating.desc()))
    movies = result.scalars().all()
    return [{"id": m.id, "title": m.title} for m in movies]


@router.get("/movies/discover")
async def discover_movies(
    request: Request,
    q: str = "",
    page: int = Query(1, ge=1),
    limit: int = Query(24, ge=1, le=50),
    source: str = "yts",
    sort_by: str = "downloads",
    sort_dir: str = "desc",
    genre: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    imdb_min: float | None = None,
    db: AsyncSession = Depends(get_db),
):
    user_id = get_current_user_id(request)
    requested_source = source.strip().lower() if source else "yts"
    if requested_source not in {"yts", "archive"}:
        raise HTTPException(status_code=400, detail="source must be 'yts' or 'archive'")

    if q.strip() and sort_by == "downloads":
        sort_by = "title"
        sort_dir = "asc"

    params: dict[str, str | int | float] = {
        "q": q,
        "page": page,
        "limit": limit,
        "source": requested_source,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
    }
    if genre:
        params["genre"] = genre
    if year_min is not None:
        params["year_min"] = year_min
    if year_max is not None:
        params["year_max"] = year_max
    if imdb_min is not None:
        params["imdb_min"] = imdb_min

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{TORRENT_SERVICE_URL}/search", params=params)
            response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        fallback_results, fallback_total, fallback_has_more, fallback_source = await _fallback_discover_results(
            db=db,
            user_id=user_id,
            q=q,
            page=page,
            limit=limit,
            source=requested_source,
            sort_by=sort_by,
            sort_dir=sort_dir,
            genre=genre,
            year_min=year_min,
            year_max=year_max,
            imdb_min=imdb_min,
        )
        return {
            "query": q,
            "page": page,
            "limit": limit,
            "total": fallback_total,
            "has_more": fallback_has_more,
            "applied_sort": {"sort_by": sort_by, "sort_dir": sort_dir},
            "applied_filters": {"genre": genre, "year_min": year_min, "year_max": year_max, "imdb_min": imdb_min},
            "source": requested_source,
            "requested_source": requested_source,
            "provider_used": fallback_source,
            "results": fallback_results,
            "warning": f"Provider request failed; using {fallback_source} fallback",
            "provider_error": str(exc),
        }

    raw_results = payload.get("results", [])
    if not isinstance(raw_results, list):
        raw_results = []

    provider_error = payload.get("error") if isinstance(payload, dict) else None
    if provider_error and not raw_results:
        fallback_results, fallback_total, fallback_has_more, fallback_source = await _fallback_discover_results(
            db=db,
            user_id=user_id,
            q=q,
            page=page,
            limit=limit,
            source=requested_source,
            sort_by=sort_by,
            sort_dir=sort_dir,
            genre=genre,
            year_min=year_min,
            year_max=year_max,
            imdb_min=imdb_min,
        )
        return {
            "query": q,
            "page": page,
            "limit": limit,
            "total": fallback_total,
            "has_more": fallback_has_more,
            "applied_sort": payload.get("applied_sort", {"sort_by": sort_by, "sort_dir": sort_dir}),
            "applied_filters": payload.get(
                "applied_filters",
                {"genre": genre, "year_min": year_min, "year_max": year_max, "imdb_min": imdb_min},
            ),
            "source": requested_source,
            "requested_source": requested_source,
            "provider_used": fallback_source,
            "results": fallback_results,
            "warning": f"Provider unavailable; using {fallback_source} fallback",
            "provider_error": str(provider_error),
        }

    cache_rows: list[dict[str, object]] = []
    external_pairs: list[tuple[str, str]] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        item_source = str(item.get("source") or "yts")
        external_id = str(item.get("id") or item.get("external_id") or "")
        if not external_id:
            continue
        external_pairs.append((item_source, external_id))
        cache_rows.append(
            {
                "source": item_source,
                "external_id": external_id,
                "imdb_id": item.get("imdb_id"),
                "title": item.get("title") or "Untitled",
                "year": _as_int(item.get("year")),
                "genres": ",".join(item.get("genres") or []) if isinstance(item.get("genres"), list) else item.get("genres"),
                "imdb_rating": _as_float(item.get("imdb_rating")),
                "thumbnail": item.get("thumbnail"),
                "downloads": _as_int(item.get("downloads")),
                "seeders": _as_int(item.get("seeders")),
                "peers": _as_int(item.get("peers")),
            }
        )

    if cache_rows:
        stmt = insert(ExternalMovieCache).values(cache_rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["source", "external_id"],
            set_={
                "imdb_id": stmt.excluded.imdb_id,
                "title": stmt.excluded.title,
                "year": stmt.excluded.year,
                "genres": stmt.excluded.genres,
                "imdb_rating": stmt.excluded.imdb_rating,
                "thumbnail": stmt.excluded.thumbnail,
                "downloads": stmt.excluded.downloads,
                "seeders": stmt.excluded.seeders,
                "peers": stmt.excluded.peers,
            },
        )
        await db.execute(stmt)
        await db.commit()

    watched_pairs: set[tuple[str, str]] = set()
    if external_pairs:
        result = await db.execute(
            select(MovieWatchState.source, MovieWatchState.external_id)
            .where(MovieWatchState.user_id == user_id)
            .where(tuple_(MovieWatchState.source, MovieWatchState.external_id).in_(external_pairs))
            .where(MovieWatchState.watched.is_(True))
        )
        watched_pairs = set(result.all())

    normalized: list[dict[str, object]] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        item_source = str(item.get("source") or "yts")
        external_id = str(item.get("id") or item.get("external_id") or "")
        if not external_id:
            continue
        normalized.append(
            {
                "id": external_id,
                "source": item_source,
                "title": item.get("title") or "Untitled",
                "year": _as_int(item.get("year")),
                "imdb_id": item.get("imdb_id"),
                "imdb_rating": _as_float(item.get("imdb_rating")),
                "thumbnail": item.get("thumbnail"),
                "genres": item.get("genres") or [],
                "downloads": _as_int(item.get("downloads")),
                "seeders": _as_int(item.get("seeders")),
                "peers": _as_int(item.get("peers")),
                "torrent_hash": item.get("torrent_hash"),
                "watched": (item_source, external_id) in watched_pairs,
                "url": item.get("url"),
            }
        )

    return {
        "query": q,
        "page": payload.get("page", page),
        "limit": payload.get("limit", limit),
        "total": payload.get("total", 0),
        "has_more": bool(payload.get("has_more", False)),
        "applied_sort": payload.get("applied_sort", {"sort_by": sort_by, "sort_dir": sort_dir}),
        "applied_filters": payload.get(
            "applied_filters",
            {"genre": genre, "year_min": year_min, "year_max": year_max, "imdb_min": imdb_min},
        ),
        "source": requested_source,
        "requested_source": requested_source,
        "provider_used": str(payload.get("provider_used") or payload.get("source_provider") or requested_source),
        "warning": payload.get("warning"),
        "provider_error": payload.get("provider_error") or payload.get("error"),
        "results": normalized,
    }


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
        "title": movie.title,
        "year": movie.year,
        "imdb_rating": movie.imdb_rating,
        "imdb_id": movie.imdb_id,
        "tmdb_id": movie.tmdb_id,
        "duration_minutes": movie.duration_minutes,
        "available_subtitles": _split_csv(movie.available_subtitles),
        "subtitle_languages": _split_csv(movie.subtitle_languages),
        "genres": _split_csv(movie.genres),
        "thumbnail": movie.thumbnail,
        "cover_image": movie.cover_image or movie.thumbnail,
        "description": movie.description,
        "producer": movie.producer,
        "director": movie.director,
        "main_cast": _split_csv(movie.main_cast),
        "original_language": movie.original_language,
        "external_source": movie.external_source,
        "external_id": movie.external_id,
        "stream_status": movie.stream_status,
        "video_path": movie.video_path,
        "last_watched_at": movie.last_watched_at,
        "last_accessed_at": movie.last_accessed_at,
        "comment_count": comment_count,
    }


@router.post("/movies/external/ingest", status_code=status.HTTP_201_CREATED)
async def ingest_external_movie(
    request: Request,
    data: ExternalMovieIngestRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Canonicalize an external movie into local `movies` row so watch/comments APIs
    can always target a stable local movie id.
    """
    _ = get_current_user_id(request)
    source = data.source.strip().lower()
    external_id = data.external_id.strip()
    if not source or not external_id:
        raise HTTPException(status_code=400, detail="source and external_id are required")

    cache_result = await db.execute(
        select(ExternalMovieCache).where(
            ExternalMovieCache.source == source,
            ExternalMovieCache.external_id == external_id,
        )
    )
    cache_row = cache_result.scalars().first()

    title_value = data.title.strip() if data.title.strip() else (cache_row.title if cache_row else "Untitled")
    year_value = data.year if data.year is not None else (cache_row.year if cache_row else None)
    rating_value = data.imdb_rating if data.imdb_rating is not None else (cache_row.imdb_rating if cache_row else None)
    thumb_value = data.thumbnail or (cache_row.thumbnail if cache_row else None)
    genres_value = data.genres if data.genres else (_normalize_genres(cache_row.genres) if cache_row else None)

    omdb = await _fetch_omdb_details(imdb_id=data.imdb_id, title=title_value, year=year_value)
    tmdb = await _fetch_tmdb_details(imdb_id=(data.imdb_id or omdb.get("imdb_id")), title=title_value, year=year_value)

    merged_title = title_value
    merged_year = year_value or _as_int(omdb.get("year"))
    merged_rating = rating_value if rating_value is not None else _as_float(omdb.get("imdb_rating"))
    merged_imdb_id = data.imdb_id or (omdb.get("imdb_id") if isinstance(omdb.get("imdb_id"), str) else None)
    merged_tmdb_id = data.tmdb_id or (tmdb.get("tmdb_id") if isinstance(tmdb.get("tmdb_id"), str) else None)
    merged_duration = data.duration_minutes or _as_int(tmdb.get("duration_minutes")) or _as_int(omdb.get("duration_minutes"))
    merged_description = data.description or (tmdb.get("description") if isinstance(tmdb.get("description"), str) else None) or (omdb.get("description") if isinstance(omdb.get("description"), str) else None)
    merged_cover = data.cover_image or thumb_value or (tmdb.get("cover_image") if isinstance(tmdb.get("cover_image"), str) else None) or (omdb.get("cover_image") if isinstance(omdb.get("cover_image"), str) else None)
    merged_genres = genres_value or [g for g in (tmdb.get("genres") if isinstance(tmdb.get("genres"), list) else []) if isinstance(g, str)] or [g for g in (omdb.get("genres") if isinstance(omdb.get("genres"), list) else []) if isinstance(g, str)]
    merged_producer = data.producer or (tmdb.get("producer") if isinstance(tmdb.get("producer"), str) else None) or (omdb.get("producer") if isinstance(omdb.get("producer"), str) else None)
    merged_director = data.director or (tmdb.get("director") if isinstance(tmdb.get("director"), str) else None) or (omdb.get("director") if isinstance(omdb.get("director"), str) else None)
    merged_cast = data.main_cast or [c for c in (tmdb.get("main_cast") if isinstance(tmdb.get("main_cast"), list) else []) if isinstance(c, str)] or [c for c in (omdb.get("main_cast") if isinstance(omdb.get("main_cast"), list) else []) if isinstance(c, str)]
    merged_language = data.original_language or (tmdb.get("original_language") if isinstance(tmdb.get("original_language"), str) else None) or (omdb.get("original_language") if isinstance(omdb.get("original_language"), str) else None)

    existing_result = await db.execute(
        select(Movie).where(Movie.external_source == source, Movie.external_id == external_id)
    )
    movie = existing_result.scalars().first()

    # `movies.imdb_id` is globally unique. If this external pair is new but imdb_id
    # already exists, reuse that canonical row instead of attempting a duplicate insert.
    if movie is None and merged_imdb_id:
        imdb_result = await db.execute(select(Movie).where(Movie.imdb_id == merged_imdb_id))
        movie = imdb_result.scalars().first()

    now = datetime.now(timezone.utc)
    if movie is None:
        movie = Movie(
            title=merged_title,
            year=merged_year,
            imdb_rating=(str(merged_rating) if merged_rating is not None else None),
            imdb_id=merged_imdb_id,
            tmdb_id=merged_tmdb_id,
            duration_minutes=merged_duration,
            available_subtitles=_to_csv(data.available_subtitles),
            subtitle_languages=_to_csv(data.available_subtitles),
            thumbnail=thumb_value,
            cover_image=merged_cover,
            description=merged_description,
            genres=_to_csv(merged_genres),
            producer=merged_producer,
            director=merged_director,
            main_cast=_to_csv(merged_cast),
            original_language=merged_language,
            external_source=source,
            external_id=external_id,
            torrent_hash=data.torrent_hash,
            stream_status="not_started",
            last_accessed_at=now,
        )
        db.add(movie)
    else:
        movie.title = merged_title or movie.title
        movie.year = merged_year if merged_year is not None else movie.year
        if merged_rating is not None:
            movie.imdb_rating = str(merged_rating)
        movie.imdb_id = merged_imdb_id or movie.imdb_id
        movie.tmdb_id = merged_tmdb_id or movie.tmdb_id
        movie.duration_minutes = merged_duration if merged_duration is not None else movie.duration_minutes
        movie.available_subtitles = _to_csv(data.available_subtitles) or movie.available_subtitles
        movie.subtitle_languages = _to_csv(data.available_subtitles) or movie.subtitle_languages
        movie.thumbnail = thumb_value or movie.thumbnail
        movie.cover_image = merged_cover or movie.cover_image
        movie.description = merged_description or movie.description
        movie.genres = _to_csv(merged_genres) or movie.genres
        movie.producer = merged_producer or movie.producer
        movie.director = merged_director or movie.director
        movie.main_cast = _to_csv(merged_cast) or movie.main_cast
        movie.original_language = merged_language or movie.original_language
        movie.torrent_hash = data.torrent_hash or movie.torrent_hash
        movie.last_accessed_at = now

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()

        recovered_movie = None
        if merged_imdb_id:
            imdb_result = await db.execute(select(Movie).where(Movie.imdb_id == merged_imdb_id))
            recovered_movie = imdb_result.scalars().first()
        if recovered_movie is None:
            ext_result = await db.execute(
                select(Movie).where(Movie.external_source == source, Movie.external_id == external_id)
            )
            recovered_movie = ext_result.scalars().first()
        if recovered_movie is None:
            raise HTTPException(status_code=409, detail="Movie ingest conflict, please retry") from exc

        movie = recovered_movie

    await db.refresh(movie)
    return {
        "movie_id": movie.id,
        "source": source,
        "external_id": external_id,
    }


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
    source: str = "yts",
    db: AsyncSession = Depends(get_db),
):
    user_id = get_current_user_id(request)
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
