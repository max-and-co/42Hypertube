import asyncio
from typing import Any

import httpx

from config import (
    ARCHIVE_ADVANCEDSEARCH_URL,
    MAX_OMDB_ENRICH,
    MAX_SEARCH_LIMIT,
    NOISY_ARCHIVE_TERMS,
    OMDB_API_KEY,
    OMDB_BASE_URL,
    YTS_LIST_MOVIES_URL,
    YTS_LIST_MOVIES_FALLBACK_URLS,
)
from services.common import as_float, as_int, as_text, as_text_list, coalesce_int, truncate_text


YTS_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
}

YTS_BUILTIN_FALLBACK_URLS = [
    "https://yts.lt/api/v2/list_movies.json",
    "https://yts.am/api/v2/list_movies.json",
    "https://yts.rs/api/v2/list_movies.json",
]


def _candidate_yts_urls() -> list[str]:
    candidates: list[str] = [YTS_LIST_MOVIES_URL]
    for url in YTS_LIST_MOVIES_FALLBACK_URLS:
        if url not in candidates:
            candidates.append(url)
    for url in YTS_BUILTIN_FALLBACK_URLS:
        if url not in candidates:
            candidates.append(url)
    return candidates


def _build_archive_query(query: str) -> str:
    cleaned = " ".join(query.strip().split())
    if not cleaned:
        return "mediatype:(movies) AND (collection:(feature_films) OR subject:(film) OR subject:(movie))"

    escaped = cleaned.replace("\\", "\\\\").replace('"', '\\"')
    phrase = f'"{escaped}"'
    return (
        "mediatype:(movies) "
        f"AND ({phrase} OR title:{phrase} OR description:{phrase} OR creator:{phrase}) "
        "AND -title:(template OR test OR tutorial)"
    )


def _as_year(doc: dict[str, Any]) -> int | None:
    raw_year = as_text(doc.get("year"))
    if raw_year and raw_year[:4].isdigit():
        return int(raw_year[:4])

    raw_date = as_text(doc.get("date"))
    if raw_date and len(raw_date) >= 4 and raw_date[:4].isdigit():
        return int(raw_date[:4])

    return None


def _normalize_archive_doc(doc: dict[str, Any]) -> dict[str, Any]:
    identifier = as_text(doc.get("identifier")) or ""
    title = as_text(doc.get("title")) or identifier or "Untitled"
    subjects = as_text_list(doc.get("subject"))

    genres: list[str] = []
    for subject in subjects:
        genres.extend([genre.strip() for genre in subject.split(",") if genre.strip()])

    return {
        "id": identifier,
        "external_id": identifier,
        "source": "archive",
        "title": title,
        "year": _as_year(doc),
        "imdb_id": None,
        "imdb_rating": None,
        "genres": genres,
        "thumbnail": f"https://archive.org/services/img/{identifier}" if identifier else None,
        "downloads": as_int(doc.get("downloads")),
        "seeders": None,
        "peers": None,
        "url": f"https://archive.org/details/{identifier}" if identifier else None,
        "description": truncate_text(as_text(doc.get("description"))),
    }


def _is_reasonable_archive_result(movie: dict[str, Any], has_query: bool) -> bool:
    title = str(movie.get("title") or "").strip().lower()
    if not title:
        return False

    for term in NOISY_ARCHIVE_TERMS:
        if term in title:
            return False

    genres = [str(genre).lower() for genre in (movie.get("genres") or [])]
    genre_blob = " ".join(genres)
    year = as_int(movie.get("year"))

    if not has_query:
        movie_signal = any(token in title for token in ("movie", "film", "cinema")) or any(
            token in genre_blob for token in ("movie", "film", "feature")
        )
        if year is None and not movie_signal:
            return False

    return True


def _apply_filters(
    movies: list[dict[str, Any]],
    genre: str | None,
    year_min: int | None,
    year_max: int | None,
    imdb_min: float | None,
) -> list[dict[str, Any]]:
    normalized_genre = (genre or "").strip().lower()
    filtered: list[dict[str, Any]] = []

    for movie in movies:
        if normalized_genre:
            genres = [str(value).lower() for value in (movie.get("genres") or [])]
            if not any(normalized_genre in value for value in genres):
                continue

        year = as_int(movie.get("year"))
        if year_min is not None and (year is None or year < year_min):
            continue
        if year_max is not None and (year is None or year > year_max):
            continue

        rating = as_float(movie.get("imdb_rating"))
        if imdb_min is not None and (rating is None or rating < imdb_min):
            continue

        filtered.append(movie)

    return filtered


def _sort_movies(movies: list[dict[str, Any]], sort_by: str, sort_dir: str) -> list[dict[str, Any]]:
    reverse = sort_dir.lower() == "desc"

    if sort_by == "title":
        return sorted(movies, key=lambda movie: str(movie.get("title") or "").lower(), reverse=reverse)
    if sort_by == "year":
        return sorted(movies, key=lambda movie: as_int(movie.get("year")) or 0, reverse=reverse)
    if sort_by == "imdb_rating":
        return sorted(movies, key=lambda movie: as_float(movie.get("imdb_rating")) or 0.0, reverse=reverse)
    if sort_by == "seeders":
        return sorted(movies, key=lambda movie: as_int(movie.get("seeders")) or 0, reverse=reverse)
    if sort_by == "peers":
        return sorted(movies, key=lambda movie: as_int(movie.get("peers")) or 0, reverse=reverse)

    return sorted(
        movies,
        key=lambda movie: (
            as_int(movie.get("downloads")) or 0,
            as_int(movie.get("seeders")) or 0,
            as_int(movie.get("peers")) or 0,
        ),
        reverse=reverse,
    )


async def _search_archive(
    q: str,
    page: int,
    limit: int,
    sort_by: str,
    sort_dir: str,
    genre: str | None,
    year_min: int | None,
    year_max: int | None,
    imdb_min: float | None,
) -> dict[str, Any]:
    archive_query = _build_archive_query(q)
    sort_suffix = "asc" if sort_dir.lower() == "asc" else "desc"

    if sort_by == "title":
        sort_clause = f"title {sort_suffix}"
    elif sort_by == "year":
        sort_clause = f"date {sort_suffix}"
    else:
        sort_clause = "downloads desc"

    params: list[tuple[str, Any]] = [
        ("q", archive_query),
        ("rows", limit),
        ("page", page),
        ("output", "json"),
        ("sort[]", sort_clause),
        ("fl[]", "identifier"),
        ("fl[]", "title"),
        ("fl[]", "year"),
        ("fl[]", "date"),
        ("fl[]", "description"),
        ("fl[]", "subject"),
        ("fl[]", "downloads"),
    ]

    async with httpx.AsyncClient(timeout=12.0) as client:
        response = await client.get(ARCHIVE_ADVANCEDSEARCH_URL, params=params)
        response.raise_for_status()
        payload = response.json()

    search_response = payload.get("response", {}) if isinstance(payload, dict) else {}
    docs = search_response.get("docs", []) if isinstance(search_response, dict) else []
    if not isinstance(docs, list):
        docs = []

    normalized = [_normalize_archive_doc(doc) for doc in docs if isinstance(doc, dict)]
    normalized = [movie for movie in normalized if _is_reasonable_archive_result(movie, has_query=bool(q.strip()))]
    filtered = _apply_filters(normalized, genre=genre, year_min=year_min, year_max=year_max, imdb_min=imdb_min)
    sorted_results = _sort_movies(filtered, sort_by=sort_by, sort_dir=sort_dir)
    total = len(filtered) if q.strip() else (as_int(search_response.get("numFound")) or len(sorted_results))

    return {
        "query": q,
        "page": page,
        "limit": limit,
        "total": total,
        "has_more": page * limit < total and len(sorted_results) > 0,
        "applied_sort": {"sort_by": sort_by, "sort_dir": sort_dir},
        "applied_filters": {
            "genre": genre,
            "year_min": year_min,
            "year_max": year_max,
            "imdb_min": imdb_min,
        },
        "source_provider": "archive",
        "results": sorted_results,
    }


def _normalize_yts_movie(movie: dict[str, Any], omdb: dict[str, Any] | None = None) -> dict[str, Any]:
    torrents = movie.get("torrents") if isinstance(movie.get("torrents"), list) else []
    seeders = max((as_int(t.get("seeds")) or 0) for t in torrents) if torrents else None
    peers = max((as_int(t.get("peers")) or 0) for t in torrents) if torrents else None

    best_torrent = None
    if torrents:
        best_torrent = max(
            (torrent for torrent in torrents if isinstance(torrent, dict)),
            key=lambda torrent: ((as_int(torrent.get("seeds")) or 0), (as_int(torrent.get("peers")) or 0)),
            default=None,
        )

    yts_rating = as_float(movie.get("rating"))
    omdb_rating = as_float((omdb or {}).get("imdbRating"))
    imdb_rating = omdb_rating if omdb_rating is not None else yts_rating

    year = coalesce_int((omdb or {}).get("Year"), movie.get("year"))
    title = as_text((omdb or {}).get("Title")) or as_text(movie.get("title")) or "Untitled"
    genre_text = as_text((omdb or {}).get("Genre"))
    genres = [genre.strip() for genre in genre_text.split(",")] if genre_text else movie.get("genres") or []

    poster = as_text((omdb or {}).get("Poster"))
    if poster == "N/A":
        poster = None

    return {
        "id": str(movie.get("id") or ""),
        "external_id": str(movie.get("id") or ""),
        "source": "yts",
        "title": title,
        "year": year,
        "imdb_id": as_text(movie.get("imdb_code")),
        "imdb_rating": imdb_rating,
        "genres": genres,
        "thumbnail": poster or as_text(movie.get("large_cover_image")) or as_text(movie.get("medium_cover_image")),
        "downloads": coalesce_int(movie.get("download_count"), movie.get("downloaded"), movie.get("downloads")),
        "seeders": seeders,
        "peers": peers,
        "torrent_hash": as_text((best_torrent or {}).get("hash")),
        "url": as_text(movie.get("url")),
    }


async def _fetch_omdb_for_movie(client: httpx.AsyncClient, imdb_id: str) -> dict[str, Any] | None:
    if not OMDB_API_KEY or not imdb_id:
        return None

    try:
        response = await client.get(
            OMDB_BASE_URL,
            params={"apikey": OMDB_API_KEY, "i": imdb_id, "r": "json"},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("Response") == "True":
            return payload
    except httpx.HTTPError:
        return None

    return None


async def search_movies(
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
) -> dict[str, Any]:
    page = max(page, 1)
    limit = max(1, min(limit, MAX_SEARCH_LIMIT))
    source = source.strip().lower() if source else "yts"

    if source == "archive":
        return await _search_archive(
            q=q,
            page=page,
            limit=limit,
            sort_by=sort_by,
            sort_dir=sort_dir,
            genre=genre,
            year_min=year_min,
            year_max=year_max,
            imdb_min=imdb_min,
        )

    if q.strip() and sort_by == "downloads":
        sort_by = "title"
        sort_dir = "asc"

    yts_sort_map = {
        "downloads": "download_count",
        "seeders": "seeds",
        "peers": "peers",
        "title": "title",
        "year": "year",
        "imdb_rating": "rating",
    }
    yts_sort_by = yts_sort_map.get(sort_by, "download_count")
    yts_order = "asc" if sort_dir.lower() == "asc" else "desc"

    yts_params: dict[str, Any] = {
        "page": page,
        "limit": limit,
        "sort_by": yts_sort_by,
        "order_by": yts_order,
    }
    if q.strip():
        yts_params["query_term"] = q.strip()
    if genre:
        yts_params["genre"] = genre

    yts_urls = _candidate_yts_urls()

    payload: dict[str, Any] = {}
    yts_movies: list[dict[str, Any]] = []
    omdb_results: list[dict[str, Any] | None] = []
    last_yts_error: Exception | None = None
    yts_provider_used = ""

    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            for yts_url in yts_urls:
                try:
                    response = await client.get(yts_url, params=yts_params, headers=YTS_REQUEST_HEADERS)
                    response.raise_for_status()
                    payload = response.json()
                    yts_provider_used = yts_url

                    data = payload.get("data", {}) if isinstance(payload, dict) else {}
                    yts_movies = data.get("movies", []) if isinstance(data, dict) else []
                    if not isinstance(yts_movies, list):
                        yts_movies = []

                    omdb_tasks = []
                    for movie in yts_movies[:MAX_OMDB_ENRICH]:
                        if isinstance(movie, dict):
                            omdb_tasks.append(_fetch_omdb_for_movie(client, as_text(movie.get("imdb_code")) or ""))

                    omdb_results = await asyncio.gather(*omdb_tasks, return_exceptions=False) if omdb_tasks else []
                    break
                except httpx.HTTPError as url_exc:
                    last_yts_error = url_exc

            if not yts_provider_used:
                raise last_yts_error or httpx.HTTPError("No YTS endpoint configured")
    except httpx.HTTPError as exc:
        try:
            fallback_payload = await _search_archive(
                q=q,
                page=page,
                limit=limit,
                sort_by=sort_by,
                sort_dir=sort_dir,
                genre=genre,
                year_min=year_min,
                year_max=year_max,
                imdb_min=imdb_min,
            )
            fallback_payload["warning"] = f"Primary provider unavailable: {exc}"
            fallback_payload["provider_error"] = str(exc)
            return fallback_payload
        except httpx.HTTPError as fallback_exc:
            return {
                "query": q,
                "page": page,
                "limit": limit,
                "total": 0,
                "has_more": False,
                "results": [],
                "error": f"Primary provider error: {exc}; Fallback provider error: {fallback_exc}",
            }

    omdb_by_imdb_id: dict[str, dict[str, Any]] = {}
    for movie, omdb_data in zip(yts_movies[:MAX_OMDB_ENRICH], omdb_results):
        imdb_id = as_text(movie.get("imdb_code")) if isinstance(movie, dict) else None
        if imdb_id and isinstance(omdb_data, dict):
            omdb_by_imdb_id[imdb_id] = omdb_data

    normalized: list[dict[str, Any]] = []
    for movie in yts_movies:
        if not isinstance(movie, dict):
            continue
        imdb_id = as_text(movie.get("imdb_code"))
        normalized.append(_normalize_yts_movie(movie, omdb_by_imdb_id.get(imdb_id or "")))

    filtered = _apply_filters(normalized, genre=genre, year_min=year_min, year_max=year_max, imdb_min=imdb_min)
    sorted_results = _sort_movies(filtered, sort_by=sort_by, sort_dir=sort_dir)

    total = 0
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            total = as_int(data.get("movie_count")) or 0

    if filtered and len(filtered) < total:
        total = max(total, (page - 1) * limit + len(filtered))

    has_more = page * limit < total and len(sorted_results) > 0
    return {
        "query": q,
        "page": page,
        "limit": limit,
        "total": total,
        "has_more": has_more,
        "source_provider": "yts",
        "provider_used": yts_provider_used,
        "applied_sort": {"sort_by": sort_by, "sort_dir": sort_dir},
        "applied_filters": {
            "genre": genre,
            "year_min": year_min,
            "year_max": year_max,
            "imdb_min": imdb_min,
        },
        "results": sorted_results,
    }


async def check_yts_connectivity() -> dict[str, Any]:
    yts_urls = _candidate_yts_urls()

    last_error: Exception | None = None
    for yts_url in yts_urls:
        try:
            async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
                response = await client.get(
                    yts_url,
                    params={"limit": 1, "page": 1},
                    headers=YTS_REQUEST_HEADERS,
                )
                response.raise_for_status()
                payload = response.json()
                status = payload.get("status") if isinstance(payload, dict) else None
                return {"reachable": True, "status": status, "provider_used": yts_url}
        except Exception as exc:
            last_error = exc

    return {"reachable": False, "error": str(last_error) if last_error else "No YTS endpoint configured"}


async def check_omdb_connectivity() -> dict[str, Any]:
    if not OMDB_API_KEY:
        return {"configured": False, "reachable": False, "error": "OMDB_API_KEY is not set"}

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.get(
                OMDB_BASE_URL,
                params={"apikey": OMDB_API_KEY, "i": "tt0111161", "r": "json"},
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("Response") == "True":
                return {
                    "configured": True,
                    "reachable": True,
                    "sample_title": payload.get("Title"),
                    "sample_imdb_rating": payload.get("imdbRating"),
                }
            return {
                "configured": True,
                "reachable": False,
                "error": payload.get("Error") or "Unknown OMDb API error",
            }
    except httpx.HTTPStatusError as exc:
        return {
            "configured": True,
            "reachable": False,
            "error": f"HTTP {exc.response.status_code} from OMDb",
        }
    except Exception:
        return {"configured": True, "reachable": False, "error": "Could not reach OMDb"}
