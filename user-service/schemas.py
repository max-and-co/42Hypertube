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
