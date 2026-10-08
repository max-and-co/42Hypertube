import logging
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse

from auth import get_current_user_id
from config import DEFAULT_SEARCH_LIMIT, MAX_SEARCH_LIMIT
from lifecycle import lifespan
from schemas import StreamSessionCreate
from services.media_service import build_live_response, build_streaming_response, subtitle_media_type
from services.search_service import (
    ProviderError,
    check_archive_connectivity,
    check_omdb_connectivity,
    check_peertube_connectivity,
    fetch_details,
    parse_cursor,
    search_movies,
)
from services.session_service import (
    create_stream_session,
    get_stream_session,
    get_stream_target,
    get_subtitle_local_path,
    list_subtitles,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

# No interactive docs: only the routes below answer (subject III.4).
app = FastAPI(lifespan=lifespan, root_path="/api/torrent", docs_url=None, redoc_url=None, openapi_url=None)


def require_user(request: Request) -> int:
    """A real logged-in user (service tokens, subject 0, may only search)."""
    user_id = get_current_user_id(request)
    if user_id <= 0:
        raise HTTPException(status_code=403, detail="A user session is required")
    return user_id


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "torrent-service"}


@app.get("/health/providers")
async def providers_health():
    return {
        "status": "ok",
        "providers": {
            "archive": await check_archive_connectivity(),
            "peertube": await check_peertube_connectivity(),
            "omdb": await check_omdb_connectivity(),
        },
    }


@app.get("/search")
async def search_endpoint(
    request: Request,
    q: str = Query("", max_length=100),
    page: int = Query(1, ge=1, le=500),
    limit: int = Query(DEFAULT_SEARCH_LIMIT, ge=1, le=MAX_SEARCH_LIMIT),
    source: Literal["all", "archive", "peertube"] = "all",
    sort_by: Literal["downloads", "title", "year"] = "downloads",
    sort_dir: Literal["asc", "desc"] = "desc",
    genre: str | None = Query(None, max_length=50),
    year_min: int | None = Query(None, ge=1870, le=2100),
    year_max: int | None = Query(None, ge=1870, le=2100),
    cursor: str | None = Query(None, max_length=1000),
):
    get_current_user_id(request)
    try:
        parse_cursor(cursor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        return await search_movies(
            q=q,
            page=page,
            limit=limit,
            source=source,
            sort_by=sort_by,
            sort_dir=sort_dir,
            genre=genre,
            year_min=year_min,
            year_max=year_max,
            cursor=cursor,
        )
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/details")
async def details_endpoint(
    request: Request,
    source: Literal["archive", "peertube"],
    external_id: str = Query(..., min_length=1, max_length=128),
):
    """Film metadata read from its source (used by user-service's ingest)."""
    get_current_user_id(request)
    try:
        return await fetch_details(source, external_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (LookupError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=404, detail="Video not found at its source") from exc


@app.post("/sessions")
async def create_session_endpoint(payload: StreamSessionCreate, request: Request):
    user_id = require_user(request)
    return await create_stream_session(payload.source, payload.external_id, user_id)


@app.get("/sessions/{session_id}")
async def get_session_endpoint(session_id: str, request: Request):
    require_user(request)
    session = await get_stream_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Stream session not found")
    return session


@app.get("/stream/{session_id}")
async def open_stream(session_id: str, request: Request):
    require_user(request)
    kind, target = await get_stream_target(session_id)
    if kind == "live":
        return build_live_response(target)
    return build_streaming_response(target, request.headers.get("range"))


@app.get("/subtitles/{session_id}")
async def list_subtitles_endpoint(session_id: str, request: Request):
    require_user(request)
    return await list_subtitles(session_id)


@app.get("/subtitles/{session_id}/{subtitle_name}")
async def get_subtitle_file(session_id: str, subtitle_name: str, request: Request):
    require_user(request)
    subtitle_path = await get_subtitle_local_path(session_id, subtitle_name)
    if subtitle_path is None or not subtitle_path.exists():
        raise HTTPException(status_code=404, detail="Subtitle file not found")

    return FileResponse(
        path=str(subtitle_path),
        media_type=subtitle_media_type(subtitle_path),
        headers={"X-Content-Type-Options": "nosniff"},
    )
