from typing import Optional
from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    username: str
    first_name: str
    last_name: str
    password: str
    preferred_language: str = "en"


class UserLogin(BaseModel):
    identifier: str   # username OR email
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    preferred_language: Optional[str] = None


class UserUpdateById(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    profile_picture: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class CommentCreate(BaseModel):
    comment: str
    movie_id: Optional[int] = None  # required for POST /comments, inferred for POST /movies/:id/comments


class CommentUpdate(BaseModel):
    comment: Optional[str] = None
    username: Optional[str] = None  # accepted per spec but not persisted


class DiscoverQuery(BaseModel):
    q: str = ""
    page: int = 1
    limit: int = 24
    sort_by: str = "downloads"
    sort_dir: str = "desc"
    genre: Optional[str] = None
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    imdb_min: Optional[float] = None


class WatchToggleRequest(BaseModel):
    watched: Optional[bool] = None


class ExternalMovieIngestRequest(BaseModel):
    source: str
    external_id: str
    title: str
    year: Optional[int] = None
    imdb_rating: Optional[float] = None
    imdb_id: Optional[str] = None
    tmdb_id: Optional[str] = None
    duration_minutes: Optional[int] = None
    genres: Optional[list[str]] = None
    thumbnail: Optional[str] = None
    cover_image: Optional[str] = None
    description: Optional[str] = None
    original_language: Optional[str] = None
    producer: Optional[str] = None
    director: Optional[str] = None
    main_cast: Optional[list[str]] = None
    torrent_hash: Optional[str] = None
    available_subtitles: Optional[list[str]] = None


class ExternalMovieIngestResponse(BaseModel):
    movie_id: int
    source: str
    external_id: str


class MovieCommentResponse(BaseModel):
    id: int
    content: str
    author_id: int
    author_username: str
    movie_id: int
