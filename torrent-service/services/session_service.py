import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx
from fastapi import HTTPException

import runtime_state
from config import (
    ARCHIVE_METADATA_URL,
    BUFFER_READY_BYTES,
    MEDIA_ROOT,
    METADATA_TIMEOUT_SECONDS,
    STALL_TIMEOUT_SECONDS,
    TORRENT_POLL_SECONDS,
)
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
from services.search_service import split_peertube_external_id

try:
    import libtorrent as lt  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional dependency at runtime
    lt = None


logger = logging.getLogger(__name__)

# Browser-playable formats rank highest. Archive.org items often ship a huge
# .mpeg master alongside a much smaller .mp4 derivative; without this ranking a
# size-based pick would choose the multi-gigabyte master we cannot stream.
_FORMAT_RANK = {".mp4": 3, ".webm": 3, ".m4v": 2, ".ogv": 2, ".mkv": 1}

_PRIORITY_SKIP = 0
_PRIORITY_SUBTITLE = 4
_PRIORITY_VIDEO = 7


def _format_rank(name: str) -> int:
    return _FORMAT_RANK.get(Path(name).suffix.lower(), 0)


# ── Magnet resolution ─────────────────────────────────────────────────────────


async def _fetch_archive_torrent(external_id: str) -> bytes:
    """Download the item's .torrent.

    We deliberately do NOT build a magnet from the `btih` archive.org
    publishes. A magnet carries only the infohash and trackers, while the
    .torrent additionally carries `url-list` - the BEP-19 webseeds pointing at
    archive.org's own HTTP servers. Most archive items have no peers willing to
    serve metadata, so without those webseeds the download stalls forever at
    "buffering".
    """
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(f"{ARCHIVE_METADATA_URL}/{external_id}")
        response.raise_for_status()
        payload = response.json()

        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected archive.org metadata for '{external_id}'")
        if payload.get("is_dark"):
            raise RuntimeError(f"Archive item '{external_id}' is not publicly available")

        files = payload.get("files")
        if not isinstance(files, list):
            files = []

        torrent_name = ""
        for item in files:
            if isinstance(item, dict) and str(item.get("name") or "").endswith(".torrent"):
                torrent_name = str(item["name"])
                break

        if not torrent_name:
            raise RuntimeError(f"Archive item '{external_id}' does not publish a torrent")

        torrent = await client.get(
            f"https://archive.org/download/{quote(external_id)}/{quote(torrent_name)}"
        )
        torrent.raise_for_status()
        return torrent.content


async def _resolve_peertube_magnet(external_id: str) -> str:
    """Every PeerTube video file exposes a ready-made magnet with a webseed."""
    host, uuid = split_peertube_external_id(external_id)
    if not host or not uuid:
        raise RuntimeError(f"Malformed peertube id '{external_id}'")

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        response = await client.get(f"https://{host}/api/v1/videos/{uuid}")
        response.raise_for_status()
        payload = response.json()

    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected PeerTube payload for '{external_id}'")

    candidates: list[dict[str, Any]] = []
    for entry in payload.get("files") or []:
        if isinstance(entry, dict):
            candidates.append(entry)
    for playlist in payload.get("streamingPlaylists") or []:
        if isinstance(playlist, dict):
            for entry in playlist.get("files") or []:
                if isinstance(entry, dict):
                    candidates.append(entry)

    def resolution_of(entry: dict[str, Any]) -> int:
        resolution = entry.get("resolution")
        if isinstance(resolution, dict):
            try:
                return int(resolution.get("id") or 0)
            except (TypeError, ValueError):
                return 0
        return 0

    # Highest resolution that stays reasonable to buffer.
    playable = [entry for entry in candidates if entry.get("magnetUri")]
    if not playable:
        raise RuntimeError(f"PeerTube video '{external_id}' exposes no torrent")

    within_budget = [entry for entry in playable if resolution_of(entry) <= 1080]
    chosen = max(within_budget or playable, key=resolution_of)
    return str(chosen["magnetUri"])


async def build_torrent_params(source: str, external_id: str, target_dir: Path):
    """Produce libtorrent add-params for a source.

    archive  -> the published .torrent, so its webseeds come with it
    peertube -> the API's magnetUri, which already embeds a `ws=` webseed
    """
    if source == "archive":
        data = await _fetch_archive_torrent(external_id)
        torrent_path = target_dir / f"{slugify(external_id)}.torrent"
        torrent_path.write_bytes(data)
        params = lt.add_torrent_params()
        params.ti = lt.torrent_info(str(torrent_path))
    elif source == "peertube":
        params = lt.parse_magnet_uri(await _resolve_peertube_magnet(external_id))
    else:
        raise RuntimeError(f"Unsupported source '{source}'")

    params.save_path = str(target_dir)
    params.storage_mode = lt.storage_mode_t.storage_mode_sparse
    return params


# ── Subtitles ─────────────────────────────────────────────────────────────────

# SubRip in the wild uses either milliseconds or centiseconds, and either a
# comma or a dot. WebVTT requires exactly HH:MM:SS.mmm or the cue is dropped.
_SRT_TIMESTAMP = re.compile(r"(\d{1,2}:\d{2}:\d{2})[,.](\d{1,3})")


def _srt_to_vtt(path: Path) -> Path:
    """Browsers only read WebVTT; archive.org ships SubRip. Convert alongside."""
    target = path.with_suffix(".vtt")
    if target.exists():
        return target
    try:
        body = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return path
    converted = _SRT_TIMESTAMP.sub(lambda m: f"{m.group(1)}.{m.group(2).ljust(3, '0')}", body)
    target.write_text("WEBVTT\n\n" + converted.lstrip("﻿"), encoding="utf-8")
    return target


def _subtitle_track(path: Path, session_id: str) -> dict[str, str]:
    usable = _srt_to_vtt(path) if path.suffix.lower() == ".srt" else path
    language = language_from_name(path.name) or "und"
    return {
        "language": language,
        "label": language.upper() if language != "und" else "Unknown",
        "url": f"/api/subtitles/{session_id}/{quote(usable.name)}",
        "local_path": str(usable),
    }


async def _publish_subtitles(session_id: str, movie_id: int, paths: list[Path], preferred_language: str) -> None:
    tracks = [_subtitle_track(path, session_id) for path in paths if path.exists()]
    if not tracks:
        return

    tracks.sort(
        key=lambda track: 0 if track["language"] == preferred_language else (1 if track["language"] == "en" else 2)
    )
    async with runtime_state.STREAM_LOCK:
        session = runtime_state.STREAM_SESSIONS.get(session_id)
        if session is None:
            return
        session["subtitle_tracks"] = tracks
        session["default_subtitle_language"] = (
            preferred_language
            if any(track["language"] == preferred_language for track in tracks)
            else tracks[0]["language"]
        )
    await update_movie_state(
        movie_id,
        subtitle_languages=",".join(sorted({track["language"] for track in tracks})),
    )


# ── Torrent streaming ─────────────────────────────────────────────────────────


async def _mark_error(session_id: str, movie_id: int, message: str) -> None:
    async with runtime_state.STREAM_LOCK:
        session = runtime_state.STREAM_SESSIONS.get(session_id)
        if session is not None:
            session["status"] = "error"
            session["error"] = message
            session["updated_at"] = now_iso()
    if movie_id:
        await update_movie_state(movie_id, stream_status="error", last_accessed_at=datetime.now(timezone.utc))


async def _transcode_to_mp4(source_path: Path, target_dir: Path, session_id: str, movie_id: int) -> Path:
    transcoded = target_dir / f"{source_path.stem}.mp4"
    if transcoded.exists() and transcoded.stat().st_size > BUFFER_READY_BYTES:
        return transcoded

    await update_movie_state(movie_id, stream_status="transcoding")
    async with runtime_state.STREAM_LOCK:
        session = runtime_state.STREAM_SESSIONS.get(session_id)
        if session is not None:
            session["status"] = "transcoding"
            session["updated_at"] = now_iso()

    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-i", str(source_path),
        "-c:v", "libx264", "-preset", "veryfast",
        "-c:a", "aac", "-movflags", "+faststart",
        str(transcoded),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        stdout_tail = (stdout or b"").decode(errors="ignore")[-800:]
        stderr_tail = (stderr or b"").decode(errors="ignore")[-800:]
        raise RuntimeError(
            "ffmpeg failed while transcoding to mp4 "
            f"(code={process.returncode}, stdout_tail={stdout_tail!r}, stderr_tail={stderr_tail!r})"
        )
    return transcoded


async def _mark_ready(session_id: str, movie_id: int, stream_file: Path) -> None:
    now = datetime.now(timezone.utc)
    await update_movie_state(
        movie_id,
        stream_status="ready",
        video_path=str(stream_file),
        last_accessed_at=now,
        last_watched_at=now,
    )
    async with runtime_state.STREAM_LOCK:
        session = runtime_state.STREAM_SESSIONS.get(session_id)
        if session is None:
            return
        session["status"] = "ready"
        session["selected_file"] = str(stream_file)
        session["stream_path"] = str(stream_file)
        session["stream_url"] = f"/api/stream/{session_id}"
        session["updated_at"] = now_iso()


async def _prepare_torrent_session(session_id: str) -> None:
    async with runtime_state.STREAM_LOCK:
        session = runtime_state.STREAM_SESSIONS[session_id]
        movie_id = int(session.get("movie_id") or 0)
        external_id = str(session.get("external_id") or "")
        source = str(session.get("source") or "")
        title = str(session.get("title") or external_id or "movie")
        user_id = int(session.get("user_id") or 0)

    if lt is None:
        await _mark_error(session_id, movie_id, "libtorrent unavailable in container")
        return

    preferred_language = await fetch_user_pref_language(user_id) if user_id else "en"
    target_dir = MEDIA_ROOT / f"{slugify(source)}-{slugify(external_id)}-{slugify(title)}"
    target_dir.mkdir(parents=True, exist_ok=True)

    # Already downloaded on a previous run: serve straight from disk.
    existing = [p for p in target_dir.rglob("*") if p.is_file() and is_video_file(p.name)]
    if existing:
        selected = max(existing, key=lambda p: (_format_rank(p.name), p.stat().st_size))
        if _format_rank(selected.name) < 2:
            selected = await _transcode_to_mp4(selected, target_dir, session_id, movie_id)
        await _publish_subtitles(
            session_id,
            movie_id,
            [p for p in target_dir.rglob("*") if p.is_file() and is_subtitle_file(p.name)],
            preferred_language,
        )
        async with runtime_state.STREAM_LOCK:
            runtime_state.STREAM_SESSIONS[session_id]["progress"] = 1.0
        await _mark_ready(session_id, movie_id, selected)
        return

    params = await build_torrent_params(source, external_id, target_dir)
    lt_session = lt.session()
    handle = lt_session.add_torrent(params)

    async with runtime_state.STREAM_LOCK:
        session = runtime_state.STREAM_SESSIONS[session_id]
        session["status"] = "buffering"
        session["updated_at"] = now_iso()
    await update_movie_state(movie_id, stream_status="buffering", last_accessed_at=datetime.now(timezone.utc))

    selected_video: Path | None = None
    subtitle_paths: list[Path] = []
    prioritised = False
    ready = False

    started_at = asyncio.get_running_loop().time()
    last_progress_at = started_at
    last_done = 0

    try:
        while True:
            status = handle.status()
            now = asyncio.get_running_loop().time()

            if not status.has_metadata and now - started_at > METADATA_TIMEOUT_SECONDS:
                raise RuntimeError(
                    "No peer or webseed answered with torrent metadata "
                    f"within {int(METADATA_TIMEOUT_SECONDS)}s"
                )

            done = int(getattr(status, "total_done", 0) or 0)
            if done > last_done:
                last_done = done
                last_progress_at = now
            elif not ready and now - last_progress_at > STALL_TIMEOUT_SECONDS:
                raise RuntimeError(
                    f"Download stalled: no data received for {int(STALL_TIMEOUT_SECONDS)}s"
                )

            if status.has_metadata and not prioritised:
                torrent_info = handle.torrent_file()
                file_storage = torrent_info.files()

                videos: list[tuple[int, int, int]] = []  # (rank, size, index)
                subtitle_indices: list[int] = []
                for index in range(file_storage.num_files()):
                    name = Path(file_storage.file_path(index)).name
                    if is_video_file(name):
                        videos.append((_format_rank(name), file_storage.file_size(index), index))
                    elif is_subtitle_file(name):
                        subtitle_indices.append(index)

                if not videos:
                    raise RuntimeError("Torrent contains no playable video file")

                videos.sort(reverse=True)
                chosen_index = videos[0][2]
                selected_video = target_dir / file_storage.file_path(chosen_index)
                subtitle_paths = [target_dir / file_storage.file_path(i) for i in subtitle_indices]

                # Only fetch what we actually stream. Archive.org torrents bundle
                # every derivative (24 files / 4 GB for one 483 MB mp4).
                priorities = [_PRIORITY_SKIP] * file_storage.num_files()
                priorities[chosen_index] = _PRIORITY_VIDEO
                for index in subtitle_indices:
                    priorities[index] = _PRIORITY_SUBTITLE
                handle.prioritize_files(priorities)

                async with runtime_state.STREAM_LOCK:
                    runtime_state.STREAM_SESSIONS[session_id]["selected_file"] = str(selected_video)
                prioritised = True
                logger.info(
                    "Selected torrent file",
                    extra={"session_id": session_id, "file": str(selected_video), "skipped": len(priorities) - 1},
                )

            async with runtime_state.STREAM_LOCK:
                session = runtime_state.STREAM_SESSIONS.get(session_id)
                if session is None:
                    return
                session["progress"] = float(status.progress)
                session["updated_at"] = now_iso()

            if subtitle_paths:
                downloaded = [p for p in subtitle_paths if p.exists()]
                if downloaded:
                    await _publish_subtitles(session_id, movie_id, downloaded, preferred_language)
                    subtitle_paths = []

            if (
                not ready
                and selected_video is not None
                and selected_video.exists()
                and selected_video.stat().st_size >= BUFFER_READY_BYTES
            ):
                stream_file = selected_video
                if _format_rank(selected_video.name) < 2:
                    stream_file = await _transcode_to_mp4(selected_video, target_dir, session_id, movie_id)
                await _mark_ready(session_id, movie_id, stream_file)
                ready = True

            if status.is_seeding:
                break

            await asyncio.sleep(TORRENT_POLL_SECONDS)
    finally:
        lt_session.remove_torrent(handle)
        lt_session.pause()

    await update_movie_state(movie_id, stream_status="ready", last_accessed_at=datetime.now(timezone.utc))


async def _prepare_stream_session(session_id: str) -> None:
    movie_id = 0
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
            title = str(session.get("title") or external_id or "movie")

        await update_movie_state(movie_id, stream_status="preparing", last_accessed_at=datetime.now(timezone.utc))

        await _prepare_torrent_session(session_id)
    except Exception as exc:
        logger.exception("Stream session failed", extra={"session_id": session_id})
        await _mark_error(session_id, movie_id, str(exc))
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
            "status": "queued",
            "progress": 0.0,
            "stream_url": None,
            "stream_path": None,
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
    logger.info(
        "Created stream session",
        extra={
            "session_id": session_id,
            "movie_id": payload.movie_id,
            "source": source,
            "external_id": external_id,
            "user_id": user_id,
        },
    )
    return session


async def get_stream_session(session_id: str) -> dict[str, Any] | None:
    async with runtime_state.STREAM_LOCK:
        return runtime_state.STREAM_SESSIONS.get(session_id)


async def get_stream_target(session_id: str) -> tuple[str | None, str | None]:
    async with runtime_state.STREAM_LOCK:
        session = runtime_state.STREAM_SESSIONS.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Stream session not found")
        stream_path = session.get("stream_path")
        status_value = session.get("status")

    return (
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
