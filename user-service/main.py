from fastapi import FastAPI, Depends, Response, HTTPException, Request, status, File, UploadFile
from fastapi.responses import RedirectResponse, FileResponse
from contextlib import asynccontextmanager
import asyncio
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text, select, or_
from pydantic import BaseModel, EmailStr
import httpx
import aiosmtplib
from email.message import EmailMessage

from models import Base, User
from auth import get_password_hash, verify_password, create_access_token, get_current_user_from_cookie

DATABASE_URL   = os.getenv("DATABASE_URL")
FRONTEND_URL   = os.getenv("FRONTEND_URL", "http://localhost:8080")

FT_CLIENT_ID     = os.getenv("FT_CLIENT_ID", "")
FT_CLIENT_SECRET = os.getenv("FT_CLIENT_SECRET", "")
FT_REDIRECT_URI  = os.getenv("FT_REDIRECT_URI", "http://localhost:8080/api/oauth/42/callback")

GITHUB_CLIENT_ID     = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
GITHUB_REDIRECT_URI  = os.getenv("GITHUB_REDIRECT_URI", "http://localhost:8080/api/oauth/github/callback")

SMTP_HOST     = os.getenv("SMTP_HOST", "")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM     = os.getenv("SMTP_FROM", "noreply@hypertube.com")

engine = create_async_engine(DATABASE_URL)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def lifespan(app: FastAPI):
    retries = 10
    while retries > 0:
        try:
            print(f"Connecting to DB... ({retries} retries left)")
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            print("✅ Database connected & tables created successfully.")
            break
        except Exception as e:
            print(f"❌ Database not ready yet: {e}")
            retries -= 1
            await asyncio.sleep(2)
    else:
        print("❌ Could not connect to database after retries.")
    yield


app = FastAPI(lifespan=lifespan, root_path="/api/users")

os.makedirs("uploads", exist_ok=True)


async def get_db():
    async with async_session() as session:
        yield session


# ── Schemas ───────────────────────────────────────────────────────────────────

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


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _auth_cookie(response: Response, user_id: int) -> None:
    token = create_access_token(data={"sub": str(user_id)})
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=60 * 60 * 24 * 7,   # 1 week in seconds
        samesite="lax",
        secure=False,
    )


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


async def _find_or_create_oauth_user(
    db: AsyncSession,
    *,
    provider: str,
    oauth_id: str,
    email: str,
    username: str,
    first_name: str,
    last_name: str,
) -> User:
    # 1. Look up by oauth_id + provider
    result = await db.execute(
        select(User).where(User.oauth_id == oauth_id, User.oauth_provider == provider)
    )
    user = result.scalars().first()

    # 2. Fall back to email match
    if not user and email:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalars().first()

    # 3. Create new user
    if not user:
        # ensure unique username
        result = await db.execute(select(User).where(User.username == username))
        if result.scalars().first():
            username = f"{username}_{oauth_id[:6]}"
        user = User(
            email=email or f"{provider}_{oauth_id}@noemail.local",
            username=username,
            first_name=first_name,
            last_name=last_name,
            oauth_provider=provider,
            oauth_id=oauth_id,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    elif not user.oauth_id:
        user.oauth_provider = provider
        user.oauth_id = oauth_id
        await db.commit()
        await db.refresh(user)

    return user


# ── Auth endpoints (routed via /api/auth/*) ───────────────────────────────────

@app.post("/register")
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


@app.post("/login")
async def login(response: Response, user: UserLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(
            or_(User.email == user.identifier, User.username == user.identifier)
        )
    )
    db_user = result.scalars().first()

    if not db_user or not db_user.hashed_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect credentials")
    if not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect credentials")

    _auth_cookie(response, db_user.id)
    return {"message": "Login successful"}


@app.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token")
    return {"message": "Logged out successfully"}


@app.post("/forgot-password")
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
    # Always the same response — prevents email enumeration
    return {"message": "If this email is registered, you will receive a reset link."}


@app.post("/reset-password")
async def reset_password(data: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(User.password_reset_token == data.token)
    )
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


# ── User endpoints (routed via /api/users/*) ──────────────────────────────────

@app.get("/avatars/{filename}")
async def get_avatar(filename: str):
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = os.path.join("uploads", filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path)


@app.get("/me")
async def read_users_me(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_current_user_from_cookie(request)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "preferred_language": user.preferred_language,
        "profile_picture": user.profile_picture,
    }


@app.patch("/me")
async def update_me(request: Request, data: UserUpdate, db: AsyncSession = Depends(get_db)):
    user_id = get_current_user_from_cookie(request)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if data.email is not None and data.email != user.email:
        result = await db.execute(select(User).where(User.email == data.email))
        if result.scalars().first():
            raise HTTPException(status_code=400, detail="Email already in use")
        user.email = data.email

    if data.username is not None and data.username != user.username:
        result = await db.execute(select(User).where(User.username == data.username))
        if result.scalars().first():
            raise HTTPException(status_code=400, detail="Username already taken")
        user.username = data.username

    if data.first_name is not None:
        user.first_name = data.first_name
    if data.last_name is not None:
        user.last_name = data.last_name
    if data.preferred_language is not None:
        user.preferred_language = data.preferred_language

    await db.commit()
    await db.refresh(user)
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "preferred_language": user.preferred_language,
        "profile_picture": user.profile_picture,
    }


@app.post("/me/avatar")
async def upload_avatar(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    user_id = get_current_user_from_cookie(request)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "jpg"
    filename = f"{uuid.uuid4()}.{ext}"
    path = os.path.join("uploads", filename)

    content = await file.read()
    with open(path, "wb") as f:
        f.write(content)

    user.profile_picture = f"/api/users/avatars/{filename}"
    await db.commit()
    return {"profile_picture": user.profile_picture}


@app.post("/me/password")
async def change_password(request: Request, data: ChangePasswordRequest, db: AsyncSession = Depends(get_db)):
    user_id = get_current_user_from_cookie(request)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.hashed_password:
        raise HTTPException(status_code=400, detail="Password change not available for OAuth accounts")
    if not verify_password(data.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")

    user.hashed_password = get_password_hash(data.new_password)
    await db.commit()
    return {"message": "Password updated successfully"}


@app.get("/profile/{user_id}")
async def get_user_profile(user_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    get_current_user_from_cookie(request)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "preferred_language": user.preferred_language,
        "profile_picture": user.profile_picture,
    }


@app.get("/search")
async def search_users(request: Request, q: str = "", db: AsyncSession = Depends(get_db)):
    get_current_user_from_cookie(request)
    if len(q) < 2:
        return []
    result = await db.execute(
        select(User).where(User.username.ilike(f"%{q}%")).limit(10)
    )
    users = result.scalars().all()
    return [{"id": u.id, "username": u.username, "profile_picture": u.profile_picture} for u in users]


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "user-service"}


# ── OAuth endpoints (routed via /api/oauth/*) ─────────────────────────────────

@app.get("/42/login")
async def ft_login():
    url = (
        "https://api.intra.42.fr/oauth/authorize"
        f"?client_id={FT_CLIENT_ID}"
        f"&redirect_uri={FT_REDIRECT_URI}"
        "&response_type=code"
    )
    return RedirectResponse(url=url)


@app.get("/42/callback")
async def ft_callback(code: str, db: AsyncSession = Depends(get_db)):
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://api.intra.42.fr/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": FT_CLIENT_ID,
                "client_secret": FT_CLIENT_SECRET,
                "code": code,
                "redirect_uri": FT_REDIRECT_URI,
            },
        )
        if token_resp.status_code != 200:
            return RedirectResponse(url=f"{FRONTEND_URL}/login?error=oauth_failed", status_code=302)

        access_token = token_resp.json().get("access_token")

        user_resp = await client.get(
            "https://api.intra.42.fr/v2/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_resp.status_code != 200:
            return RedirectResponse(url=f"{FRONTEND_URL}/login?error=oauth_failed", status_code=302)

        d = user_resp.json()

    user = await _find_or_create_oauth_user(
        db,
        provider="42",
        oauth_id=str(d["id"]),
        email=d.get("email", ""),
        username=d.get("login", f"ft_{d['id']}"),
        first_name=d.get("first_name", ""),
        last_name=d.get("last_name", ""),
    )

    redirect = RedirectResponse(url=f"{FRONTEND_URL}/home", status_code=302)
    _auth_cookie(redirect, user.id)
    return redirect


@app.get("/github/login")
async def github_login():
    url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&redirect_uri={GITHUB_REDIRECT_URI}"
        "&scope=user:email"
    )
    return RedirectResponse(url=url)


@app.get("/github/callback")
async def github_callback(code: str, db: AsyncSession = Depends(get_db)):
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": GITHUB_REDIRECT_URI,
            },
            headers={"Accept": "application/json"},
        )
        if token_resp.status_code != 200:
            return RedirectResponse(url=f"{FRONTEND_URL}/login?error=oauth_failed", status_code=302)

        access_token = token_resp.json().get("access_token")
        if not access_token:
            return RedirectResponse(url=f"{FRONTEND_URL}/login?error=oauth_failed", status_code=302)

        user_resp = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        d = user_resp.json()

        # Fetch primary email if not public
        email = d.get("email")
        if not email:
            emails_resp = await client.get(
                "https://api.github.com/user/emails",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            emails = emails_resp.json()
            primary = next((e for e in emails if e.get("primary")), None)
            email = primary["email"] if primary else ""

    display_name = d.get("name") or ""
    parts = display_name.split(" ", 1)
    first_name = parts[0] if parts else d.get("login", "")
    last_name  = parts[1] if len(parts) > 1 else ""

    user = await _find_or_create_oauth_user(
        db,
        provider="github",
        oauth_id=str(d["id"]),
        email=email,
        username=d.get("login", f"gh_{d['id']}"),
        first_name=first_name,
        last_name=last_name,
    )

    redirect = RedirectResponse(url=f"{FRONTEND_URL}/home", status_code=302)
    _auth_cookie(redirect, user.id)
    return redirect
