from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean, UniqueConstraint, Float
from sqlalchemy.orm import declarative_base
from datetime import datetime, timezone

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=True)  # nullable for OAuth-only users
    profile_picture = Column(String, nullable=True)
    preferred_language = Column(String, default="en", nullable=False)
    oauth_provider = Column(String, nullable=True)   # "42" or "github"
    oauth_id = Column(String, nullable=True)
    password_reset_token = Column(String, nullable=True)
    password_reset_expires = Column(DateTime(timezone=True), nullable=True)


class Movie(Base):
    __tablename__ = "movies"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    year = Column(Integer, nullable=True)
    imdb_rating = Column(String(10), nullable=True)   # e.g. "8.1"
    imdb_id = Column(String(20), nullable=True, unique=True)
    tmdb_id = Column(String(20), nullable=True)
    duration_minutes = Column(Integer, nullable=True)
    producer = Column(String, nullable=True)
    director = Column(String, nullable=True)
    main_cast = Column(Text, nullable=True)  # comma-separated names
    available_subtitles = Column(String, nullable=True)  # comma-separated: "en,fr,es"
    subtitle_languages = Column(String, nullable=True)  # comma-separated normalized codes
    thumbnail = Column(String, nullable=True)
    cover_image = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    genres = Column(String, nullable=True)             # comma-separated
    original_language = Column(String(16), nullable=True)
    external_source = Column(String(32), nullable=True, index=True)
    external_id = Column(String(128), nullable=True, index=True)
    torrent_hash = Column(String, nullable=True)
    stream_status = Column(String(32), nullable=False, default="not_started")
    video_path = Column(String, nullable=True)
    last_watched_at = Column(DateTime(timezone=True), nullable=True)
    last_accessed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=False)
    movie_id = Column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ExternalMovieCache(Base):
    __tablename__ = "external_movie_cache"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(32), nullable=False, index=True)
    external_id = Column(String(128), nullable=False, index=True)
    imdb_id = Column(String(20), nullable=True, index=True)
    title = Column(String, nullable=False)
    year = Column(Integer, nullable=True)
    genres = Column(String, nullable=True)
    imdb_rating = Column(Float, nullable=True)
    thumbnail = Column(String, nullable=True)
    downloads = Column(Integer, nullable=True)
    seeders = Column(Integer, nullable=True)
    peers = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_external_movie_source_id"),)


class MovieWatchState(Base):
    __tablename__ = "movie_watch_state"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    source = Column(String(32), nullable=False, index=True)
    external_id = Column(String(128), nullable=False, index=True)
    watched = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("user_id", "source", "external_id", name="uq_user_watch_source_id"),)
