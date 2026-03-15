from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

from auth import get_current_user_id
from config import DEFAULT_SEARCH_LIMIT
from lifecycle import lifespan
from schemas import StreamSessionCreate
from services.media_service import build_streaming_response, subtitle_media_type
from services.search_service import check_omdb_connectivity, check_yts_connectivity, search_movies
from services.session_service import (
    create_stream_session,
    get_stream_session,
    get_stream_target,
    get_subtitle_local_path,
    list_subtitles,
)

app = FastAPI(lifespan=lifespan, root_path="/api/torrent")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "torrent-service"}


@app.get("/health/providers")
async def providers_health():
    yts = await check_yts_connectivity()
    omdb = await check_omdb_connectivity()
    return {
        "status": "ok",
        "providers": {
            "yts": yts,
            "omdb": omdb,
        },
    }


@app.get("/protected")
async def protected_route(user_id: int = Depends(get_current_user_id)):
    return {
        "message": "You have successfully accessed a protected route on the torrent-service!",
        "user_id": user_id,
    }


@app.get("/search")
async def search_endpoint(
    q: str = "",
    page: int = 1,
    limit: int = DEFAULT_SEARCH_LIMIT,
    sort_by: str = "downloads",
    sort_dir: str = "desc",
    genre: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    imdb_min: float | None = None,
):
    return await search_movies(
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


@app.post("/sessions")
async def create_session_endpoint(payload: StreamSessionCreate, request: Request):
    user_id = get_current_user_id(request)
    return await create_stream_session(payload, user_id)


@app.get("/sessions/{session_id}")
async def get_session_endpoint(session_id: str, request: Request):
    get_current_user_id(request)
    session = await get_stream_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Stream session not found")
    return session


@app.get("/stream/{session_id}")
async def open_stream(session_id: str, request: Request):
    stream_url, stream_path, status_value = await get_stream_target(session_id)

    if stream_path:
        path = Path(stream_path)
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="Local stream file missing")
        return build_streaming_response(path, request.headers.get("range"))

    if not stream_url:
        raise HTTPException(status_code=409, detail=f"Stream not ready (status={status_value})")

    return RedirectResponse(url=stream_url, status_code=307)


@app.get("/subtitles/{session_id}")
async def list_subtitles_endpoint(session_id: str):
    return await list_subtitles(session_id)


@app.get("/subtitles/{session_id}/{subtitle_name}")
async def get_subtitle_file(session_id: str, subtitle_name: str):
    subtitle_path = await get_subtitle_local_path(session_id, subtitle_name)
    if subtitle_path is None or not subtitle_path.exists():
        raise HTTPException(status_code=404, detail="Subtitle file not found")

    return FileResponse(
        path=str(subtitle_path),
        media_type=subtitle_media_type(subtitle_path),
        filename=subtitle_path.name,
    )
