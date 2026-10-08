"""Stream sessions: download a film with BitTorrent and play it meanwhile.

Subject III.3: the torrent starts on the server when a film is opened, playback
begins as soon as enough data is there, all work runs in the background, the
finished file is kept, and formats a browser cannot read (mkv...) are converted
on the fly.

How playing-while-downloading works here:
  * libtorrent downloads pieces in order (sequential mode), so the start of
    the film arrives first; the session is "ready" once BUFFER_READY_BYTES
    from the start are on disk - measured on real pieces, not on file size
    (libtorrent creates the file at full size immediately).
  * /stream answers byte ranges; before sending any byte it waits for the
    pieces holding it and asks libtorrent for them first (piece deadlines).
    A seek ahead of the download therefore waits instead of sending zeros.
  * Non-browser formats are piped through FFmpeg as they download; FFmpeg
    writes fragmented mp4, which plays while it is still being written. When
    done, it is remuxed once into a normal seekable mp4 kept for later.
"""
import asyncio
import json
import logging
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
    LIVE_READY_BYTES,
    MEDIA_ROOT,
    METADATA_TIMEOUT_SECONDS,
    STALL_TIMEOUT_SECONDS,
    STREAM_WAIT_SECONDS,
    TORRENT_POLL_SECONDS,
)
from runtime_state import LiveOutput, TorrentFile
from services import subtitle_service
from services.common import is_subtitle_file, is_video_file, normalize_language, now_iso, session_key, slugify
from services.db_service import fetch_movie, fetch_user_pref_language, update_movie_state
from services.search_service import split_peertube_external_id, validate_external_id

try:
    import libtorrent as lt  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional dependency at runtime
    lt = None


logger = logging.getLogger(__name__)

# Browser-playable formats rank highest. Archive.org items often ship a huge
# .mpeg master alongside a much smaller .mp4 derivative; without this ranking a
# size-based pick would choose the multi-gigabyte master.
_FORMAT_RANK = {".mp4": 3, ".webm": 3, ".m4v": 2, ".ogv": 2, ".mkv": 1}
# Containers FFmpeg can read from a pipe, front to back, while they download.
# (.mov/.avi may keep their index at the end: those are converted once complete.)
_PIPE_FRIENDLY = {".mkv", ".webm", ".mpeg", ".mpg", ".ts", ".ogv"}

_PRIORITY_SKIP = 0
_PRIORITY_SUBTITLE = 4
_PRIORITY_VIDEO = 7

COMPLETE_MARKER = ".complete.json"
# Pieces just past the downloaded prefix get a deadline on every poll, so
# peers and HTTP webseeds alike deliver the film front to back.
READAHEAD_PIECES = 12
READ_CHUNK = 512 * 1024
FEED_CHUNK = 1024 * 1024


def _format_rank(name: str) -> int:
    return _FORMAT_RANK.get(Path(name).suffix.lower(), 0)


def _needs_conversion(path: Path) -> bool:
    return _format_rank(path.name) < 2


def _spawn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    runtime_state.BACKGROUND_TASKS.add(task)
    task.add_done_callback(runtime_state.BACKGROUND_TASKS.discard)
    return task


# ── Torrent sources ───────────────────────────────────────────────────────────


async def _fetch_archive_torrent(external_id: str) -> bytes:
    """Download the item's .torrent.

    We deliberately do NOT build a magnet from the `btih` archive.org
    publishes. A magnet carries only the infohash and trackers, while the
    .torrent additionally carries `url-list` - the BEP-19 webseeds pointing at
    archive.org's own HTTP servers. Most archive items have no peers willing to
    serve metadata, so without those webseeds the download stalls forever.
    """
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(f"{ARCHIVE_METADATA_URL}/{quote(external_id)}")
        response.raise_for_status()
        payload = response.json()

        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected archive.org metadata for '{external_id}'")
        if payload.get("is_dark"):
            raise RuntimeError(f"Archive item '{external_id}' is not publicly available")

        files = payload.get("files")
        torrent_name = next(
            (str(item["name"]) for item in files or [] if isinstance(item, dict) and str(item.get("name") or "").endswith(".torrent")),
            "",
        )
        if not torrent_name:
            raise RuntimeError(f"Archive item '{external_id}' does not publish a torrent")

        torrent = await client.get(f"https://archive.org/download/{quote(external_id)}/{quote(torrent_name)}")
        torrent.raise_for_status()
        return torrent.content


MAX_TORRENT_FILE_BYTES = 4 * 1024 * 1024


async def _fetch_peertube_torrent(external_id: str) -> tuple[bytes, str | None]:
    """Download the .torrent of the best file up to 1080p, and that file's
    current URL.

    Not the magnet: PeerTube's peers are WebTorrent (WebRTC) browsers that
    libtorrent cannot reach, and a webseed cannot serve torrent metadata, so a
    magnet never gets past "downloading metadata". The .torrent carries the
    metadata and the instance's HTTP webseed.
    """
    host, uuid = split_peertube_external_id(external_id)
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
        response = await client.get(f"https://{host}/api/v1/videos/{uuid}")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected PeerTube payload for '{external_id}'")

        candidates: list[dict[str, Any]] = [e for e in payload.get("files") or [] if isinstance(e, dict)]
        for playlist in payload.get("streamingPlaylists") or []:
            if isinstance(playlist, dict):
                candidates.extend(e for e in playlist.get("files") or [] if isinstance(e, dict))

        def resolution_of(entry: dict[str, Any]) -> int:
            resolution = entry.get("resolution")
            try:
                return int(resolution.get("id") or 0) if isinstance(resolution, dict) else 0
            except (TypeError, ValueError):
                return 0

        # Only from the video's own instance: the URL comes from its API.
        playable = [
            entry for entry in candidates
            if str(entry.get("torrentUrl") or "").startswith(f"https://{host}/")
        ]
        if not playable:
            raise RuntimeError(f"PeerTube video '{external_id}' exposes no torrent")
        within_budget = [entry for entry in playable if resolution_of(entry) <= 1080]
        chosen = max(within_budget or playable, key=resolution_of)

        torrent = await client.get(str(chosen["torrentUrl"]))
        torrent.raise_for_status()
        if len(torrent.content) > MAX_TORRENT_FILE_BYTES:
            raise RuntimeError(f"PeerTube torrent for '{external_id}' is too large")
        # Torrents made before PeerTube 6 name a webseed under /static/webseed/,
        # which now answers 404: the API's fileUrl is where the file lives today.
        file_url = str(chosen.get("fileUrl") or "")
        return torrent.content, file_url if file_url.startswith(f"https://{host}/") else None


async def build_torrent_params(source: str, external_id: str, target_dir: Path):
    """The source's published .torrent, which carries the HTTP webseeds."""
    extra_webseed: str | None = None
    if source == "archive":
        data = await _fetch_archive_torrent(external_id)
    elif source == "peertube":
        data, extra_webseed = await _fetch_peertube_torrent(external_id)
    else:
        raise RuntimeError(f"Unsupported source '{source}'")
    torrent_path = target_dir / f"{slugify(external_id)}.torrent"
    torrent_path.write_bytes(data)
    params = lt.add_torrent_params()
    params.ti = lt.torrent_info(str(torrent_path))
    if extra_webseed:
        params.url_seeds = [extra_webseed]

    params.save_path = str(target_dir)
    params.storage_mode = lt.storage_mode_t.storage_mode_sparse
    return params


def _enable_sequential(handle) -> None:
    try:
        handle.set_flags(lt.torrent_flags.sequential_download)
    except AttributeError:  # older bindings
        handle.set_sequential_download(True)


# ── Reading bytes that may still be downloading ───────────────────────────────


def _pieces_for(src: TorrentFile, start: int, end: int) -> range:
    first = (src.file_offset + start) // src.piece_length
    last = (src.file_offset + end) // src.piece_length
    return range(first, last + 1)


def _push_readahead(src: TorrentFile, prefix: int) -> None:
    if src.handle is None or src.complete or prefix >= src.size:
        return
    first = (src.file_offset + prefix) // src.piece_length
    last = (src.file_offset + src.size - 1) // src.piece_length
    for rank, piece in enumerate(range(first, min(last, first + READAHEAD_PIECES - 1) + 1)):
        if not src.handle.have_piece(piece):
            src.handle.set_piece_deadline(piece, 1000 + rank * 400)


def _contiguous_bytes(src: TorrentFile) -> int:
    """How many bytes from the start of the file are downloaded without a gap."""
    if src.complete:
        return src.size
    if src.handle is None or not src.piece_length:
        return 0
    pieces = _pieces_for(src, 0, max(src.size - 1, 0))
    for piece in pieces:
        if not src.handle.have_piece(piece):
            return max(0, min(src.size, piece * src.piece_length - src.file_offset))
    return src.size


async def wait_for_bytes(src: TorrentFile, start: int, end: int, timeout: float = STREAM_WAIT_SECONDS) -> bool:
    """Block (asynchronously) until bytes start..end are on disk."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        if src.complete:
            return True
        handle = src.handle
        if src.failed or handle is None:
            return False
        missing = [p for p in _pieces_for(src, start, end) if not handle.have_piece(p)]
        if not missing:
            return True
        # Ask for what the player needs right now before anything else.
        for rank, piece in enumerate(missing[:16]):
            handle.set_piece_deadline(piece, 300 + rank * 150)
        if loop.time() > deadline:
            return False
        await asyncio.sleep(0.2)


def _read(path: Path, start: int, length: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(start)
        return handle.read(length)


async def iter_source(src: TorrentFile, start: int, end: int):
    """Yield bytes start..end, waiting for each chunk to be downloaded."""
    position = start
    while position <= end:
        stop = min(end, position + READ_CHUNK - 1)
        if not await wait_for_bytes(src, position, stop):
            logger.warning("Stream stopped at byte %s of %s: data not available", position, src.path.name)
            return
        data = await asyncio.to_thread(_read, src.path, position, stop - position + 1)
        if not data:
            return
        yield data
        position += len(data)


async def iter_live(out: LiveOutput):
    """Yield a growing FFmpeg output until conversion ends."""
    position = 0
    idle = 0.0
    while True:
        size = out.path.stat().st_size if out.path.exists() else 0
        if position < size:
            data = await asyncio.to_thread(_read, out.path, position, min(READ_CHUNK, size - position))
            position += len(data)
            idle = 0.0
            yield data
            continue
        if out.done or out.failed:
            return
        if idle > STREAM_WAIT_SECONDS:
            return
        await asyncio.sleep(0.3)
        idle += 0.3


# ── Session bookkeeping ───────────────────────────────────────────────────────


async def _set(session_id: str, **fields: Any) -> None:
    async with runtime_state.STREAM_LOCK:
        session = runtime_state.STREAM_SESSIONS.get(session_id)
        if session is not None:
            session.update(fields, updated_at=now_iso())


async def _mark_error(session_id: str, movie_id: int, message: str) -> None:
    await _set(session_id, status="error", error=message)
    source = runtime_state.SOURCES.get(session_id)
    if source is not None and not source.complete:
        source.failed = True
    if movie_id:
        await update_movie_state(movie_id, stream_status="error", last_accessed_at=datetime.now(timezone.utc))


async def _mark_ready(session_id: str, movie_id: int, video_path: Path, mode: str) -> None:
    now = datetime.now(timezone.utc)
    await update_movie_state(
        movie_id, stream_status="ready", video_path=str(video_path), last_accessed_at=now, last_watched_at=now
    )
    async with runtime_state.STREAM_LOCK:
        session = runtime_state.STREAM_SESSIONS.get(session_id)
        if session is not None and session["status"] not in ("ready", "complete"):
            session.update(status="ready", mode=mode, stream_url=f"/api/stream/{session_id}", updated_at=now_iso())


async def _publish_subtitles(session_id: str, movie: dict[str, Any], paths: list[Path], preferred: str) -> None:
    # Auto captions carry no language in their name: they transcribe the
    # film's own language (English when archive.org does not say).
    spoken = normalize_language(movie.get("original_language")) or "en"
    tracks: list[dict[str, str]] = []
    for path in paths:
        if path.exists():
            usable = await subtitle_service.to_vtt(path)
            if usable is not None:
                hint = spoken if subtitle_service.is_auto_caption(path) else None
                tracks.append(subtitle_service.track(usable, session_id, hint))
    if not tracks:
        return

    async with runtime_state.STREAM_LOCK:
        session = runtime_state.STREAM_SESSIONS.get(session_id)
        if session is None:
            return
        # "x.srt" and its converted "x.vtt" are the same track: keep one.
        merged = list({t["local_path"]: t for t in session["subtitle_tracks"] + tracks}.values())
        merged.sort(key=lambda t: 0 if t["language"] == preferred else (1 if t["language"] == "en" else 2))
        session["subtitle_tracks"] = merged
        languages = {t["language"] for t in merged}
        session["default_subtitle_language"] = subtitle_service.default_language(
            preferred, movie.get("original_language"), languages
        )
        session["updated_at"] = now_iso()

    await update_movie_state(int(movie["id"]), subtitle_languages=",".join(sorted(languages - {"und"})) or None)


async def _fetch_external_subtitles(session_id: str, movie: dict[str, Any], preferred: str) -> None:
    languages = subtitle_service.wanted_languages(preferred, movie.get("original_language"))
    source, external_id = str(movie["external_source"]), str(movie["external_id"])
    try:
        paths: list[Path] = []
        if source == "peertube":
            paths += await subtitle_service.peertube_captions(external_id, languages)
        have = {subtitle_service.track(p, session_id)["language"] for p in paths}
        missing = [language for language in languages if language not in have]
        if missing:
            paths += await subtitle_service.opensubtitles(movie.get("imdb_id"), source, external_id, missing)
        await _publish_subtitles(session_id, movie, paths, preferred)
    except Exception:
        logger.exception("External subtitle lookup failed", extra={"session_id": session_id})


# ── Conversion (mkv and other non-browser formats) ────────────────────────────


async def _feed_ffmpeg(src: TorrentFile, stdin: asyncio.StreamWriter) -> None:
    try:
        async for chunk in iter_source(src, 0, src.size - 1):
            stdin.write(chunk)
            await stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        return  # FFmpeg stopped early; its exit code reports why
    finally:
        stdin.close()


async def _convert_live(session_id: str, movie_id: int, src: TorrentFile, final_path: Path) -> None:
    """Convert to fragmented mp4 as the source downloads; the player reads the
    output while it grows. Then remux once into a seekable mp4 for later."""
    out = LiveOutput(path=final_path.with_suffix(".live.mp4"))
    runtime_state.LIVE_OUTPUTS[session_id] = out
    out.path.unlink(missing_ok=True)
    await _set(session_id, status="transcoding")
    await update_movie_state(movie_id, stream_status="transcoding")

    from_pipe = src.path.suffix.lower() in _PIPE_FRIENDLY
    if not from_pipe:
        # The container's index may sit at the end: wait for the whole file.
        while not src.complete:
            if src.failed:
                out.failed = True
                return
            await asyncio.sleep(1.0)

    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", "pipe:0" if from_pipe else str(src.path),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", "scale='min(1280,iw)':-2", "-pix_fmt", "yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-ac", "2", "-b:a", "160k",
        "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        "-f", "mp4", str(out.path),
        stdin=asyncio.subprocess.PIPE if from_pipe else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )

    async def watch_output() -> None:
        while process.returncode is None:
            if out.path.exists() and out.path.stat().st_size >= LIVE_READY_BYTES:
                await _mark_ready(session_id, movie_id, src.path, mode="live")
                return
            await asyncio.sleep(0.5)

    watcher = asyncio.create_task(watch_output())
    feeder = asyncio.create_task(_feed_ffmpeg(src, process.stdin)) if from_pipe else None
    stderr = await process.stderr.read()
    await process.wait()
    watcher.cancel()
    if feeder is not None:
        feeder.cancel()

    if process.returncode != 0 or not out.path.exists():
        out.failed = True
        await _mark_error(session_id, movie_id, "Conversion failed: " + stderr.decode(errors="ignore")[-300:])
        return

    out.done = True
    await _mark_ready(session_id, movie_id, src.path, mode="live")

    # A fragmented mp4 cannot be seeked well; keep a regular one for next time.
    for _ in range(30):  # the download loop flags completion within a poll or two
        if src.complete or src.failed:
            break
        await asyncio.sleep(1.0)
    tmp = final_path.with_suffix(".tmp.mp4")
    remux = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(out.path),
        "-c", "copy", "-movflags", "+faststart", str(tmp),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    if await remux.wait() == 0 and src.complete:
        tmp.replace(final_path)
        _write_marker(final_path.parent, final_path, converted=True)
        await update_movie_state(movie_id, video_path=str(final_path))
    else:
        tmp.unlink(missing_ok=True)


# ── Download ──────────────────────────────────────────────────────────────────


def _write_marker(target_dir: Path, video: Path, converted: bool) -> None:
    (target_dir / COMPLETE_MARKER).write_text(
        json.dumps({"video": str(video.relative_to(target_dir)), "converted": converted})
    )


def _read_marker(target_dir: Path) -> Path | None:
    """The finished video, if a previous download completed (not just started)."""
    try:
        marker = json.loads((target_dir / COMPLETE_MARKER).read_text())
        video = (target_dir / str(marker["video"])).resolve()
        video.relative_to(target_dir.resolve())
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return video if video.is_file() else None


async def _serve_from_disk(session_id: str, movie: dict[str, Any], video: Path, preferred: str) -> None:
    movie_id = int(movie["id"])
    src = TorrentFile(path=video, size=video.stat().st_size, complete=True)
    runtime_state.SOURCES[session_id] = src
    subtitles = [p for p in video.parent.rglob("*") if p.is_file() and is_subtitle_file(p.name)]
    await _publish_subtitles(session_id, movie, subtitles, preferred)
    await _set(session_id, progress=1.0)
    if _needs_conversion(video):
        await _convert_live(session_id, movie_id, src, video.with_suffix(".mp4"))
        return
    await _mark_ready(session_id, movie_id, video, mode="direct")
    await _set(session_id, status="complete")


async def _download(session_id: str, movie: dict[str, Any], target_dir: Path, preferred: str) -> None:
    movie_id = int(movie["id"])
    source, external_id = str(movie["external_source"]), str(movie["external_id"])

    params = await build_torrent_params(source, external_id, target_dir)
    lt_session = lt.session()
    handle = lt_session.add_torrent(params)
    await _set(session_id, status="buffering")
    await update_movie_state(movie_id, stream_status="buffering", last_accessed_at=datetime.now(timezone.utc))

    src: TorrentFile | None = None
    subtitle_files: list[tuple[int, Path]] = []
    converting = False
    loop = asyncio.get_running_loop()
    started_at = last_progress_at = loop.time()
    last_done = 0

    try:
        while True:
            status = handle.status()
            now = loop.time()

            if not status.has_metadata and now - started_at > METADATA_TIMEOUT_SECONDS:
                raise RuntimeError(f"No peer or webseed sent the torrent metadata within {int(METADATA_TIMEOUT_SECONDS)}s")

            done = int(getattr(status, "total_wanted_done", 0) or 0)
            if done > last_done:
                last_done, last_progress_at = done, now
            elif now - last_progress_at > STALL_TIMEOUT_SECONDS:
                raise RuntimeError(f"Download stalled: no data received for {int(STALL_TIMEOUT_SECONDS)}s")

            if status.has_metadata and src is None:
                info = handle.torrent_file()
                files = info.files()
                videos = sorted(
                    (
                        (_format_rank(files.file_path(i)), files.file_size(i), i)
                        for i in range(files.num_files())
                        if is_video_file(Path(files.file_path(i)).name)
                    ),
                    reverse=True,
                )
                if not videos:
                    raise RuntimeError("Torrent contains no playable video file")
                chosen = videos[0][2]
                subtitle_files = [
                    (i, target_dir / files.file_path(i))
                    for i in range(files.num_files())
                    if is_subtitle_file(Path(files.file_path(i)).name)
                ]

                # Only fetch what we stream. Archive.org torrents bundle every
                # derivative (24 files / 4 GB for one 483 MB mp4).
                priorities = [_PRIORITY_SKIP] * files.num_files()
                priorities[chosen] = _PRIORITY_VIDEO
                for index, _ in subtitle_files:
                    priorities[index] = _PRIORITY_SUBTITLE
                handle.prioritize_files(priorities)
                _enable_sequential(handle)

                src = TorrentFile(
                    path=target_dir / files.file_path(chosen),
                    size=files.file_size(chosen),
                    handle=handle,
                    file_offset=files.file_offset(chosen),
                    piece_length=info.piece_length(),
                )
                runtime_state.SOURCES[session_id] = src
                # An mp4 may keep its index (moov) at the end: fetch that early too.
                tail = _pieces_for(src, max(0, src.size - 2 * src.piece_length), src.size - 1)
                for piece in tail:
                    handle.set_piece_deadline(piece, 2000)
                await _set(session_id, selected_file=src.path.name)

            if src is not None:
                wanted = int(getattr(status, "total_wanted", 0) or 0)
                prefix = _contiguous_bytes(src)
                _push_readahead(src, prefix)
                await _set(
                    session_id,
                    progress=round(done / wanted, 4) if wanted else 0.0,
                    buffered=round(prefix / src.size, 4) if src.size else 0.0,
                )

                if subtitle_files:
                    progress = handle.file_progress()
                    sizes = handle.torrent_file().files()
                    finished = [(i, p) for i, p in subtitle_files if progress[i] >= sizes.file_size(i)]
                    if finished:
                        await _publish_subtitles(session_id, movie, [p for _, p in finished], preferred)
                        subtitle_files = [f for f in subtitle_files if f not in finished]

                if _needs_conversion(src.path):
                    if not converting and (prefix >= min(FEED_CHUNK, src.size) or status.is_finished):
                        converting = True
                        runtime_state.TORRENT_RUNNERS[f"{session_id}:convert"] = _spawn(
                            _convert_live(session_id, movie_id, src, src.path.with_suffix(".mp4"))
                        )
                elif prefix >= min(BUFFER_READY_BYTES, src.size):
                    await _mark_ready(session_id, movie_id, src.path, mode="direct")

                if status.is_finished and prefix >= src.size:
                    src.complete = True
                    break

            await asyncio.sleep(TORRENT_POLL_SECONDS)
    finally:
        if src is not None and not src.complete:
            src.failed = True
        if src is not None:
            src.handle = None
        lt_session.remove_torrent(handle)
        lt_session.pause()

    # Kept on disk so the next viewer does not download it again.
    _write_marker(target_dir, src.path, converted=False)
    await update_movie_state(movie_id, last_accessed_at=datetime.now(timezone.utc))
    await _set(session_id, progress=1.0)
    if not _needs_conversion(src.path):
        await _set(session_id, status="complete")


async def _run_session(session_id: str) -> None:
    movie_id = 0
    try:
        async with runtime_state.STREAM_LOCK:
            session = runtime_state.STREAM_SESSIONS[session_id]
            movie_id = int(session["movie_id"])
            user_id = int(session["user_id"])
            session.update(status="preparing", updated_at=now_iso())

        movie = await fetch_movie(movie_id)
        if movie is None:
            raise RuntimeError("Film not found")
        await update_movie_state(movie_id, stream_status="preparing", last_accessed_at=datetime.now(timezone.utc))
        if lt is None:
            raise RuntimeError("libtorrent unavailable in container")

        preferred = await fetch_user_pref_language(user_id)
        _spawn(_fetch_external_subtitles(session_id, movie, preferred))

        source, external_id = str(movie["external_source"]), str(movie["external_id"])
        target_dir = MEDIA_ROOT / f"{slugify(source)}-{slugify(external_id)}"
        target_dir.mkdir(parents=True, exist_ok=True)

        finished = _read_marker(target_dir)
        if finished is not None:
            converted = finished.with_suffix(".mp4")
            await _serve_from_disk(session_id, movie, converted if converted.is_file() else finished, preferred)
            return
        # Not finished before (or never started): libtorrent re-checks any
        # pieces already on disk and resumes from there.
        await _download(session_id, movie, target_dir, preferred)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("Stream session failed", extra={"session_id": session_id})
        await _mark_error(session_id, movie_id, str(exc)[:300])
    finally:
        runtime_state.TORRENT_RUNNERS.pop(session_id, None)


# ── Public API used by main.py ────────────────────────────────────────────────


def public_view(session: dict[str, Any]) -> dict[str, Any]:
    """What a browser may see of a session: no paths, no other user's id."""
    return {
        "session_id": session["session_id"],
        "movie_id": session["movie_id"],
        "source": session["source"],
        "external_id": session["external_id"],
        "status": session["status"],
        "mode": session.get("mode"),
        "progress": session.get("progress", 0.0),
        "buffered": session.get("buffered", 0.0),
        "error": session.get("error"),
        "stream_url": session.get("stream_url"),
        "subtitle_tracks": [
            {"language": t["language"], "label": t["label"], "url": t["url"]} for t in session["subtitle_tracks"]
        ],
        "default_subtitle_language": session.get("default_subtitle_language"),
        "updated_at": session.get("updated_at"),
    }


def _still_usable(session_id: str, session: dict[str, Any]) -> bool:
    """An errored session, or one whose file was erased by the monthly cleanup,
    is replaced by a fresh one - so a failed download can be retried."""
    if session["status"] == "error":
        return False
    src = runtime_state.SOURCES.get(session_id)
    if src is not None and (src.failed or (src.complete and not src.path.exists())):
        return False
    return True


async def create_stream_session(source: str, external_id: str, user_id: int) -> dict[str, Any]:
    source = source.strip().lower()
    external_id = external_id.strip()
    try:
        await validate_external_id(source, external_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # The film row is looked up here, never taken from the request, so a client
    # cannot point a download at another film's database row.
    movie = await fetch_movie(source=source, external_id=external_id)
    if movie is None:
        raise HTTPException(status_code=404, detail="Open the film page first")

    key = session_key(source, external_id)
    async with runtime_state.STREAM_LOCK:
        existing_id = runtime_state.STREAM_INDEX.get(key)
        existing = runtime_state.STREAM_SESSIONS.get(existing_id) if existing_id else None
        if existing is not None and _still_usable(existing_id, existing):
            existing["updated_at"] = now_iso()
            reused = public_view(existing)
        else:
            reused = None
            if existing_id:
                runtime_state.STREAM_SESSIONS.pop(existing_id, None)
                runtime_state.SOURCES.pop(existing_id, None)
                runtime_state.LIVE_OUTPUTS.pop(existing_id, None)
            session_id = str(uuid4())
            session = {
                "session_id": session_id,
                "movie_id": int(movie["id"]),
                "user_id": user_id,
                "source": source,
                "external_id": external_id,
                "status": "queued",
                "mode": None,
                "progress": 0.0,
                "stream_url": None,
                "selected_file": None,
                "subtitle_tracks": [],
                "default_subtitle_language": None,
                "error": None,
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
            runtime_state.STREAM_SESSIONS[session_id] = session
            runtime_state.STREAM_INDEX[key] = session_id

    if reused is not None:
        # Watching again counts as watching: keeps the film from the monthly purge.
        await update_movie_state(int(movie["id"]), last_watched_at=datetime.now(timezone.utc))
        return reused

    runtime_state.TORRENT_RUNNERS[session_id] = asyncio.create_task(_run_session(session_id))
    logger.info("Created stream session %s for %s:%s", session_id, source, external_id)
    return public_view(session)


async def get_stream_session(session_id: str) -> dict[str, Any] | None:
    async with runtime_state.STREAM_LOCK:
        session = runtime_state.STREAM_SESSIONS.get(session_id)
        return public_view(session) if session else None


async def get_stream_target(session_id: str) -> tuple[str, TorrentFile | LiveOutput]:
    """("live", output) while a conversion is being played, else ("direct", file)."""
    async with runtime_state.STREAM_LOCK:
        session = runtime_state.STREAM_SESSIONS.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Stream session not found")
        status_value = session["status"]
        mode = session.get("mode")

    if status_value not in ("ready", "complete") or mode is None:
        raise HTTPException(status_code=409, detail=f"Stream not ready (status={status_value})")
    if mode == "live":
        out = runtime_state.LIVE_OUTPUTS.get(session_id)
        if out is None or out.failed:
            raise HTTPException(status_code=409, detail="Conversion unavailable")
        return "live", out
    src = runtime_state.SOURCES.get(session_id)
    if src is None or src.failed or not src.path.exists():
        raise HTTPException(status_code=404, detail="Local stream file missing")
    return "direct", src


async def list_subtitles(session_id: str) -> dict[str, Any]:
    session = await get_stream_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Stream session not found")
    return {"session_id": session_id, "subtitle_tracks": session["subtitle_tracks"]}


async def get_subtitle_local_path(session_id: str, subtitle_name: str) -> Path | None:
    safe_name = Path(subtitle_name).name
    async with runtime_state.STREAM_LOCK:
        session = runtime_state.STREAM_SESSIONS.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Stream session not found")
        tracks = list(session.get("subtitle_tracks") or [])

    for track in tracks:
        candidate = Path(str(track.get("local_path") or ""))
        if candidate.name == safe_name:
            return candidate
    return None


async def cancel_all_stream_tasks() -> None:
    tasks = list(runtime_state.TORRENT_RUNNERS.values()) + list(runtime_state.BACKGROUND_TASKS)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    runtime_state.TORRENT_RUNNERS.clear()
