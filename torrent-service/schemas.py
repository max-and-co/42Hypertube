from typing import Literal

from pydantic import BaseModel, Field


class StreamSessionCreate(BaseModel):
    """Names the film only; its database row is looked up server side."""
    source: Literal["archive", "peertube"]
    external_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:\-]+$")
