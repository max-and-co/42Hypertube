"""Thin async wrapper around one shared libtorrent session.

Only the selected video file is downloaded, in sequential piece order so the
start of the movie arrives first. Readers wait for the exact pieces covering a
byte range (and bump their priority with a deadline), so the player can stream
while the rest of the file is still downloading.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any

try:
    import libtorrent as lt  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional dependency at runtime
    lt = None

logger = logging.getLogger(__name__)

_SESSION: Any = None
_TORRENTS: dict[str, "TorrentStream"] = {}

PRIORITY_SKIP = 0
PRIORITY_BACKGROUND = 1
PRIORITY_TOP = 7
# Pieces fetched ahead of the reader at top priority.
LOOKAHEAD_PIECES = 6


def available() -> bool:
    return lt is not None


def _session() -> Any:
    global _SESSION
    if _SESSION is None:
        if lt is None:
            raise RuntimeError("libtorrent unavailable in container")
        _SESSION = lt.session(
            {
                "listen_interfaces": "0.0.0.0:6881,[::]:6881",
                "enable_dht": True,
                "enable_lsd": True,
                "alert_mask": 0,
            }
        )
    return _SESSION


class TorrentStream:
    """One torrent, one wanted video file inside it."""

    def __init__(self, key: str, handle: Any, info: Any, file_index: int, save_path: Path) -> None:
        self.key = key
        self.handle = handle
        self.info = info
        self.file_index = file_index
        self.save_path = save_path
        files = info.files()
        self.file_size = int(files.file_size(file_index))
        self.relative_path = files.file_path(file_index)
        self.path = save_path / self.relative_path
        self.piece_length = int(info.piece_length())

    # ── piece helpers ────────────────────────────────────────────────────────
    def _piece_span(self, start: int, end: int) -> range:
        """Pieces covering file bytes [start, end] (inclusive)."""
        end = min(end, self.file_size - 1)
        first = self.info.map_file(self.file_index, start, 1).piece
        last = self.info.map_file(self.file_index, end, 1).piece
        return range(first, last + 1)

    def has_range(self, start: int, end: int) -> bool:
        return all(self.handle.have_piece(p) for p in self._piece_span(start, end))

    def range_progress(self, start: int, end: int) -> float:
        span = self._piece_span(start, end)
        if not len(span):
            return 1.0
        return sum(1 for p in span if self.handle.have_piece(p)) / len(span)

    def _boost(self, pieces: range, base_deadline_ms: int) -> None:
        """Top priority + deadline: the rest of the file downloads at background
        priority, so peers and web seeds serve these pieces first."""
        last_piece = self.info.num_pieces() - 1
        window = range(pieces.start, min(pieces.stop + LOOKAHEAD_PIECES, last_piece + 1))
        for offset, piece in enumerate(window):
            if not self.handle.have_piece(piece):
                self.handle.piece_priority(piece, PRIORITY_TOP)
                self.handle.set_piece_deadline(piece, base_deadline_ms + offset * 300)

    async def wait_for_range(self, start: int, end: int, timeout: float = 120.0) -> bool:
        """Wait until bytes [start, end] are on disk, prioritising those pieces."""
        span = self._piece_span(start, end)
        self._boost(span, 200)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if all(self.handle.have_piece(p) for p in span):
                return True
            await asyncio.sleep(0.25)
        return False

    def prioritize_head(self, buffer_bytes: int) -> None:
        """Mark the opening buffer (and the last piece, where a non-faststart MP4
        keeps its index) time-critical so playback can start quickly even when
        peers would otherwise send pieces from the middle of the file."""
        self._boost(self._piece_span(0, min(buffer_bytes, self.file_size) - 1), 1000)
        self._boost(self._piece_span(self.file_size - 1, self.file_size - 1), 2000)

    def is_file_complete(self) -> bool:
        progress = self.handle.file_progress(flags=1)  # piece granularity
        return int(progress[self.file_index]) >= self.file_size

    def stats(self) -> dict[str, Any]:
        st = self.handle.status()
        return {
            "progress": round(float(st.progress), 4),
            "download_rate": int(st.download_rate),
            "peers": int(st.num_peers),
            "seeds": int(st.num_seeds),
        }


def add_torrent(
    key: str,
    torrent_bytes: bytes,
    save_path: Path,
    choose_file,
) -> TorrentStream:
    """Add (or reuse) a torrent; `choose_file(info) -> index` picks the video."""
    if key in _TORRENTS:
        return _TORRENTS[key]
    info = lt.torrent_info(lt.bdecode(torrent_bytes))  # type: ignore[union-attr]
    file_index = choose_file(info)
    if file_index is None:
        raise RuntimeError("No playable video file in torrent")
    priorities = [PRIORITY_SKIP] * info.num_files()
    priorities[file_index] = PRIORITY_BACKGROUND
    save_path.mkdir(parents=True, exist_ok=True)
    handle = _session().add_torrent(
        {
            "ti": info,
            "save_path": str(save_path),
            "file_priorities": priorities,
            "flags": lt.torrent_flags.sequential_download,  # type: ignore[union-attr]
        }
    )
    stream = TorrentStream(key, handle, info, file_index, save_path)
    _TORRENTS[key] = stream
    logger.info("Torrent added", extra={"key": key, "file": stream.relative_path, "size": stream.file_size})
    return stream


def get(key: str) -> TorrentStream | None:
    return _TORRENTS.get(key)


def remove(key: str) -> None:
    stream = _TORRENTS.pop(key, None)
    if stream is not None and _SESSION is not None:
        _SESSION.remove_torrent(stream.handle)
