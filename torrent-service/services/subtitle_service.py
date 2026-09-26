"""Subtitles (subject III.3).

English subtitles are fetched whenever a source has them. When the film's
language differs from the viewer's preferred language, subtitles in the
preferred language are fetched too and selected by default. Sources, in order:
files shipped inside the torrent, the PeerTube captions API, and OpenSubtitles
(only when OPENSUBTITLES_API_KEY is set). Everything is converted to WebVTT,
the only format browsers read.
"""
import asyncio
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from config import OPENSUBTITLES_API_KEY, SUBTITLES_ROOT
from services.common import language_from_name, normalize_language, slugify
from services.search_service import split_peertube_external_id, validate_external_id

logger = logging.getLogger(__name__)

OPENSUBTITLES_URL = "https://api.opensubtitles.com/api/v1"
USER_AGENT = "Hypertube v1.0"
MAX_SUBTITLE_BYTES = 2 * 1024 * 1024

# SubRip in the wild uses either milliseconds or centiseconds, and either a
# comma or a dot. WebVTT requires exactly HH:MM:SS.mmm or the cue is dropped.
_SRT_TIMESTAMP = re.compile(r"(\d{1,2}:\d{2}:\d{2})[,.](\d{1,3})")


def wanted_languages(preferred: str, original: str | None) -> list[str]:
    """English always; the preferred language when the film is in another one."""
    languages = ["en"]
    original_code = normalize_language(original)
    if preferred != "en" and preferred != original_code:
        languages.append(preferred)
    return languages


def default_language(preferred: str, original: str | None, available: set[str]) -> str | None:
    """Turn subtitles on only when the film is not in the viewer's language."""
    original_code = normalize_language(original)
    if original_code == preferred:
        return None
    return preferred if preferred in available else None


def srt_text_to_vtt(body: str) -> str:
    converted = _SRT_TIMESTAMP.sub(lambda m: f"{m.group(1)}.{m.group(2).ljust(3, '0')}", body)
    return "WEBVTT\n\n" + converted.lstrip("﻿")


async def to_vtt(path: Path) -> Path | None:
    """Convert a subtitle file next to itself; None when it cannot be read."""
    suffix = path.suffix.lower()
    if suffix == ".vtt":
        return path
    target = path.with_suffix(".vtt")
    if target.exists():
        return target
    if suffix == ".srt":
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        target.write_text(srt_text_to_vtt(body), encoding="utf-8")
        return target
    # .ass / .ssa: styling is dropped, the text and timings are kept.
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(path), str(target),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0 or not target.exists():
        logger.warning("Could not convert subtitle %s: %s", path.name, (stderr or b"").decode(errors="ignore")[-300:])
        return None
    return target


def _folder(source: str, external_id: str) -> Path:
    folder = SUBTITLES_ROOT / f"{slugify(source)}-{slugify(external_id)}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


async def _download(client: httpx.AsyncClient, url: str, headers: dict[str, str] | None = None) -> bytes | None:
    try:
        response = await client.get(url, headers=headers)
        if response.status_code != 200 or len(response.content) > MAX_SUBTITLE_BYTES:
            return None
        return response.content
    except httpx.HTTPError:
        return None


async def peertube_captions(external_id: str, languages: list[str]) -> list[Path]:
    await validate_external_id("peertube", external_id)
    host, uuid = split_peertube_external_id(external_id)
    folder = _folder("peertube", external_id)
    found: list[Path] = []
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        try:
            response = await client.get(f"https://{host}/api/v1/videos/{uuid}/captions")
            response.raise_for_status()
            captions = response.json().get("data") or []
        except (httpx.HTTPError, ValueError):
            return []
        for caption in captions:
            if not isinstance(caption, dict):
                continue
            language = normalize_language(str((caption.get("language") or {}).get("id") or ""))
            path = str(caption.get("captionPath") or caption.get("fileUrl") or "")
            if language not in languages or not path:
                continue
            url = path if path.startswith("https://") else f"https://{host}{path}"
            if not url.startswith(f"https://{host}/"):
                continue  # captions are only fetched from the video's own host
            body = await _download(client, url)
            if body:
                target = folder / f"peertube.{language}.vtt"
                target.write_bytes(body)
                found.append(target)
    return found


async def opensubtitles(imdb_id: str | None, source: str, external_id: str, languages: list[str]) -> list[Path]:
    if not OPENSUBTITLES_API_KEY or not imdb_id or not re.fullmatch(r"tt\d{5,10}", imdb_id):
        return []
    folder = _folder(source, external_id)
    headers = {"Api-Key": OPENSUBTITLES_API_KEY, "User-Agent": USER_AGENT, "Accept": "application/json"}
    found: list[Path] = []
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            response = await client.get(
                f"{OPENSUBTITLES_URL}/subtitles",
                params={"imdb_id": imdb_id[2:].lstrip("0"), "languages": ",".join(languages), "order_by": "download_count"},
                headers=headers,
            )
            response.raise_for_status()
            results: list[dict[str, Any]] = response.json().get("data") or []
        except (httpx.HTTPError, ValueError):
            return []

        for language in languages:
            target = folder / f"opensubtitles.{language}.vtt"
            if target.exists():
                found.append(target)
                continue
            match = next(
                (r for r in results if normalize_language(str((r.get("attributes") or {}).get("language") or "")) == language),
                None,
            )
            files = ((match or {}).get("attributes") or {}).get("files") or []
            if not files:
                continue
            try:
                link_resp = await client.post(
                    f"{OPENSUBTITLES_URL}/download", json={"file_id": files[0].get("file_id")}, headers=headers
                )
                link_resp.raise_for_status()
                link = str(link_resp.json().get("link") or "")
            except (httpx.HTTPError, ValueError):
                continue
            body = await _download(client, link) if link.startswith("https://") else None
            if body:
                target.write_text(srt_text_to_vtt(body.decode("utf-8", errors="replace")), encoding="utf-8")
                found.append(target)
    return found


def track(path: Path, session_id: str, origin_hint: str | None = None) -> dict[str, str]:
    language = language_from_name(path.name) or origin_hint or "und"
    return {
        "language": language,
        "label": language.upper() if language != "und" else "Unknown",
        "url": f"/api/subtitles/{session_id}/{quote(path.name)}",
        "local_path": str(path),
    }
