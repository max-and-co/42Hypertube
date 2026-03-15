import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx
from fastapi import HTTPException

import runtime_state
from config import BUFFER_READY_BYTES, MEDIA_ROOT, SUBTITLES_ROOT, TORRENT_POLL_SECONDS
from schemas import StreamSessionCreate
from services.common import (
    is_subtitle_file,
    is_video_file,
    language_from_name,
    now_iso,
    session_key,
    slugify,
)
from services.db_service import fetch_user_pref_language, update_movie_state

try:
    import libtorrent as lt  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional dependency at runtime
    lt = None


async def _download_subtitle(url: str, target_path: Path) -> bool:
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            target_path.write_bytes(response.content)
        return True
    except Exception:
        return False


async def _prepare_archive_session(session_id: str, external_id: str) -> None:
    async with runtime_state.STREAM_LOCK:
        session = runtime_state.STREAM_SESSIONS[session_id]
        user_id = int(session.get("user_id") or 0)
        movie_id = int(session.get("movie_id") or 0)

    preferred_language = "en"
    if user_id:
        preferred_language = await fetch_user_pref_language(user_id)

    metadata_url = f"https://archive.org/metadata/{external_id}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(metadata_url)
        response.raise_for_status()
        payload = response.json()

    files = payload.get("files", []) if isinstance(payload, dict) else []
    if not isinstance(files, list):
        files = []

    video_candidates: list[tuple[int, str]] = []
    subtitle_tracks_remote: list[dict[str, str]] = []
    for item in files:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name") or "")
        if not name:
            continue

        if is_video_file(name):
            extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            priority = 0
            if extension == "mp4":
                priority = 4
            elif extension == "webm":
                priority = 3
            elif extension == "m4v":
                priority = 2
            else:
                priority = 1
            video_candidates.append((priority, name))

        if is_subtitle_file(name):
            language = language_from_name(name) or "und"
            subtitle_tracks_remote.append(
                {
                    "language": language,
                    "label": language.upper() if language != "und" else "Unknown",
                    "url": f"https://archive.org/download/{external_id}/{name}",
                    "file_name": name,
                }
            )

    if not video_candidates:
        raise RuntimeError("No video file available for archive item")

    video_candidates.sort(key=lambda item: item[0], reverse=True)
    selected_name = video_candidates[0][1]
    stream_url = f"https://archive.org/download/{external_id}/{selected_name}"

    wanted_languages = {"en", preferred_language}
    local_tracks: list[dict[str, str]] = []
    for track in subtitle_tracks_remote:
        language = str(track.get("language") or "und")
        if language not in wanted_languages:
            continue

        file_name = str(track.get("file_name") or "subtitle.vtt")
        extension = Path(file_name).suffix or ".vtt"
        local_name = f"{language}{extension}"
        local_path = SUBTITLES_ROOT / f"archive-{external_id}" / local_name
        downloaded = await _download_subtitle(str(track.get("url") or ""), local_path)
        if downloaded:
            local_tracks.append(
                {
                    "language": language,
                    "label": language.upper(),
                    "url": f"/api/subtitles/{session_id}/{quote(local_name)}",
                    "local_path": str(local_path),
                }
            )

    if not local_tracks:
        for track in subtitle_tracks_remote:
            local_tracks.append(
                {
                    "language": str(track.get("language") or "und"),
                    "label": str(track.get("label") or "Unknown"),
                    "url": str(track.get("url") or ""),
                    "local_path": "",
                }
            )

    await update_movie_state(
        movie_id,
        stream_status="ready",
        subtitle_languages=",".join(sorted({str(track.get('language') or 'und') for track in local_tracks})),
        last_accessed_at=datetime.now(timezone.utc),
    )

    async with runtime_state.STREAM_LOCK:
        session = runtime_state.STREAM_SESSIONS[session_id]
        session["status"] = "ready"
        session["stream_url"] = stream_url
        session["selected_file"] = selected_name
        session["subtitle_tracks"] = local_tracks
        session["default_subtitle_language"] = (
            preferred_language if any(track.get("language") == preferred_language for track in local_tracks) else "en"
        )
        session["updated_at"] = now_iso()


async def _prepare_torrent_session(session_id: str, torrent_hash: str | None) -> None:
    async with runtime_state.STREAM_LOCK:
        session = runtime_state.STREAM_SESSIONS[session_id]
        movie_id = int(session.get("movie_id") or 0)
        external_id = str(session.get("external_id") or "")
        title = str(session.get("title") or external_id or "movie")
        user_id = int(session.get("user_id") or 0)

    if not torrent_hash:
        async with runtime_state.STREAM_LOCK:
            session = runtime_state.STREAM_SESSIONS[session_id]
            session["status"] = "error"
            session["error"] = "Missing torrent hash for yts source"
            session["updated_at"] = now_iso()
        await update_movie_state(movie_id, stream_status="error", last_accessed_at=datetime.now(timezone.utc))
        return

    if lt is None:
        async with runtime_state.STREAM_LOCK:
            session = runtime_state.STREAM_SESSIONS[session_id]
            session["status"] = "error"
            session["error"] = "libtorrent unavailable in container"
            session["updated_at"] = now_iso()
        await update_movie_state(movie_id, stream_status="error", last_accessed_at=datetime.now(timezone.utc))
        return

    target_dir = MEDIA_ROOT / f"yts-{slugify(external_id)}-{slugify(title)}"
    target_dir.mkdir(parents=True, exist_ok=True)

    existing_files = [path for path in target_dir.rglob("*") if path.is_file() and is_video_file(path.name)]
    if existing_files:
        selected = max(existing_files, key=lambda path: path.stat().st_size)
        selected_for_stream = selected
        if selected.suffix.lower() == ".mkv":
            transcoded = target_dir / f"{selected.stem}.mp4"
            if transcoded.exists() and transcoded.stat().st_size > BUFFER_READY_BYTES:
                selected_for_stream = transcoded

        await update_movie_state(
            movie_id,
            stream_status="ready",
            video_path=str(selected_for_stream),
            last_accessed_at=datetime.now(timezone.utc),
            last_watched_at=datetime.now(timezone.utc),
        )

        async with runtime_state.STREAM_LOCK:
            session = runtime_state.STREAM_SESSIONS[session_id]
            session["status"] = "ready"
            session["selected_file"] = str(selected_for_stream)
            session["stream_path"] = str(selected_for_stream)
            session["stream_url"] = f"/api/stream/{session_id}"
            session["progress"] = 1.0
            session["updated_at"] = now_iso()
        return

    magnet_uri = f"magnet:?xt=urn:btih:{torrent_hash}&dn={quote(title)}"
    lt_session = lt.session()  # type: ignore[union-attr]
    lt_session.listen_on(6881, 6891)
    params = {
        "save_path": str(target_dir),
        "storage_mode": lt.storage_mode_t.storage_mode_sparse,  # type: ignore[union-attr]
    }
    handle = lt.add_magnet_uri(lt_session, magnet_uri, params)  # type: ignore[union-attr]

    selected_video: Path | None = None
    preferred_language = await fetch_user_pref_language(user_id) if user_id else "en"

    async with runtime_state.STREAM_LOCK:
        session = runtime_state.STREAM_SESSIONS[session_id]
        session["status"] = "buffering"
        session["updated_at"] = now_iso()
    await update_movie_state(movie_id, stream_status="buffering", last_accessed_at=datetime.now(timezone.utc))

    while True:
        if handle.has_metadata():
            torrent_info = handle.get_torrent_info()
            file_storage = torrent_info.files()

            candidates: list[tuple[int, Path]] = []
            subtitle_candidates: list[Path] = []
            for index in range(file_storage.num_files()):
                relative = Path(file_storage.file_path(index))
                absolute = target_dir / relative
                if is_video_file(relative.name):
                    priority = 10 if relative.suffix.lower() == ".mp4" else 5
                    candidates.append((priority + int(file_storage.file_size(index) / (1024 * 1024)), absolute))
                if is_subtitle_file(relative.name):
                    subtitle_candidates.append(absolute)

            if candidates and selected_video is None:
                candidates.sort(key=lambda item: item[0], reverse=True)
                selected_video = candidates[0][1]
                async with runtime_state.STREAM_LOCK:
                    session = runtime_state.STREAM_SESSIONS[session_id]
                    session["selected_file"] = str(selected_video)

            if subtitle_candidates:
                subtitle_tracks: list[dict[str, str]] = []
                for subtitle_path in subtitle_candidates:
                    if not subtitle_path.exists():
                        continue
                    language = language_from_name(subtitle_path.name) or "und"
                    subtitle_tracks.append(
                        {
                            "language": language,
                            "label": language.upper() if language != "und" else "Unknown",
                            "url": f"/api/subtitles/{session_id}/{quote(subtitle_path.name)}",
                            "local_path": str(subtitle_path),
                        }
                    )

                if subtitle_tracks:
                    subtitle_tracks.sort(
                        key=lambda track: 0 if track["language"] == "en" else (1 if track["language"] == preferred_language else 2)
                    )
                    async with runtime_state.STREAM_LOCK:
                        session = runtime_state.STREAM_SESSIONS[session_id]
                        session["subtitle_tracks"] = subtitle_tracks
                        session["default_subtitle_language"] = (
                            preferred_language
                            if any(track["language"] == preferred_language for track in subtitle_tracks)
                            else "en"
                        )
                    await update_movie_state(
                        movie_id,
                        subtitle_languages=",".join(sorted({track["language"] for track in subtitle_tracks})),
                    )

        status = handle.status()
        progress = float(status.progress)
        async with runtime_state.STREAM_LOCK:
            session = runtime_state.STREAM_SESSIONS.get(session_id)
            if not session:
                return
            session["progress"] = progress
            session["updated_at"] = now_iso()

        if selected_video and selected_video.exists() and selected_video.stat().st_size >= BUFFER_READY_BYTES:
            stream_file = selected_video
            if selected_video.suffix.lower() == ".mkv":
                transcoded = target_dir / f"{selected_video.stem}.mp4"
                if not transcoded.exists():
                    await update_movie_state(movie_id, stream_status="transcoding")
                    async with runtime_state.STREAM_LOCK:
                        session = runtime_state.STREAM_SESSIONS[session_id]
                        session["status"] = "transcoding"
                        session["updated_at"] = now_iso()

                    process = await asyncio.create_subprocess_exec(
                        "ffmpeg",
                        "-y",
                        "-i",
                        str(selected_video),
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-c:a",
                        "aac",
                        "-movflags",
                        "+faststart",
                        str(transcoded),
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await process.wait()

                if transcoded.exists() and transcoded.stat().st_size > BUFFER_READY_BYTES:
                    stream_file = transcoded

            await update_movie_state(
                movie_id,
                stream_status="ready",
                video_path=str(stream_file),
                last_accessed_at=datetime.now(timezone.utc),
                last_watched_at=datetime.now(timezone.utc),
            )
            async with runtime_state.STREAM_LOCK:
                session = runtime_state.STREAM_SESSIONS[session_id]
                session["status"] = "ready"
                session["stream_path"] = str(stream_file)
                session["stream_url"] = f"/api/stream/{session_id}"
                session["updated_at"] = now_iso()

            if status.is_seeding:
                break

        if status.is_seeding:
            break

        await asyncio.sleep(TORRENT_POLL_SECONDS)

    await update_movie_state(movie_id, stream_status="ready", last_accessed_at=datetime.now(timezone.utc))


async def _prepare_stream_session(session_id: str) -> None:
    try:
        async with runtime_state.STREAM_LOCK:
            session = runtime_state.STREAM_SESSIONS.get(session_id)
            if not session:
                return

            movie_id = int(session.get("movie_id") or 0)
            session["status"] = "preparing"
            session["updated_at"] = now_iso()
            source = str(session.get("source") or "")
            external_id = str(session.get("external_id") or "")
            torrent_hash = session.get("torrent_hash")

        await update_movie_state(movie_id, stream_status="preparing", last_accessed_at=datetime.now(timezone.utc))

        if source == "archive":
            await _prepare_archive_session(session_id=session_id, external_id=external_id)
            return

        if source == "yts":
            await _prepare_torrent_session(session_id=session_id, torrent_hash=torrent_hash)
            return

        raise RuntimeError(f"Unsupported source '{source}'")
    except Exception as exc:
        async with runtime_state.STREAM_LOCK:
            session = runtime_state.STREAM_SESSIONS.get(session_id)
            if session is not None:
                movie_id = int(session.get("movie_id") or 0)
                session["status"] = "error"
                session["error"] = str(exc)
                session["updated_at"] = now_iso()
            else:
                movie_id = 0

        if movie_id:
            await update_movie_state(movie_id, stream_status="error", last_accessed_at=datetime.now(timezone.utc))
    finally:
        runtime_state.TORRENT_RUNNERS.pop(session_id, None)


async def create_stream_session(payload: StreamSessionCreate, user_id: int) -> dict[str, Any]:
    source = payload.source.strip().lower()
    external_id = payload.external_id.strip()
    if not source or not external_id:
        raise HTTPException(status_code=400, detail="source and external_id are required")

    key = session_key(source, external_id)
    async with runtime_state.STREAM_LOCK:
        existing_id = runtime_state.STREAM_INDEX.get(key)
        if existing_id and existing_id in runtime_state.STREAM_SESSIONS:
            existing = runtime_state.STREAM_SESSIONS[existing_id]
            existing["updated_at"] = now_iso()
            return existing

        session_id = str(uuid4())
        session = {
            "session_id": session_id,
            "movie_id": payload.movie_id,
            "user_id": user_id,
            "source": source,
            "external_id": external_id,
            "title": payload.title,
            "torrent_hash": payload.torrent_hash,
            "status": "queued",
            "progress": 0.0,
            "stream_url": None,
            "selected_file": None,
            "subtitle_tracks": [],
            "default_subtitle_language": "en",
            "error": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        runtime_state.STREAM_SESSIONS[session_id] = session
        runtime_state.STREAM_INDEX[key] = session_id

    task = asyncio.create_task(_prepare_stream_session(session_id))
    runtime_state.TORRENT_RUNNERS[session_id] = task
    return session


async def get_stream_session(session_id: str) -> dict[str, Any] | None:
    async with runtime_state.STREAM_LOCK:
        return runtime_state.STREAM_SESSIONS.get(session_id)


async def get_stream_target(session_id: str) -> tuple[str | None, str | None, str | None]:
    async with runtime_state.STREAM_LOCK:
        session = runtime_state.STREAM_SESSIONS.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Stream session not found")

        stream_url = session.get("stream_url")
        stream_path = session.get("stream_path")
        status_value = session.get("status")

    return (
        str(stream_url) if stream_url else None,
        str(stream_path) if stream_path else None,
        str(status_value) if status_value else None,
    )


async def list_subtitles(session_id: str) -> dict[str, Any]:
    async with runtime_state.STREAM_LOCK:
        session = runtime_state.STREAM_SESSIONS.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Stream session not found")
        return {
            "session_id": session_id,
            "subtitle_tracks": session.get("subtitle_tracks") or [],
        }


async def get_subtitle_local_path(session_id: str, subtitle_name: str) -> Path | None:
    safe_name = Path(subtitle_name).name
    async with runtime_state.STREAM_LOCK:
        session = runtime_state.STREAM_SESSIONS.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Stream session not found")
        tracks = session.get("subtitle_tracks") or []

    for track in tracks:
        if not isinstance(track, dict):
            continue
        local_path = str(track.get("local_path") or "")
        if not local_path:
            continue
        candidate = Path(local_path)
        if candidate.name == safe_name:
            return candidate

    return None


async def cancel_all_stream_tasks() -> None:
    tasks = list(runtime_state.TORRENT_RUNNERS.values())
    for task in tasks:
        task.cancel()

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    runtime_state.TORRENT_RUNNERS.clear()
