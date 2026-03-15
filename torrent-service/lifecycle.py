import asyncio
from contextlib import asynccontextmanager
from contextlib import suppress

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import runtime_state
from config import DATABASE_URL, MEDIA_ROOT, SUBTITLES_ROOT
from services.db_service import retention_cleanup_loop
from services.session_service import cancel_all_stream_tasks


@asynccontextmanager
async def lifespan(app: FastAPI):
    retries = 10
    while retries > 0:
        try:
            print(f"Connecting to DB... ({retries} retries left)")
            runtime_state.DB_ENGINE = create_async_engine(DATABASE_URL)
            async with runtime_state.DB_ENGINE.connect() as conn:
                await conn.execute(text("SELECT 1"))
            print("Database connected successfully.")
            break
        except Exception as exc:
            print(f"Database not ready yet: {exc}")
            retries -= 1
            await asyncio.sleep(2)

    MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
    SUBTITLES_ROOT.mkdir(parents=True, exist_ok=True)
    cleanup_task = asyncio.create_task(retention_cleanup_loop())

    try:
        yield
    finally:
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task
        await cancel_all_stream_tasks()

        if runtime_state.DB_ENGINE is not None:
            await runtime_state.DB_ENGINE.dispose()
            runtime_state.DB_ENGINE = None
