from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
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
    duration_minutes = Column(Integer, nullable=True)
    available_subtitles = Column(String, nullable=True)  # comma-separated: "en,fr,es"
    thumbnail = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    genres = Column(String, nullable=True)             # comma-separated
    torrent_hash = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=False)
    movie_id = Column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
