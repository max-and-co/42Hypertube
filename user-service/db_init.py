from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


STARTUP_MIGRATIONS = [
    """
    CREATE TABLE IF NOT EXISTS external_movie_cache (
        id SERIAL PRIMARY KEY,
        source VARCHAR(32) NOT NULL,
        external_id VARCHAR(128) NOT NULL,
        imdb_id VARCHAR(20),
        title VARCHAR NOT NULL,
        year INTEGER,
        genres VARCHAR,
        imdb_rating DOUBLE PRECISION,
        thumbnail VARCHAR,
        downloads INTEGER,
        seeders INTEGER,
        peers INTEGER,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        CONSTRAINT uq_external_movie_source_id UNIQUE (source, external_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS movie_watch_state (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        source VARCHAR(32) NOT NULL,
        external_id VARCHAR(128) NOT NULL,
        watched BOOLEAN NOT NULL DEFAULT FALSE,
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        CONSTRAINT uq_user_watch_source_id UNIQUE (user_id, source, external_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_external_movie_cache_title ON external_movie_cache (title)",
    "CREATE INDEX IF NOT EXISTS idx_external_movie_cache_year ON external_movie_cache (year)",
    "CREATE INDEX IF NOT EXISTS idx_external_movie_cache_rating ON external_movie_cache (imdb_rating)",
    "CREATE INDEX IF NOT EXISTS idx_external_movie_cache_downloads ON external_movie_cache (downloads)",
    "CREATE INDEX IF NOT EXISTS idx_external_movie_cache_seeders_peers ON external_movie_cache (seeders, peers)",
    "CREATE INDEX IF NOT EXISTS idx_movie_watch_state_user ON movie_watch_state (user_id)",
    "ALTER TABLE movies ADD COLUMN IF NOT EXISTS tmdb_id VARCHAR(20)",
    "ALTER TABLE movies ADD COLUMN IF NOT EXISTS producer VARCHAR",
    "ALTER TABLE movies ADD COLUMN IF NOT EXISTS director VARCHAR",
    "ALTER TABLE movies ADD COLUMN IF NOT EXISTS main_cast TEXT",
    "ALTER TABLE movies ADD COLUMN IF NOT EXISTS subtitle_languages VARCHAR",
    "ALTER TABLE movies ADD COLUMN IF NOT EXISTS cover_image VARCHAR",
    "ALTER TABLE movies ADD COLUMN IF NOT EXISTS original_language VARCHAR(16)",
    "ALTER TABLE movies ADD COLUMN IF NOT EXISTS external_source VARCHAR(32)",
    "ALTER TABLE movies ADD COLUMN IF NOT EXISTS external_id VARCHAR(128)",
    "ALTER TABLE movies ADD COLUMN IF NOT EXISTS stream_status VARCHAR(32) NOT NULL DEFAULT 'not_started'",
    "ALTER TABLE movies ADD COLUMN IF NOT EXISTS video_path VARCHAR",
    "ALTER TABLE movies ADD COLUMN IF NOT EXISTS last_watched_at TIMESTAMPTZ",
    "ALTER TABLE movies ADD COLUMN IF NOT EXISTS last_accessed_at TIMESTAMPTZ",
    "CREATE INDEX IF NOT EXISTS idx_movies_external_source_id ON movies (external_source, external_id)",
]


async def run_startup_migrations(conn: AsyncConnection) -> None:
    for statement in STARTUP_MIGRATIONS:
        await conn.execute(text(statement))
