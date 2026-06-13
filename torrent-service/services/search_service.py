import asyncio
import re
import time
from typing import Any

import httpx
from bs4 import BeautifulSoup

from config import (
    ARCHIVE_ADVANCEDSEARCH_URL,
    MAX_OMDB_ENRICH,
    MAX_SEARCH_LIMIT,
    NOISY_ARCHIVE_TERMS,
    OMDB_API_KEY,
    OMDB_BASE_URL,
    PDT_BASE_URL,
    PDT_CATALOG_TTL,
)
from services.common import as_float, as_int, as_text, as_text_list, coalesce_int, truncate_text


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


# ---------------------------------------------------------------------------
# Public Domain Torrents (publicdomaintorrents.info) — legal torrent provider.
# The site has no JSON API: a single category page lists every movie as
# `<a href="nshowmovie.html?movieid=N">Title</a>`. We scrape and cache that
# listing, filter/sort/paginate it ourselves, then enrich the visible page with
# OMDb metadata (year, rating, poster) since PDT exposes none.
# ---------------------------------------------------------------------------

_PDT_LISTING_CACHE: dict[str, tuple[float, list[dict[str, str]]]] = {}


def _parse_pdt_listing(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    entries: list[dict[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        match = re.search(r"movieid=(\d+)", anchor["href"])
        if not match:
            continue
        movie_id = match.group(1)
        title = " ".join(anchor.get_text().split())
        if not title or movie_id in seen:
            continue
        seen.add(movie_id)
        entries.append({"movieid": movie_id, "title": title})
    return entries


async def _fetch_pdt_listing(category: str) -> list[dict[str, str]]:
    cache_key = category or "ALL"
    now = time.monotonic()
    cached = _PDT_LISTING_CACHE.get(cache_key)
    if cached and now - cached[0] < PDT_CATALOG_TTL:
        return cached[1]

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        response = await client.get(f"{PDT_BASE_URL}/nshowcat.html", params={"category": cache_key})
        response.raise_for_status()
        html = response.text

    entries = _parse_pdt_listing(html)
    if entries:
        _PDT_LISTING_CACHE[cache_key] = (now, entries)
    return entries


async def _fetch_omdb_by_title(client: httpx.AsyncClient, title: str) -> dict[str, Any] | None:
    if not OMDB_API_KEY or not title:
        return None

    try:
        response = await client.get(
            OMDB_BASE_URL,
            params={"apikey": OMDB_API_KEY, "t": title, "type": "movie", "r": "json"},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("Response") == "True":
            return payload
    except httpx.HTTPError:
        return None

    return None


def _normalize_pdt_movie(entry: dict[str, str], omdb: dict[str, Any] | None = None) -> dict[str, Any]:
    omdb = omdb or {}
    movie_id = entry["movieid"]

    poster = as_text(omdb.get("Poster"))
    if poster == "N/A":
        poster = None

    genre_text = as_text(omdb.get("Genre"))
    genres = [genre.strip() for genre in genre_text.split(",") if genre.strip()] if genre_text else []

    return {
        "id": movie_id,
        "external_id": movie_id,
        "source": "pdt",
        "title": entry["title"] or as_text(omdb.get("Title")) or "Untitled",
        "year": coalesce_int(omdb.get("Year")),
        "imdb_id": as_text(omdb.get("imdbID")),
        "imdb_rating": as_float(omdb.get("imdbRating")),
        "genres": genres,
        "thumbnail": poster,
        "downloads": None,
        "seeders": None,
        "peers": None,
        "url": f"{PDT_BASE_URL}/nshowmovie.html?movieid={movie_id}",
    }


async def _search_pdt(
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
    category = genre.strip() if genre and genre.strip() else "ALL"
    entries = await _fetch_pdt_listing(category)

    query = " ".join(q.strip().split()).lower()
    if query:
        entries = [entry for entry in entries if query in entry["title"].lower()]

    reverse = sort_dir.lower() == "desc"
    entries = sorted(entries, key=lambda entry: entry["title"].lower(), reverse=reverse)

    total = len(entries)
    start = (page - 1) * limit
    page_slice = entries[start : start + limit]

    omdb_results: list[Any] = []
    if page_slice:
        async with httpx.AsyncClient(timeout=12.0) as client:
            tasks = [_fetch_omdb_by_title(client, entry["title"]) for entry in page_slice[:MAX_OMDB_ENRICH]]
            omdb_results = await asyncio.gather(*tasks, return_exceptions=False) if tasks else []

    normalized: list[dict[str, Any]] = []
    for index, entry in enumerate(page_slice):
        omdb_data = omdb_results[index] if index < len(omdb_results) and isinstance(omdb_results[index], dict) else None
        normalized.append(_normalize_pdt_movie(entry, omdb_data))

    # Genre already constrained the catalog (category page); only year/rating
    # filters remain. PDT has no global year/rating, so these apply within the
    # enriched page slice.
    filtered = _apply_filters(normalized, genre=None, year_min=year_min, year_max=year_max, imdb_min=imdb_min)
    sorted_results = _sort_movies(filtered, sort_by=sort_by, sort_dir=sort_dir)

    return {
        "query": q,
        "page": page,
        "limit": limit,
        "total": total,
        "has_more": (start + limit) < total and len(sorted_results) > 0,
        "applied_sort": {"sort_by": sort_by, "sort_dir": sort_dir},
        "applied_filters": {
            "genre": genre,
            "year_min": year_min,
            "year_max": year_max,
            "imdb_min": imdb_min,
        },
        "source_provider": "pdt",
        "results": sorted_results,
    }


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
    source = source.strip().lower() if source else "pdt"

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

    try:
        return await _search_pdt(
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


async def check_pdt_connectivity() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
            response = await client.get(f"{PDT_BASE_URL}/nshowcat.html", params={"category": "ALL"})
            response.raise_for_status()
        return {"reachable": True, "provider_used": PDT_BASE_URL}
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
