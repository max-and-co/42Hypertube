import secrets
from datetime import datetime, timedelta, timezone

import aiosmtplib
from email.message import EmailMessage
from fastapi import APIRouter, Depends, Response, HTTPException, status
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from auth import (
    get_password_hash, verify_password, set_auth_cookie, get_db,
    FRONTEND_URL, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM,
)
from models import User
from schemas import UserCreate, UserLogin, ForgotPasswordRequest, ResetPasswordRequest

router = APIRouter()


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


@router.post("/register")
async def register(user: UserCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == user.email))
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Email already registered")

    result = await db.execute(select(User).where(User.username == user.username))
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Username already taken")

    new_user = User(
        email=user.email,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        hashed_password=get_password_hash(user.password),
        preferred_language=user.preferred_language,
    )
    db.add(new_user)
    await db.commit()
    return {"message": "Registration successful"}


@router.post("/login")
async def login(response: Response, user: UserLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(or_(User.email == user.identifier, User.username == user.identifier))
    )
    db_user = result.scalars().first()

    if not db_user or not db_user.hashed_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect credentials")
    if not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect credentials")

    set_auth_cookie(response, db_user.id)
    return {"message": "Login successful"}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token")
    return {"message": "Logged out successfully"}


@router.post("/forgot-password")
async def forgot_password(data: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
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
    return {"message": "If this email is registered, you will receive a reset link."}


@router.post("/reset-password")
async def reset_password(data: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.password_reset_token == data.token))
    user = result.scalars().first()
    if not user or not user.password_reset_expires:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    if datetime.now(timezone.utc) > user.password_reset_expires:
        raise HTTPException(status_code=400, detail="Reset token has expired")

    user.hashed_password = get_password_hash(data.new_password)
    user.password_reset_token = None
    user.password_reset_expires = None
    await db.commit()
    return {"message": "Password reset successfully"}
