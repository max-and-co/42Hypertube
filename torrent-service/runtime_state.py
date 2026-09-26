import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass
class TorrentFile:
    """The video file a session streams, while it downloads and after."""
    path: Path
    size: int
    handle: Any = None        # libtorrent handle while downloading
    file_offset: int = 0      # where this file starts inside the torrent's pieces
    piece_length: int = 0
    complete: bool = False    # every byte is on disk
    failed: bool = False      # the download stopped before completing


@dataclass
class LiveOutput:
    """A growing fragmented-mp4 file written by FFmpeg while it converts."""
    path: Path
    done: bool = False
    failed: bool = False
    started: asyncio.Event = field(default_factory=asyncio.Event)


STREAM_SESSIONS: dict[str, dict[str, Any]] = {}
STREAM_INDEX: dict[str, str] = {}
STREAM_LOCK = asyncio.Lock()
TORRENT_RUNNERS: dict[str, asyncio.Task[None]] = {}
BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()

SOURCES: dict[str, TorrentFile] = {}
LIVE_OUTPUTS: dict[str, LiveOutput] = {}

DB_ENGINE: AsyncEngine | None = None
