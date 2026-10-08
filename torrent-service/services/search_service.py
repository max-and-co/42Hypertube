import asyncio
import html
import ipaddress
import logging
import re
import socket
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from config import (
    ARCHIVE_ADVANCEDSEARCH_URL,
    ARCHIVE_COLLECTIONS,
    ARCHIVE_LICENCE_MARKER,
    ARCHIVE_MAX_YEAR,
    ARCHIVE_METADATA_URL,
    ARCHIVE_UPLOADED_BEFORE,
    DEFAULT_SOURCE,
    MAX_SEARCH_LIMIT,
    NOISY_ARCHIVE_TERMS,
    OMDB_API_KEY,
    OMDB_BASE_URL,
    PEERTUBE_BROWSE_MIN_DURATION,
    PEERTUBE_FREE_LICENCES,
    PEERTUBE_SEARCH_URL,
    PEERTUBE_TRUSTED_HOSTS,
)
from services.common import as_float, as_int, as_text, as_text_list, truncate_text

logger = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    """Every requested source failed."""


# ── Identifier validation ─────────────────────────────────────────────────────
# Ids come from the browser and end up in URLs this service fetches, so they
# are checked before any request: an archive identifier is a plain slug, and a
# PeerTube id names a public host (never a container on our network).

_ARCHIVE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_PEERTUBE_HOST = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9-]{1,63}\.)+[A-Za-z]{2,63}$")
_PEERTUBE_VIDEO = re.compile(r"^[A-Za-z0-9-]{8,64}$")


async def _host_is_public(hostname: str) -> bool:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(hostname, 443)
    except (socket.gaierror, UnicodeError):
        return False
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            return False
    return bool(infos)


async def validate_external_id(source: str, external_id: str) -> None:
    """Raise ValueError when an id is malformed or points somewhere unsafe."""
    if source == "archive":
        if not _ARCHIVE_ID.fullmatch(external_id):
            raise ValueError("Malformed archive.org identifier")
        return
    if source == "peertube":
        host, uuid = split_peertube_external_id(external_id)
        if not _PEERTUBE_HOST.fullmatch(host) or not _PEERTUBE_VIDEO.fullmatch(uuid):
            raise ValueError("Malformed PeerTube id")
        if host.lower() not in PEERTUBE_TRUSTED_HOSTS:
            raise ValueError("PeerTube host is not an allowed source")
        if not await _host_is_public(host):
            raise ValueError("PeerTube host is not a public address")
        return
    raise ValueError(f"Unsupported source '{source}'")


# ── Shared filtering / sorting ────────────────────────────────────────────────


def _apply_filters(
    movies: list[dict[str, Any]],
    genre: str | None,
    year_min: int | None,
    year_max: int | None,
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

        filtered.append(movie)

    return filtered


def _sort_movies(movies: list[dict[str, Any]], sort_by: str, sort_dir: str) -> list[dict[str, Any]]:
    reverse = sort_dir.lower() == "desc"

    if sort_by == "title":
        return sorted(movies, key=lambda movie: str(movie.get("title") or "").lower(), reverse=reverse)
    if sort_by == "year":
        return sorted(movies, key=lambda movie: as_int(movie.get("year")) or 0, reverse=reverse)
    return sorted(movies, key=lambda movie: as_int(movie.get("downloads")) or 0, reverse=reverse)


# ── Internet Archive ──────────────────────────────────────────────────────────


_ARCHIVE_SCOPE = (
    f"mediatype:(movies) AND collection:({' OR '.join(ARCHIVE_COLLECTIONS)}) "
    f"AND licenseurl:*{ARCHIVE_LICENCE_MARKER}* "
    f"AND year:[1870 TO {ARCHIVE_MAX_YEAR}] "
    f"AND publicdate:[1990-01-01 TO {ARCHIVE_UPLOADED_BEFORE}]"
)


def _archive_phrase(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _build_archive_query(
    query: str, genre: str | None = None, year_min: int | None = None, year_max: int | None = None
) -> str:
    """Filters go into the query itself: filtering a fetched page afterwards
    left 2 horror films out of 12 per request, and the grid crawled."""
    parts = [_ARCHIVE_SCOPE]
    cleaned = " ".join(query.strip().split())
    if cleaned:
        phrase = _archive_phrase(cleaned)
        parts.append(f"({phrase} OR title:{phrase} OR description:{phrase} OR creator:{phrase})")
        parts.append("-title:(template OR test OR tutorial)")
    if genre and genre.strip():
        parts.append(f"subject:{_archive_phrase(' '.join(genre.split()))}")
    if year_min is not None or year_max is not None:
        parts.append(f"year:[{year_min or 1870} TO {year_max or 2100}]")
    return " AND ".join(parts)


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


def _archive_sort_clause(sort_by: str, sort_dir: str) -> str:
    suffix = "asc" if sort_dir.lower() == "asc" else "desc"
    if sort_by == "title":
        # titleSorter is the lower-cased title: the order _merge_key uses.
        return f"titleSorter {suffix}"
    if sort_by == "year":
        return f"year {suffix}"
    return "downloads desc"


async def _archive_page(
    client: httpx.AsyncClient, query: str, sort_clause: str, page: int, rows: int
) -> tuple[list[dict[str, Any]], int]:
    """One page of archive.org results, in archive.org's order, unfiltered."""
    params: list[tuple[str, Any]] = [
        ("q", query),
        ("rows", rows),
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
    response = await client.get(ARCHIVE_ADVANCEDSEARCH_URL, params=params)
    response.raise_for_status()
    payload = response.json()

    search_response = payload.get("response", {}) if isinstance(payload, dict) else {}
    docs = search_response.get("docs", []) if isinstance(search_response, dict) else []
    if not isinstance(docs, list):
        docs = []
    normalized = [_normalize_archive_doc(doc) for doc in docs if isinstance(doc, dict)]
    return normalized, as_int(search_response.get("numFound")) or 0


def _keep_archive(movie: dict[str, Any], q: str, genre: str | None, year_min: int | None, year_max: int | None) -> bool:
    return _is_reasonable_archive_result(movie, has_query=bool(q.strip())) and bool(
        _apply_filters([movie], genre=genre, year_min=year_min, year_max=year_max)
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
) -> dict[str, Any]:
    query = _build_archive_query(q, genre, year_min, year_max)
    async with httpx.AsyncClient(timeout=12.0) as client:
        movies, total = await _archive_page(client, query, _archive_sort_clause(sort_by, sort_dir), page, limit)

    kept = [movie for movie in movies if _keep_archive(movie, q, genre, year_min, year_max)]
    # The total is what archive.org matched, not what survived this page's
    # filters: a page emptied by a filter must not end the infinite scroll.
    return {"total": total, "has_more": page * limit < total, "results": _sort_movies(kept, sort_by, sort_dir)}


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


def _peertube_params(q: str, sort_by: str, sort_dir: str) -> list[tuple[str, Any]]:
    descending = sort_dir.lower() != "asc"
    if sort_by == "title":
        remote_sort = "-name" if descending else "name"
    elif sort_by == "year":
        remote_sort = "-publishedAt" if descending else "publishedAt"
    else:
        # PeerTube has no ratings/seeders; views is the closest popularity signal.
        remote_sort = "-views"

    params: list[tuple[str, Any]] = [("sort", remote_sort), ("nsfw", "false")]
    for licence_id in PEERTUBE_FREE_LICENCES:
        params.append(("licenceOneOf", licence_id))
    if q.strip():
        params.append(("search", q.strip()))
    else:
        # Browsing: skip short clips so the catalogue looks like films.
        params.append(("durationMin", PEERTUBE_BROWSE_MIN_DURATION))
    return params


async def _peertube_page(
    client: httpx.AsyncClient, host: str, params: list[tuple[str, Any]], start: int, count: int
) -> tuple[list[dict[str, Any]], int]:
    """Videos of one trusted instance, in SepiaSearch's order, unfiltered.
    SepiaSearch filters on a single host per query."""
    response = await client.get(
        PEERTUBE_SEARCH_URL, params=[*params, ("start", start), ("count", count), ("host", host)]
    )
    response.raise_for_status()
    answer = response.json()
    answer = answer if isinstance(answer, dict) else {}

    movies: list[dict[str, Any]] = []
    data = answer.get("data", [])
    for video in data if isinstance(data, list) else []:
        if not isinstance(video, dict):
            continue
        item = _normalize_peertube_video(video)
        # Belt and braces: never trust that the index honoured the host filter.
        if item is not None and item["external_id"].split(":", 1)[0].lower() == host:
            movies.append(item)
    return movies, as_int(answer.get("total")) or 0


async def _search_peertube(
    q: str,
    page: int,
    limit: int,
    sort_by: str,
    sort_dir: str,
    genre: str | None,
    year_min: int | None,
    year_max: int | None,
) -> dict[str, Any]:
    # Each trusted instance gets its share of the page, asked in parallel.
    per_host = -(-limit // len(PEERTUBE_TRUSTED_HOSTS))
    params = _peertube_params(q, sort_by, sort_dir)
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
        answers = await asyncio.gather(
            *(_peertube_page(client, host, params, (page - 1) * per_host, per_host) for host in PEERTUBE_TRUSTED_HOSTS),
            return_exceptions=True,
        )
    pages = [answer for answer in answers if not isinstance(answer, BaseException)]
    if not pages:
        raise answers[0]

    movies = [movie for part, _ in pages for movie in part]
    filtered = _apply_filters(movies, genre=genre, year_min=year_min, year_max=year_max)
    return {
        "total": sum(total for _, total in pages),
        "has_more": any(page * per_host < total for _, total in pages),
        "results": _sort_movies(filtered, sort_by=sort_by, sort_dir=sort_dir),
    }


# ── Merged order across sources (sort by name / year) ─────────────────────────
# Page N of every source glued together is not in order: page 1 of PeerTube
# ends at "T…", then page 2 of archive.org starts again at "B…". Instead a
# cursor records how many items of each stream (archive.org, each PeerTube
# instance) were already shown; every request fetches `limit` more from each
# stream and merges them, so the grid stays in one global order.

_CURSOR_PART = re.compile(r"^([a-z0-9.-]{1,253})=(\d{1,6})$")


def parse_cursor(raw: str | None) -> dict[str, int]:
    """'archive=24,video.blender.org=8' -> offsets; anything malformed -> ValueError."""
    offsets: dict[str, int] = {}
    for part in filter(None, (raw or "").split(",")):
        match = _CURSOR_PART.fullmatch(part)
        if not match:
            raise ValueError("Malformed cursor")
        offsets[match.group(1)] = int(match.group(2))
    return offsets


def _format_cursor(offsets: dict[str, int]) -> str:
    return ",".join(f"{name}={offset}" for name, offset in offsets.items())


def _merge_key(movie: dict[str, Any], sort_by: str) -> Any:
    if sort_by == "year":
        return as_int(movie.get("year")) or 0
    return str(movie.get("title") or "").lower()


async def _archive_window(
    client: httpx.AsyncClient, query: str, sort_clause: str, offset: int, count: int
) -> tuple[list[dict[str, Any]], int]:
    """`count` items from `offset`: archive.org only pages, so read the one or
    two pages covering that range."""
    first = offset // count + 1
    pages = await asyncio.gather(
        *(_archive_page(client, query, sort_clause, page, count) for page in ((first, first + 1) if offset % count else (first,)))
    )
    movies = [movie for part, _ in pages for movie in part]
    skip = offset % count
    return movies[skip:skip + count], pages[0][1]


async def _search_merged(
    q: str,
    cursor: dict[str, int],
    limit: int,
    source: str,
    sort_by: str,
    sort_dir: str,
    genre: str | None,
    year_min: int | None,
    year_max: int | None,
) -> dict[str, Any]:
    streams: list[str] = []
    if source in ("all", "archive"):
        streams.append("archive")
    if source in ("all", "peertube"):
        streams.extend(PEERTUBE_TRUSTED_HOSTS)
    offsets = {name: cursor.get(name, 0) for name in streams}

    archive_query = _build_archive_query(q, genre, year_min, year_max)
    archive_sort = _archive_sort_clause(sort_by, sort_dir)
    peertube_params = _peertube_params(q, sort_by, sort_dir)

    async def fetch(client: httpx.AsyncClient, name: str):
        if name == "archive":
            return await _archive_window(client, archive_query, archive_sort, offsets[name], limit)
        return await _peertube_page(client, name, peertube_params, offsets[name], limit)

    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
        answers = await asyncio.gather(*(fetch(client, name) for name in streams), return_exceptions=True)

    buffers: dict[str, list[dict[str, Any]]] = {}
    totals: dict[str, int] = {}
    failed: list[str] = []
    for name, answer in zip(streams, answers):
        if isinstance(answer, BaseException):
            logger.warning("Search stream %s failed: %s", name, answer)
            failed.append(name)
        else:
            buffers[name], totals[name] = answer
            if not buffers[name]:
                # Nothing more comes back (SepiaSearch caps deep paging even
                # when its total says otherwise): this stream is finished.
                totals[name] = offsets[name]
    if not buffers:
        raise ProviderError("No search source answered")

    def keep(name: str, movie: dict[str, Any]) -> bool:
        if name == "archive":
            return _keep_archive(movie, q, genre, year_min, year_max)
        return bool(_apply_filters([movie], genre=genre, year_min=year_min, year_max=year_max))

    descending = sort_dir.lower() == "desc"
    positions = {name: 0 for name in buffers}
    results: list[dict[str, Any]] = []
    while len(results) < limit:
        heads = [name for name in buffers if positions[name] < len(buffers[name])]
        # A stream that still has items on the server but none fetched here
        # could hold the next one: stop, the next request continues from here.
        if any(
            positions[name] >= len(buffers[name]) and offsets[name] + positions[name] < totals[name]
            for name in buffers
        ) or not heads:
            break
        pick = (max if descending else min)(heads, key=lambda name: _merge_key(buffers[name][positions[name]], sort_by))
        movie = buffers[pick][positions[pick]]
        positions[pick] += 1
        if keep(pick, movie):
            results.append(movie)

    next_offsets = {name: offsets[name] + positions.get(name, 0) for name in streams}
    has_more = any(next_offsets[name] < totals[name] for name in buffers)
    return {
        "total": sum(totals.values()),
        "has_more": has_more,
        "next_cursor": _format_cursor(next_offsets) if has_more else None,
        "failed": failed,
        "results": results,
    }


# ── Entry point ───────────────────────────────────────────────────────────────


def _interleave(first: list[dict[str, Any]], second: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Archive downloads and PeerTube views are not comparable numbers, so the
    popularity order alternates the two sources' own rankings."""
    merged: list[dict[str, Any]] = []
    for index in range(max(len(first), len(second))):
        if index < len(first):
            merged.append(first[index])
        if index < len(second):
            merged.append(second[index])
    return merged


# The sources answer in 3-10 s; a page already fetched is reused for a few
# minutes (going back, re-sorting, several users browsing the front page).
_SEARCH_CACHE: dict[tuple, tuple[float, dict[str, Any]]] = {}
SEARCH_CACHE_SECONDS = 300
SEARCH_CACHE_MAX = 512


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
    cursor: str | None = None,
) -> dict[str, Any]:
    page = max(page, 1)
    limit = max(1, min(limit, MAX_SEARCH_LIMIT))
    source = source.strip().lower() if source else DEFAULT_SOURCE

    if q.strip() and sort_by == "downloads":
        sort_by = "title"
        sort_dir = "asc"

    merged = sort_by in ("title", "year")
    cache_key = (q.strip().lower(), page, limit, source, sort_by, sort_dir, genre, year_min, year_max, cursor if merged else None)
    now = asyncio.get_running_loop().time()
    cached = _SEARCH_CACHE.get(cache_key)
    if cached and cached[0] > now:
        return cached[1]

    if merged:
        answer = await _search_merged(
            q, parse_cursor(cursor), limit, source, sort_by, sort_dir, genre, year_min, year_max
        )
        failed = answer.pop("failed")
        result = {
            "query": q,
            "page": page,
            "limit": limit,
            **answer,
            "applied_sort": {"sort_by": sort_by, "sort_dir": sort_dir},
            "sources": [name for name in ("archive", "peertube") if source in ("all", name)],
            "warning": f"Unavailable right now: {', '.join(failed)}" if failed else None,
        }
        if not failed:
            if len(_SEARCH_CACHE) >= SEARCH_CACHE_MAX:
                _SEARCH_CACHE.pop(next(iter(_SEARCH_CACHE)))
            _SEARCH_CACHE[cache_key] = (now + SEARCH_CACHE_SECONDS, result)
        return result

    providers = {"archive": _search_archive, "peertube": _search_peertube}
    names = list(providers) if source == "all" else [source]
    # With both sources each contributes half a page, so pages stay the same size.
    per_source = -(-limit // len(names))

    answers = await asyncio.gather(
        *(
            providers[name](
                q=q, page=page, limit=per_source, sort_by=sort_by, sort_dir=sort_dir,
                genre=genre, year_min=year_min, year_max=year_max,
            )
            for name in names
        ),
        return_exceptions=True,
    )

    ok: dict[str, dict[str, Any]] = {}
    for name, answer in zip(names, answers):
        if isinstance(answer, Exception):
            logger.warning("Search source %s failed: %s", name, answer)
        else:
            ok[name] = answer
    if not ok:
        raise ProviderError("No search source answered")

    lists = [ok[name]["results"] for name in names if name in ok]
    if len(lists) == 2 and sort_by == "downloads":
        results = _interleave(lists[0], lists[1])
    else:
        results = _sort_movies([m for part in lists for m in part], sort_by=sort_by, sort_dir=sort_dir)

    failed = [name for name in names if name not in ok]
    result = {
        "query": q,
        "page": page,
        "limit": limit,
        "total": sum(answer["total"] for answer in ok.values()),
        "has_more": any(answer["has_more"] for answer in ok.values()),
        "applied_sort": {"sort_by": sort_by, "sort_dir": sort_dir},
        "sources": list(ok),
        "warning": f"Unavailable right now: {', '.join(failed)}" if failed else None,
        "results": results,
    }
    if not failed:
        if len(_SEARCH_CACHE) >= SEARCH_CACHE_MAX:
            _SEARCH_CACHE.pop(next(iter(_SEARCH_CACHE)))
        _SEARCH_CACHE[cache_key] = (now + SEARCH_CACHE_SECONDS, result)
    return result


# ── Details (film page) ───────────────────────────────────────────────────────

_TAGS = re.compile(r"<[^>]+>")


def _plain_text(value: Any, max_length: int = 2000) -> str | None:
    text = as_text(value)
    if not text:
        return None
    text = html.unescape(_TAGS.sub(" ", text))
    return truncate_text(text, max_length)


def _runtime_minutes(value: Any) -> int | None:
    text = as_text(value)
    if not text:
        return None
    parts = text.split(":")
    if len(parts) in (2, 3) and all(p.strip().isdigit() for p in parts):
        numbers = [int(p) for p in parts]
        seconds = numbers[-1] + 60 * numbers[-2] + (3600 * numbers[0] if len(numbers) == 3 else 0)
        return max(1, round(seconds / 60))
    match = re.match(r"\s*(\d+)", text)
    return int(match.group(1)) if match else None


async def fetch_details(source: str, external_id: str) -> dict[str, Any]:
    """Metadata for the film page, read from the source itself."""
    await validate_external_id(source, external_id)
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        if source == "archive":
            response = await client.get(f"{ARCHIVE_METADATA_URL}/{quote(external_id)}")
            response.raise_for_status()
            metadata = (response.json() or {}).get("metadata") or {}
            if not metadata:
                raise LookupError("Unknown archive.org item")
            if not set(as_text_list(metadata.get("collection"))) & set(ARCHIVE_COLLECTIONS):
                raise LookupError("archive.org item is not in an allowed collection")
            if ARCHIVE_LICENCE_MARKER not in (as_text(metadata.get("licenseurl")) or "").lower():
                raise LookupError("archive.org item is not marked public domain")
            year = _as_year({"year": metadata.get("year")})
            uploaded = as_text(metadata.get("publicdate")) or "9999"
            if year is None or year > ARCHIVE_MAX_YEAR or uploaded >= ARCHIVE_UPLOADED_BEFORE:
                raise LookupError("archive.org item is outside the public-domain catalogue")
            genres: list[str] = []
            for subject in as_text_list(metadata.get("subject")):
                genres.extend(g.strip() for g in re.split(r"[;,]", subject) if g.strip())
            return {
                "title": as_text(metadata.get("title")) or external_id,
                "year": _as_year(metadata),
                "description": _plain_text(metadata.get("description")),
                "thumbnail": f"https://archive.org/services/img/{external_id}",
                "duration_minutes": _runtime_minutes(metadata.get("runtime")),
                "genres": genres[:8],
                "original_language": as_text(metadata.get("language")),
            }

        host, uuid = split_peertube_external_id(external_id)
        response = await client.get(f"https://{host}/api/v1/videos/{uuid}")
        response.raise_for_status()
        video = response.json() or {}
        category = video.get("category") if isinstance(video.get("category"), dict) else {}
        language = video.get("language") if isinstance(video.get("language"), dict) else {}
        preview = as_text(video.get("previewPath")) or as_text(video.get("thumbnailPath"))
        return {
            "title": as_text(video.get("name")) or "Untitled",
            "year": _peertube_year(video),
            "description": _plain_text(video.get("description")),
            "thumbnail": f"https://{host}{preview}" if preview else None,
            "duration_minutes": (as_int(video.get("duration")) or 0) // 60 or None,
            "genres": [label] if (label := as_text(category.get("label"))) else [],
            "original_language": as_text(language.get("id")),
        }


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
