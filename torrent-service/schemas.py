from pydantic import BaseModel


class StreamSessionCreate(BaseModel):
    movie_id: int
    source: str
    external_id: str
    title: str
    torrent_hash: str | None = None
