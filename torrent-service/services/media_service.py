from pathlib import Path

from fastapi.responses import Response, StreamingResponse

from runtime_state import LiveOutput, TorrentFile
from services.common import guess_media_type, parse_range_header


def build_streaming_response(src: TorrentFile, range_header: str | None) -> Response:
    """Byte-range answer for a file that may still be downloading.

    Sizes come from the torrent, not from the file on disk, and every chunk
    waits for its pieces (session_service.iter_source) - so a player never
    receives bytes that have not been downloaded yet.
    """
    from services.session_service import iter_source  # avoid an import cycle

    file_size = src.size
    media_type = guess_media_type(src.path)
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "no-store"}

    if range_header and range_header.startswith("bytes="):
        parsed = parse_range_header(range_header, file_size)
        if parsed is None:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
        start, end = parsed
        headers.update({"Content-Range": f"bytes {start}-{end}/{file_size}", "Content-Length": str(end - start + 1)})
        return StreamingResponse(iter_source(src, start, end), status_code=206, media_type=media_type, headers=headers)

    headers["Content-Length"] = str(file_size)
    return StreamingResponse(iter_source(src, 0, file_size - 1), status_code=200, media_type=media_type, headers=headers)


def build_live_response(out: LiveOutput) -> StreamingResponse:
    """A conversion in progress has no final size yet: send it as it grows.
    No Accept-Ranges, so the browser plays it front to back."""
    from services.session_service import iter_live

    return StreamingResponse(iter_live(out), status_code=200, media_type="video/mp4", headers={"Cache-Control": "no-store"})


def subtitle_media_type(path: Path) -> str:
    return "text/vtt"
