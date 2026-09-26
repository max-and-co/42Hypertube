"""IMDb ratings for search results (subject III.2.2: each thumbnail shows its
IMDb rating, from OMDb or TMDb, when available).

Search sources (archive.org, PeerTube) carry no rating, so each result title is
looked up on OMDb, then TMDb as a fallback. Answers - including "not found" -
are cached in the rating_lookup_cache table, so a title costs one API call per
week at most and the free OMDb quota is not burnt by infinite scroll.
"""
import asyncio
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models import RatingLookupCache

logger = logging.getLogger(__name__)

OMDB_API_KEY = os.getenv("OMDB_API_KEY", "").strip()
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()
OMDB_BASE_URL = "https://www.omdbapi.com/"
TMDB_BASE_URL = "https://api.themoviedb.org/3"

LOOKUP_CONCURRENCY = 8
LOOKUP_TIMEOUT_SECONDS = 4.0
# A page of thumbnails never waits longer than this for ratings; unfinished
# lookups are simply retried on the next request.
PAGE_BUDGET_SECONDS = 6.0
NOT_FOUND_TTL = timedelta(days=7)
TMDB_MIN_VOTES = 20

_NOISE = re.compile(
    r"\b(full movie|full film|feature film|public domain|hd|720p|1080p|4k|restored|remastered|colorized)\b",
    re.IGNORECASE,
)
_BRACKETS = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
_YEAR = re.compile(r"\b(18[89]\d|19\d\d|20[0-3]\d)\b")


def normalize_title(title: str, year: int | None) -> tuple[str, int | None]:
    """'Nosferatu (1922) [HD]' -> ('Nosferatu', 1922)."""
    if year is None:
        for group in re.findall(r"[\(\[]([^\)\]]*)[\)\]]", title):
            match = _YEAR.search(group)
            if match:
                year = int(match.group(1))
                break
    cleaned = _BRACKETS.sub(" ", title)
    cleaned = _NOISE.sub(" ", cleaned)
    # "The General - 1926" -> "The General", year 1926
    trailing = re.search(r"[\s\-|:,]+(18[89]\d|19\d\d|20[0-3]\d)\s*$", cleaned)
    if trailing:
        year = year or int(trailing.group(1))
        cleaned = cleaned[: trailing.start()]
    cleaned = re.sub(r"\s+[-|:]\s*$", "", " ".join(cleaned.split()))
    return cleaned.strip(" -|:"), year


def cache_key(title: str, year: int | None) -> str:
    return f"{title.lower()}|{year or ''}"[:300]


def _as_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


async def _omdb(client: httpx.AsyncClient, title: str, year: int | None) -> tuple[str | None, float | None] | None:
    if not OMDB_API_KEY:
        return None
    params = {"apikey": OMDB_API_KEY, "t": title, "type": "movie", "r": "json"}
    if year:
        params["y"] = str(year)
    response = await client.get(OMDB_BASE_URL, params=params)
    response.raise_for_status()
    payload = response.json()
    if payload.get("Response") != "True":
        return None
    rating = _as_float(payload.get("imdbRating"))
    if rating is None:
        return None
    return payload.get("imdbID"), rating


async def _tmdb(client: httpx.AsyncClient, title: str, year: int | None) -> tuple[str | None, float | None] | None:
    if not TMDB_API_KEY:
        return None
    params = {"api_key": TMDB_API_KEY, "query": title}
    if year:
        params["year"] = str(year)
    response = await client.get(f"{TMDB_BASE_URL}/search/movie", params=params)
    response.raise_for_status()
    for result in response.json().get("results") or []:
        # Only an exact title match with enough votes: a fuzzy search on a
        # random clip title would otherwise attach some unrelated film's grade.
        names = {str(result.get("title") or "").lower(), str(result.get("original_title") or "").lower()}
        if title.lower() in names and int(result.get("vote_count") or 0) >= TMDB_MIN_VOTES:
            return None, _as_float(result.get("vote_average"))
    return None


async def _lookup_one(client: httpx.AsyncClient, gate: asyncio.Semaphore, title: str, year: int | None):
    failed = False
    async with gate:
        for provider in (_omdb, _tmdb):
            try:
                found = await asyncio.wait_for(provider(client, title, year), LOOKUP_TIMEOUT_SECONDS)
            except (httpx.HTTPError, asyncio.TimeoutError, ValueError):
                failed = True
                continue
            if found is not None:
                return found
    if failed:
        # A provider was unreachable: raise so no false "not found" is cached.
        raise RuntimeError(f"rating lookup failed for {title!r}")
    return None


async def ratings_for(db: AsyncSession, items: list[tuple[str, int | None]]) -> dict[str, tuple[str | None, float | None]]:
    """Map cache_key -> (imdb_id, rating) for every (title, year) that has one."""
    if not OMDB_API_KEY and not TMDB_API_KEY:
        return {}

    wanted: dict[str, tuple[str, int | None]] = {}
    for raw_title, raw_year in items:
        title, year = normalize_title(raw_title or "", raw_year)
        if len(title) >= 2:
            wanted.setdefault(cache_key(title, year), (title, year))
    if not wanted:
        return {}

    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(select(RatingLookupCache).where(RatingLookupCache.key.in_(list(wanted))))
    ).scalars().all()

    ratings: dict[str, tuple[str | None, float | None]] = {}
    for row in rows:
        if row.rating is not None:
            ratings[row.key] = (row.imdb_id, row.rating)
            wanted.pop(row.key, None)
        elif row.fetched_at and now - row.fetched_at < NOT_FOUND_TTL:
            wanted.pop(row.key, None)

    if not wanted:
        return ratings

    gate = asyncio.Semaphore(LOOKUP_CONCURRENCY)
    async with httpx.AsyncClient(timeout=LOOKUP_TIMEOUT_SECONDS) as client:
        tasks = {
            asyncio.create_task(_lookup_one(client, gate, title, year)): key
            for key, (title, year) in wanted.items()
        }
        done, pending = await asyncio.wait(tasks, timeout=PAGE_BUDGET_SECONDS)
        for task in pending:
            task.cancel()

    to_store = []
    for task in done:
        key = tasks[task]
        if task.exception() is not None:
            continue
        found = task.result()
        imdb_id, rating = found if found else (None, None)
        if rating is not None:
            ratings[key] = (imdb_id, rating)
        to_store.append({"key": key, "imdb_id": imdb_id, "rating": rating, "fetched_at": now})

    if to_store:
        stmt = insert(RatingLookupCache).values(to_store)
        stmt = stmt.on_conflict_do_update(
            index_elements=["key"],
            set_={"imdb_id": stmt.excluded.imdb_id, "rating": stmt.excluded.rating, "fetched_at": stmt.excluded.fetched_at},
        )
        await db.execute(stmt)
        await db.commit()

    return ratings


def rating_of(ratings: dict[str, tuple[str | None, float | None]], title: str, year: int | None):
    clean, clean_year = normalize_title(title or "", year)
    return ratings.get(cache_key(clean, clean_year), (None, None))
