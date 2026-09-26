import os
from pathlib import Path

DATABASE_URL = os.getenv("DATABASE_URL")

# ── Sources ───────────────────────────────────────────────────────────────────
# Both sources are royalty-free / legally distributable, as required by the
# subject. Archive.org is one of the two sources the subject names explicitly;
# PeerTube results are filtered to Creative Commons / public-domain licences.

ARCHIVE_ADVANCEDSEARCH_URL = "https://archive.org/advancedsearch.php"
ARCHIVE_METADATA_URL = "https://archive.org/metadata"
ARCHIVE_TRACKERS = [
    "http://bt1.archive.org:6969/announce",
    "http://bt2.archive.org:6969/announce",
]

# SepiaSearch is the official cross-instance PeerTube search index.
PEERTUBE_SEARCH_URL = os.getenv(
    "PEERTUBE_SEARCH_URL", "https://sepiasearch.org/api/v1/search/videos"
).strip()
# PeerTube licence ids: 1 CC-BY, 2 CC-BY-SA, 3 CC-BY-ND, 4 CC-BY-NC,
# 5 CC-BY-NC-SA, 6 CC-BY-NC-ND, 7 Public Domain. Anything outside this set
# ("Unknown" / "All Rights Reserved") is never surfaced.
PEERTUBE_FREE_LICENCES = [1, 2, 3, 4, 5, 6, 7]
# When browsing (no search term) only show feature-length content, so the
# catalogue reads like a film library rather than a pile of short clips.
PEERTUBE_BROWSE_MIN_DURATION = int(os.getenv("PEERTUBE_BROWSE_MIN_DURATION", "2400"))

OMDB_BASE_URL = "https://www.omdbapi.com/"
OMDB_API_KEY = os.getenv("OMDB_API_KEY", "").strip()

DEFAULT_SEARCH_LIMIT = 24
MAX_SEARCH_LIMIT = 50

DEFAULT_SOURCE = "archive"
SUPPORTED_SOURCES = ("archive", "peertube")

MEDIA_ROOT = Path(os.getenv("TORRENT_MEDIA_DIR", "/data/media"))
SUBTITLES_ROOT = Path(os.getenv("TORRENT_SUBTITLES_DIR", "/data/subtitles"))
RETENTION_DAYS = int(os.getenv("MEDIA_RETENTION_DAYS", "30"))

# Played while downloading: ready once this many bytes from the START of the
# film are on disk (pieces are fetched in order, see session_service).
BUFFER_READY_BYTES = int(os.getenv("STREAM_BUFFER_BYTES", str(20 * 1024 * 1024)))
# A converted (mkv...) stream is ready once FFmpeg has written this much.
LIVE_READY_BYTES = int(os.getenv("STREAM_LIVE_READY_BYTES", str(1024 * 1024)))
# How long a player request may wait for a piece before the response ends.
STREAM_WAIT_SECONDS = float(os.getenv("STREAM_WAIT_SECONDS", "120"))

# Optional: English / preferred-language subtitles for films with an IMDb id.
OPENSUBTITLES_API_KEY = os.getenv("OPENSUBTITLES_API_KEY", "").strip()
TORRENT_POLL_SECONDS = float(os.getenv("TORRENT_POLL_SECONDS", "1.0"))
# A session must not sit at "buffering" forever with no explanation.
METADATA_TIMEOUT_SECONDS = float(os.getenv("STREAM_METADATA_TIMEOUT", "90"))
STALL_TIMEOUT_SECONDS = float(os.getenv("STREAM_STALL_TIMEOUT", "240"))

NOISY_ARCHIVE_TERMS = {
    "template",
    "test file",
    "graphics",
    "stock footage",
    "capcut",
    "tutorial",
    "how to",
}
