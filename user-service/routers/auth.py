import secrets
from datetime import datetime, timedelta, timezone

import aiosmtplib
from email.message import EmailMessage
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from auth import (
    get_password_hash, verify_password, set_auth_cookie, get_db, get_optional_user_id,
    form_error, parse_form,
    FRONTEND_URL, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM,
)
from models import User
from schemas import UserCreate, UserLogin, ForgotPasswordRequest, ResetPasswordRequest

router = APIRouter()


def user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "preferred_language": user.preferred_language,
        "profile_picture": user.profile_picture,
    }


async def _send_reset_email(to_email: str, token: str) -> None:
    reset_url = f"{FRONTEND_URL}/reset-password?token={token}"
    if not SMTP_HOST or not SMTP_USER:
        print(f"[DEV] Password reset link for {to_email}:")
        print(f"[DEV]   {reset_url}")
        return
    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to_email
    msg["Subject"] = "Password Reset — Lumière"
    msg.set_content(
        f"To reset your password, visit the link below.\n\n"
        f"{reset_url}\n\n"
        f"This link expires in 1 hour. If you did not request a reset, ignore this email."
    )
    await aiosmtplib.send(
        msg,
        hostname=SMTP_HOST,
        port=SMTP_PORT,
        username=SMTP_USER,
        password=SMTP_PASSWORD,
        start_tls=True,
    )


@router.get("/session")
async def session(request: Request, db: AsyncSession = Depends(get_db)):
    """Who is logged in, if anyone. Always 200, so a logged-out visitor's page
    load never prints a 401 in the console."""
    user_id = get_optional_user_id(request)
    if user_id is None:
        return {"authenticated": False, "user": None}
    user = (await db.execute(select(User).where(User.id == user_id))).scalars().first()
    if not user:
        return {"authenticated": False, "user": None}
    return {"authenticated": True, "user": user_payload(user)}


@router.post("/register")
async def register(request: Request, db: AsyncSession = Depends(get_db)):
    user, error = await parse_form(request, UserCreate)
    if error:
        return error
    email = user.email.lower()

    result = await db.execute(select(User).where(func.lower(User.email) == email))
    if result.scalars().first():
        return form_error("Email already registered")

    result = await db.execute(select(User).where(func.lower(User.username) == user.username.lower()))
    if result.scalars().first():
        return form_error("Username already taken")

    new_user = User(
        email=email,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        hashed_password=get_password_hash(user.password),
        preferred_language=user.preferred_language,
    )
    db.add(new_user)
    await db.commit()
    return {"ok": True, "message": "Registration successful"}


@router.post("/login")
async def login(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    credentials, error = await parse_form(request, UserLogin)
    if error:
        return form_error("Incorrect credentials")

    identifier = credentials.identifier.strip()
    result = await db.execute(
        select(User).where(or_(func.lower(User.email) == identifier.lower(), User.username == identifier))
    )
    db_user = result.scalars().first()

    if not db_user or not db_user.hashed_password:
        return form_error("Incorrect credentials")
    if not verify_password(credentials.password, db_user.hashed_password):
        return form_error("Incorrect credentials")

    set_auth_cookie(response, db_user.id)
    return {"ok": True, "message": "Login successful"}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", samesite="lax")
    return {"ok": True, "message": "Logged out successfully"}


@router.post("/forgot-password")
async def forgot_password(request: Request, db: AsyncSession = Depends(get_db)):
    data, error = await parse_form(request, ForgotPasswordRequest)
    if error:
        return error
    result = await db.execute(select(User).where(func.lower(User.email) == data.email.lower()))
    user = result.scalars().first()
    if user:
        token = secrets.token_urlsafe(32)
        user.password_reset_token = token
        user.password_reset_expires = datetime.now(timezone.utc) + timedelta(hours=1)
        await db.commit()
        try:
            await _send_reset_email(user.email, token)
        except Exception as e:
            print(f"[WARN] Failed to send reset email: {e}")
    # Same answer either way, so the form cannot be used to discover accounts.
    return {"ok": True, "message": "If this email is registered, you will receive a reset link."}


@router.post("/reset-password")
async def reset_password(request: Request, db: AsyncSession = Depends(get_db)):
    data, error = await parse_form(request, ResetPasswordRequest)
    if error:
        return error
    result = await db.execute(select(User).where(User.password_reset_token == data.token))
    user = result.scalars().first()
    if not user or not user.password_reset_expires:
        return form_error("Invalid or expired token")
    if datetime.now(timezone.utc) > user.password_reset_expires:
        return form_error("Reset token has expired")

    user.hashed_password = get_password_hash(data.new_password)
    user.password_reset_token = None
    user.password_reset_expires = None
    await db.commit()
    return {"ok": True, "message": "Password reset successfully"}
