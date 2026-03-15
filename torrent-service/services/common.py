import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def session_key(source: str, external_id: str) -> str:
    return f"{source.strip().lower()}::{external_id.strip()}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_video_file(name: str) -> bool:
    lowered = name.lower()
    return lowered.endswith((".mp4", ".webm", ".mkv", ".m4v", ".mov", ".avi"))


def is_subtitle_file(name: str) -> bool:
    lowered = name.lower()
    return lowered.endswith((".vtt", ".srt", ".ass"))


def language_from_name(name: str) -> str | None:
    lowered = name.lower()
    for candidate in ("en", "eng", "english", "fr", "fre", "french", "es", "spa", "spanish"):
        if candidate in lowered:
            if candidate.startswith("en"):
                return "en"
            if candidate.startswith("fr"):
                return "fr"
            if candidate.startswith("es"):
                return "es"
    return None


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip())
    normalized = normalized.strip("-")
    return normalized[:80] if normalized else "movie"


def as_text(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def as_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                items.append(item.strip())
        return items
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def as_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def coalesce_int(*values: Any) -> int | None:
    for value in values:
        parsed = as_int(value)
        if parsed is not None:
            return parsed
    return None


def truncate_text(text: str | None, max_length: int = 320) -> str | None:
    if not text:
        return None
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_length:
        return collapsed
    return collapsed[: max_length - 3].rstrip() + "..."


def guess_media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    if guessed:
        return guessed
    return "video/mp4"


def parse_range_header(range_header: str | None, file_size: int) -> tuple[int, int] | None:
    if not range_header or not range_header.startswith("bytes="):
        return None

    raw = range_header.replace("bytes=", "", 1)
    start_str, _, end_str = raw.partition("-")
    try:
        if start_str == "":
            suffix = int(end_str)
            if suffix <= 0:
                return None
            start = max(file_size - suffix, 0)
            end = file_size - 1
            return start, end

        start = int(start_str)
        end = int(end_str) if end_str else file_size - 1
    except ValueError:
        return None

    if start >= file_size:
        return None

    end = min(end, file_size - 1)
    if end < start:
        return None
    return start, end


def iter_file_chunks(path: Path, start: int, end: int, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    with path.open("rb") as file_handle:
        file_handle.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            read_size = min(chunk_size, remaining)
            data = file_handle.read(read_size)
            if not data:
                break
            remaining -= len(data)
            yield data
