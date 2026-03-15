import os
from pathlib import Path

DATABASE_URL = os.getenv("DATABASE_URL")
YTS_LIST_MOVIES_URL = "https://yts.mx/api/v2/list_movies.json"
ARCHIVE_ADVANCEDSEARCH_URL = "https://archive.org/advancedsearch.php"
OMDB_BASE_URL = "https://www.omdbapi.com/"
OMDB_API_KEY = os.getenv("OMDB_API_KEY", "").strip()

DEFAULT_SEARCH_LIMIT = 24
MAX_SEARCH_LIMIT = 50
MAX_OMDB_ENRICH = 12

MEDIA_ROOT = Path(os.getenv("TORRENT_MEDIA_DIR", "/data/media"))
SUBTITLES_ROOT = Path(os.getenv("TORRENT_SUBTITLES_DIR", "/data/subtitles"))
RETENTION_DAYS = int(os.getenv("MEDIA_RETENTION_DAYS", "30"))

BUFFER_READY_BYTES = int(os.getenv("STREAM_BUFFER_BYTES", str(20 * 1024 * 1024)))
TORRENT_POLL_SECONDS = float(os.getenv("TORRENT_POLL_SECONDS", "1.0"))

NOISY_ARCHIVE_TERMS = {
    "template",
    "test file",
    "graphics",
    "stock footage",
    "capcut",
    "tutorial",
    "how to",
}
