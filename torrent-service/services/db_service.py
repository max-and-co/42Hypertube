import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

import runtime_state
from config import MEDIA_ROOT, RETENTION_DAYS, SUBTITLES_ROOT


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


def _delete_stale_files(root: Path, max_age_seconds: int) -> None:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            age_seconds = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
            if age_seconds > max_age_seconds:
                path.unlink(missing_ok=True)
        except OSError:
            continue


async def retention_cleanup_loop() -> None:
    while True:
        try:
            await db_execute(
                """
                UPDATE movies
                SET stream_status = 'not_started', video_path = NULL
                WHERE last_watched_at IS NOT NULL
                  AND last_watched_at < (NOW() - (:days || ' days')::interval)
                """,
                {"days": RETENTION_DAYS},
            )

            stale_rows = await db_fetch_one(
                """
                SELECT COUNT(*)::int AS total
                FROM movies
                WHERE last_watched_at IS NOT NULL
                  AND last_watched_at < (NOW() - (:days || ' days')::interval)
                """,
                {"days": RETENTION_DAYS},
            )

            if stale_rows and int(stale_rows.get("total") or 0) >= 0:
                max_age_seconds = RETENTION_DAYS * 24 * 60 * 60
                _delete_stale_files(MEDIA_ROOT, max_age_seconds)
                _delete_stale_files(SUBTITLES_ROOT, max_age_seconds)
        except Exception:
            pass

        await asyncio.sleep(6 * 60 * 60)
