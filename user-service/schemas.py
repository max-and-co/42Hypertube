import re
from typing import Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, EmailStr, Field, field_validator

# Every field a user can type is validated here, server side. The frontend runs
# the same checks for instant feedback, but these are the ones that count.

Language = Literal["en", "fr", "es"]

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")
# Letters (any alphabet), single spaces, apostrophes and hyphens: "Jean-Luc", "O'Neil".
NAME_RE = re.compile(r"^[^\W\d_]+(?:[ '\-][^\W\d_]+)*$")
AVATAR_PATH_RE = re.compile(r"^/api/users/avatars/[0-9a-f-]{36}\.(png|jpg|gif|webp)$")

MAX_COMMENT_LENGTH = 1000


def check_username(value: Optional[str]) -> Optional[str]:
    if value is None:
        return value
    value = value.strip()
    if not USERNAME_RE.fullmatch(value):
        raise ValueError("Username must be 3-30 characters: letters, digits, '.', '_' or '-'")
    return value


def check_name(value: Optional[str]) -> Optional[str]:
    if value is None:
        return value
    value = " ".join(value.split())
    if not 1 <= len(value) <= 50 or not NAME_RE.fullmatch(value):
        raise ValueError("Names must be 1-50 letters (spaces, ' and - allowed)")
    return value


def check_password(value: Optional[str]) -> Optional[str]:
    if value is None:
        return value
    if not 8 <= len(value) <= 128:
        raise ValueError("Password must be 8-128 characters")
    if not re.search(r"[^\W\d_]", value) or not re.search(r"\d", value):
        raise ValueError("Password must contain at least one letter and one digit")
    return value


def check_comment(value: Optional[str]) -> Optional[str]:
    if value is None:
        return value
    value = value.strip()
    if not value:
        raise ValueError("Comment cannot be empty")
    if len(value) > MAX_COMMENT_LENGTH:
        raise ValueError(f"Comment must be at most {MAX_COMMENT_LENGTH} characters")
    return value


def check_picture_url(value: Optional[str]) -> Optional[str]:
    """A profile picture is either one of our own uploads or a public https URL."""
    if value is None:
        return value
    value = value.strip()
    if len(value) > 2048:
        raise ValueError("Profile picture URL is too long")
    if AVATAR_PATH_RE.fullmatch(value):
        return value
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Profile picture must be an uploaded avatar or an https URL")
    return value


class UserCreate(BaseModel):
    email: EmailStr = Field(max_length=254)
    username: str
    first_name: str
    last_name: str
    password: str
    preferred_language: Language = "en"

    v_username = field_validator("username")(check_username)
    v_names = field_validator("first_name", "last_name")(check_name)
    v_password = field_validator("password")(check_password)


class UserLogin(BaseModel):
    identifier: str = Field(min_length=1, max_length=254)  # username OR email
    password: str = Field(min_length=1, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr = Field(max_length=254)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    new_password: str

    v_password = field_validator("new_password")(check_password)


class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    email: Optional[EmailStr] = Field(default=None, max_length=254)
    preferred_language: Optional[Language] = None

    v_username = field_validator("username")(check_username)
    v_names = field_validator("first_name", "last_name")(check_name)


class UserUpdateById(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = Field(default=None, max_length=254)
    password: Optional[str] = None
    profile_picture: Optional[str] = None

    v_username = field_validator("username")(check_username)
    v_password = field_validator("password")(check_password)
    v_picture = field_validator("profile_picture")(check_picture_url)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str

    v_password = field_validator("new_password")(check_password)


class CommentCreate(BaseModel):
    comment: str
    movie_id: Optional[int] = Field(default=None, ge=1)  # required for POST /comments

    v_comment = field_validator("comment")(check_comment)


class CommentUpdate(BaseModel):
    comment: Optional[str] = None
    username: Optional[str] = None  # accepted per the subject's API doc, never persisted

    v_comment = field_validator("comment")(check_comment)


class WatchToggleRequest(BaseModel):
    watched: Optional[bool] = None


class ExternalMovieIngestRequest(BaseModel):
    """Only identifies the film. Everything shown about it is fetched server side."""
    source: Literal["archive", "peertube"]
    external_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:\-]+$")
