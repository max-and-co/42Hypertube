import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import text

import runtime_state
from config import MEDIA_ROOT, RETENTION_DAYS

logger = logging.getLogger(__name__)


async def db_execute(statement: str, params: dict[str, Any]) -> None:
    if runtime_state.DB_ENGINE is None:
        return
    async with runtime_state.DB_ENGINE.begin() as conn:
        await conn.execute(text(statement), params)


async def db_fetch_one(statement: str, params: dict[str, Any]) -> dict[str, Any] | None:
    if runtime_state.DB_ENGINE is None:
        return None
    async with runtime_state.DB_ENGINE.connect() as conn:
        result = await conn.execute(text(statement), params)
        row = result.mappings().first()
        return dict(row) if row else None


async def db_fetch_all(statement: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    if runtime_state.DB_ENGINE is None:
        return []
    async with runtime_state.DB_ENGINE.connect() as conn:
        result = await conn.execute(text(statement), params)
        return [dict(row) for row in result.mappings().all()]


async def update_movie_state(movie_id: int, **fields: Any) -> None:
    if not fields:
        return

    set_parts = []
    params: dict[str, Any] = {"movie_id": movie_id}
    for key, value in fields.items():
        set_parts.append(f"{key} = :{key}")
        params[key] = value

    statement = f"UPDATE movies SET {', '.join(set_parts)} WHERE id = :movie_id"
    await db_execute(statement, params)


async def fetch_user_pref_language(user_id: int) -> str:
    row = await db_fetch_one("SELECT preferred_language FROM users WHERE id = :user_id", {"user_id": user_id})
    if not row:
        return "en"

    value = str(row.get("preferred_language") or "en").strip().lower()
    return value or "en"


def _movie_dir_for(video_path: str) -> Path | None:
    """Map a stored video_path back to the per-movie download directory.

    Guards against deleting anything outside MEDIA_ROOT.
    """
    try:
        resolved = Path(video_path).resolve()
        root = MEDIA_ROOT.resolve()
        relative = resolved.relative_to(root)
    except (ValueError, OSError):
        return None

    if not relative.parts:
        return None
    return root / relative.parts[0]


async def purge_unwatched_movies() -> int:
    """Erase movies nobody has watched for RETENTION_DAYS.

    The subject says a movie unwatched for a month is erased, so retention is
    keyed on last_watched_at per movie - never on file mtime, which would also
    delete a film watched yesterday that happens to have downloaded long ago.
    """
    stale = await db_fetch_all(
        """
        SELECT id, video_path
        FROM movies
        WHERE video_path IS NOT NULL
          AND last_watched_at IS NOT NULL
          AND last_watched_at < (NOW() - make_interval(days => :days))
        """,
        {"days": RETENTION_DAYS},
    )

    for row in stale:
        directory = _movie_dir_for(str(row.get("video_path") or ""))
        if directory is not None and directory.exists():
            shutil.rmtree(directory, ignore_errors=True)
            logger.info("Erased unwatched movie", extra={"movie_id": row["id"], "path": str(directory)})

        await db_execute(
            "UPDATE movies SET stream_status = 'not_started', video_path = NULL WHERE id = :id",
            {"id": row["id"]},
        )

    return len(stale)


async def retention_cleanup_loop() -> None:
    while True:
        try:
            await purge_unwatched_movies()
        except Exception:
            logger.exception("Retention cleanup failed")

        await asyncio.sleep(6 * 60 * 60)
