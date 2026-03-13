import os
import jwt
import bcrypt
from datetime import datetime, timedelta, timezone
from fastapi import Request, Response, HTTPException, status
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# ── Config ────────────────────────────────────────────────────────────────────

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8080")

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

# ── Database ──────────────────────────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_async_engine(DATABASE_URL)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db():
    async with async_session() as session:
        yield session

# ── JWT & passwords ───────────────────────────────────────────────────────────

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 1 week


def get_secret() -> str:
    secret = os.getenv("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY environment variable is not set")
    return secret


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, get_secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> int:
    try:
        payload = jwt.decode(token, get_secret(), algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
        return int(user_id)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.PyJWTError as e:
        print(f"JWT decode error: {e}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")


def get_current_user_id(request: Request) -> int:
    """Accept both Authorization: Bearer <token> header and httponly cookie."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return decode_token(auth_header[7:])
    token = request.cookies.get("access_token")
    if token:
        return decode_token(token)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


def get_current_user_from_cookie(request: Request) -> int:
    return get_current_user_id(request)


def set_auth_cookie(response: Response, user_id: int) -> None:
    token = create_access_token(data={"sub": str(user_id)})
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=60 * 60 * 24 * 7,
        samesite="lax",
        secure=False,
    )
