from fastapi import FastAPI, Depends, Request
from contextlib import asynccontextmanager
import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from typing import Any
import httpx

# Import auth dependency compatible with Bearer header and cookie auth
from auth import get_current_user_id

DATABASE_URL = os.getenv("DATABASE_URL")
ARCHIVE_ADVANCEDSEARCH_URL = "https://archive.org/advancedsearch.php"
DEFAULT_SEARCH_LIMIT = 24
MAX_SEARCH_LIMIT = 50


def _as_text(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _as_year(doc: dict[str, Any]) -> str:
    raw_year = _as_text(doc.get("year"))
    if raw_year:
        return raw_year[:4]
    raw_date = _as_text(doc.get("date"))
    if raw_date and len(raw_date) >= 4:
        return raw_date[:4]
    return "N/A"


def _build_archive_query(query: str) -> str:
    cleaned = " ".join(query.strip().split())
    if not cleaned:
        return "mediatype:(movies)"

    escaped = cleaned.replace('\\', '\\\\').replace('"', '\\"')
    phrase = f'"{escaped}"'
    return f"mediatype:(movies) AND ({phrase} OR title:{phrase} OR description:{phrase} OR creator:{phrase})"


def _truncate_text(text: str | None, max_length: int = 320) -> str | None:
    if not text:
        return None
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_length:
        return collapsed
    return collapsed[: max_length - 3].rstrip() + "..."


def _normalize_archive_doc(doc: dict[str, Any]) -> dict[str, Any]:
    identifier = _as_text(doc.get("identifier")) or ""
    title = _as_text(doc.get("title")) or identifier or "Untitled"
    description = _as_text(doc.get("description"))
    creator = _as_text(doc.get("creator"))

    return {
        "id": identifier,
        "identifier": identifier,
        "title": title,
        "year": _as_year(doc),
        "creator": creator,
        "description": _truncate_text(description),
        "thumbnail": f"https://archive.org/services/img/{identifier}" if identifier else None,
        "archive_url": f"https://archive.org/details/{identifier}" if identifier else None,
    }

@asynccontextmanager
async def lifespan(app: FastAPI):
    retries = 10
    while retries > 0:
        try:
            print(f"Connecting to DB... ({retries} retries left)")
            engine = create_async_engine(DATABASE_URL)
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            print("✅ Database connected successfully.")
            break
        except Exception as e:
            print(f"❌ Database not ready yet: {e}")
            retries -= 1
            await asyncio.sleep(2)
    
    yield

app = FastAPI(lifespan=lifespan, root_path="/api/torrent")

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "torrent-service"}

@app.get("/protected")
async def protected_route(user_id: int = Depends(get_current_user_id)):
    return {
        "message": "You have successfully accessed a protected route on the torrent-service!",
        "user_id": user_id
    }


@app.get("/search")
async def search_movies_archive(q: str = "", page: int = 1, limit: int = DEFAULT_SEARCH_LIMIT):
    """GET /api/torrent/search?q=... — Archive.org-backed movie search."""
    page = max(page, 1)
    limit = max(1, min(limit, MAX_SEARCH_LIMIT))

    archive_query = _build_archive_query(q)
    params: list[tuple[str, Any]] = [
        ("q", archive_query),
        ("rows", limit),
        ("page", page),
        ("output", "json"),
        ("sort[]", "downloads desc"),
        ("fl[]", "identifier"),
        ("fl[]", "title"),
        ("fl[]", "year"),
        ("fl[]", "date"),
        ("fl[]", "description"),
        ("fl[]", "creator"),
    ]

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.get(ARCHIVE_ADVANCEDSEARCH_URL, params=params)
            response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        return {"query": q, "page": page, "limit": limit, "total": 0, "results": [], "error": str(exc)}

    search_response = payload.get("response", {})
    docs = search_response.get("docs", [])
    results = [_normalize_archive_doc(doc) for doc in docs if isinstance(doc, dict)]

    return {
        "query": q,
        "page": page,
        "limit": limit,
        "total": search_response.get("numFound", 0),
        "results": results,
    }
