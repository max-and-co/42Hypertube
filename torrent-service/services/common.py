import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def session_key(source: str, external_id: str) -> str:
    return f"{source.strip().lower()}::{external_id.strip()}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_video_file(name: str) -> bool:
    lowered = name.lower()
    return lowered.endswith((".mp4", ".webm", ".mkv", ".m4v", ".ogv", ".mov", ".avi", ".mpeg", ".mpg"))


def is_subtitle_file(name: str) -> bool:
    lowered = name.lower()
    return lowered.endswith((".vtt", ".srt", ".ass"))


_LANGUAGE_TOKENS = {
    "en": "en", "eng": "en", "english": "en",
    "fr": "fr", "fre": "fr", "fra": "fr", "french": "fr", "francais": "fr",
    "es": "es", "spa": "es", "spanish": "es", "espanol": "es",
    "de": "de", "ger": "de", "deu": "de", "german": "de",
    "it": "it", "ita": "it", "italian": "it",
    "pt": "pt", "por": "pt", "portuguese": "pt",
    "ru": "ru", "rus": "ru", "russian": "ru",
    "ja": "ja", "jpn": "ja", "japanese": "ja",
    "zh": "zh", "chi": "zh", "zho": "zh", "chinese": "zh",
    "nl": "nl", "dut": "nl", "nld": "nl", "dutch": "nl",
}


def normalize_language(value: str | None) -> str | None:
    """'English, French' / 'eng' / 'en-US' -> 'en' (first language only)."""
    if not value:
        return None
    first = re.split(r"[,;/]", value.strip().lower())[0].strip()
    first = first.split("-")[0].split("_")[0]
    return _LANGUAGE_TOKENS.get(first)


def language_from_name(name: str) -> str | None:
    """Match whole filename tokens only.

    Substring matching is wrong here: "charlie_chaplin_film_fest.srt" contains
    "es" inside "fest" and would be labelled Spanish. Only the last two tokens
    before the extension are read ("film.en.srt", "film_english.srt"), so a
    title word such as "de" or "it" is not taken for a language.
    """
    tokens = [t for t in re.split(r"[^a-z]+", Path(name).stem.lower()) if t]
    for position, token in enumerate(reversed(tokens[-2:])):
        # A two-letter code only counts as the very last token ("film.en"),
        # never inside a title ("la_vie_de_chateau").
        if len(token) == 2 and position > 0:
            continue
        language = _LANGUAGE_TOKENS.get(token)
        if language:
            return language
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
