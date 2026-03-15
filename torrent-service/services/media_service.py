from pathlib import Path

from fastapi.responses import StreamingResponse

from services.common import guess_media_type, iter_file_chunks, parse_range_header


def build_streaming_response(path: Path, range_header: str | None) -> StreamingResponse:
    file_size = path.stat().st_size
    media_type = guess_media_type(path)
    parsed_range = parse_range_header(range_header, file_size)

    if parsed_range is None:
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
        }
        return StreamingResponse(
            iter_file_chunks(path, 0, file_size - 1),
            status_code=200,
            media_type=media_type,
            headers=headers,
        )

    start, end = parsed_range
    chunk_len = end - start + 1
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Content-Length": str(chunk_len),
    }
    return StreamingResponse(
        iter_file_chunks(path, start, end),
        status_code=206,
        media_type=media_type,
        headers=headers,
    )


def subtitle_media_type(path: Path) -> str:
    if path.suffix.lower() == ".srt":
        return "application/x-subrip"
    return "text/vtt"
