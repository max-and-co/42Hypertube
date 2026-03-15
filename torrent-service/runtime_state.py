import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

STREAM_SESSIONS: dict[str, dict[str, Any]] = {}
STREAM_INDEX: dict[str, str] = {}
STREAM_LOCK = asyncio.Lock()
TORRENT_RUNNERS: dict[str, asyncio.Task[None]] = {}

DB_ENGINE: AsyncEngine | None = None
