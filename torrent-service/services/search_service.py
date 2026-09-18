from typing import Any
from urllib.parse import urlparse

import httpx

from config import (
    ARCHIVE_ADVANCEDSEARCH_URL,
    DEFAULT_SOURCE,
    MAX_SEARCH_LIMIT,
    NOISY_ARCHIVE_TERMS,
    OMDB_API_KEY,
    OMDB_BASE_URL,
    PEERTUBE_BROWSE_MIN_DURATION,
    PEERTUBE_FREE_LICENCES,
    PEERTUBE_SEARCH_URL,
)
from services.common import as_float, as_int, as_text, as_text_list, truncate_text


# ── Shared filtering / sorting ────────────────────────────────────────────────


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


# ── Internet Archive ──────────────────────────────────────────────────────────


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
        "provider_used": ARCHIVE_ADVANCEDSEARCH_URL,
        "results": sorted_results,
    }


# ── PeerTube (via SepiaSearch) ────────────────────────────────────────────────


def peertube_external_id(host: str, uuid: str) -> str:
    """PeerTube is federated, so an id is only unique together with its host."""
    return f"{host}:{uuid}"


def split_peertube_external_id(external_id: str) -> tuple[str, str]:
    host, _, uuid = external_id.partition(":")
    return host.strip(), uuid.strip()


def _peertube_host(video: dict[str, Any]) -> str:
    url = as_text(video.get("url"))
    if url:
        parsed = urlparse(url)
        if parsed.netloc:
            return parsed.netloc

    account = video.get("account")
    if isinstance(account, dict):
        return as_text(account.get("host")) or ""
    return ""


def _peertube_year(video: dict[str, Any]) -> int | None:
    for key in ("originallyPublishedAt", "publishedAt"):
        raw = as_text(video.get(key))
        if raw and len(raw) >= 4 and raw[:4].isdigit():
            return int(raw[:4])
    return None


def _normalize_peertube_video(video: dict[str, Any]) -> dict[str, Any] | None:
    host = _peertube_host(video)
    uuid = as_text(video.get("uuid"))
    if not host or not uuid:
        return None

    external_id = peertube_external_id(host, uuid)
    thumbnail_path = as_text(video.get("thumbnailPath"))
    thumbnail = f"https://{host}{thumbnail_path}" if thumbnail_path else None

    category = video.get("category")
    genres: list[str] = []
    if isinstance(category, dict):
        label = as_text(category.get("label"))
        if label:
            genres.append(label)

    licence = video.get("licence")
    licence_label = as_text(licence.get("label")) if isinstance(licence, dict) else None

    return {
        "id": external_id,
        "external_id": external_id,
        "source": "peertube",
        "title": as_text(video.get("name")) or "Untitled",
        "year": _peertube_year(video),
        "imdb_id": None,
        "imdb_rating": None,
        "genres": genres,
        "thumbnail": thumbnail,
        "downloads": as_int(video.get("views")),
        "seeders": None,
        "peers": None,
        "url": as_text(video.get("url")),
        "description": truncate_text(as_text(video.get("description"))),
        "duration_minutes": (as_int(video.get("duration")) or 0) // 60 or None,
        "licence": licence_label,
    }


async def _search_peertube(
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
    descending = sort_dir.lower() != "asc"
    if sort_by == "title":
        remote_sort = "-name" if descending else "name"
    elif sort_by == "year":
        remote_sort = "-publishedAt" if descending else "publishedAt"
    else:
        # PeerTube has no ratings/seeders; views is the closest popularity signal.
        remote_sort = "-views"

    params: list[tuple[str, Any]] = [
        ("start", (page - 1) * limit),
        ("count", limit),
        ("sort", remote_sort),
    ]
    for licence_id in PEERTUBE_FREE_LICENCES:
        params.append(("licenceOneOf", licence_id))

    if q.strip():
        params.append(("search", q.strip()))
    else:
        # Browsing: restrict to feature-length so the catalogue looks like films.
        params.append(("durationMin", PEERTUBE_BROWSE_MIN_DURATION))

    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
        response = await client.get(PEERTUBE_SEARCH_URL, params=params)
        response.raise_for_status()
        payload = response.json()

    data = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(data, list):
        data = []

    normalized: list[dict[str, Any]] = []
    for video in data:
        if not isinstance(video, dict):
            continue
        item = _normalize_peertube_video(video)
        if item is not None:
            normalized.append(item)

    filtered = _apply_filters(normalized, genre=genre, year_min=year_min, year_max=year_max, imdb_min=imdb_min)
    sorted_results = _sort_movies(filtered, sort_by=sort_by, sort_dir=sort_dir)
    total = as_int(payload.get("total")) or len(sorted_results)

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
        "source_provider": "peertube",
        "provider_used": PEERTUBE_SEARCH_URL,
        "results": sorted_results,
    }


# ── Entry point ───────────────────────────────────────────────────────────────


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
    source = source.strip().lower() if source else DEFAULT_SOURCE

    if q.strip() and sort_by == "downloads":
        sort_by = "title"
        sort_dir = "asc"

    provider = _search_peertube if source == "peertube" else _search_archive
    return await provider(
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


# ── Health checks ─────────────────────────────────────────────────────────────


async def check_archive_connectivity() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.get(
                ARCHIVE_ADVANCEDSEARCH_URL,
                params=[("q", "mediatype:(movies)"), ("rows", 1), ("output", "json"), ("fl[]", "identifier")],
            )
            response.raise_for_status()
            payload = response.json()
        found = payload.get("response", {}).get("numFound") if isinstance(payload, dict) else None
        return {"reachable": True, "num_found": found, "provider_used": ARCHIVE_ADVANCEDSEARCH_URL}
    except Exception as exc:
        return {"reachable": False, "error": str(exc)}


async def check_peertube_connectivity() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
            response = await client.get(PEERTUBE_SEARCH_URL, params=[("count", 1), ("licenceOneOf", 1)])
            response.raise_for_status()
            payload = response.json()
        return {
            "reachable": True,
            "total": payload.get("total") if isinstance(payload, dict) else None,
            "provider_used": PEERTUBE_SEARCH_URL,
        }
    except Exception as exc:
        return {"reachable": False, "error": str(exc)}


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
