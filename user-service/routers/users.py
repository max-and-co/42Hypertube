import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user_id, get_password_hash, verify_password, get_db
from models import User
from schemas import UserUpdate, UserUpdateById, ChangePasswordRequest

router = APIRouter()

os.makedirs("uploads", exist_ok=True)

# An avatar is only ever stored with an extension we derive ourselves from the
# file's magic bytes. The browser-supplied filename and Content-Type are both
# attacker-controlled: without this, uploading HTML named "x.html" as
# "image/png" would be served back as text/html from our own origin.
MAX_AVATAR_BYTES = 2 * 1024 * 1024

_IMAGE_SIGNATURES: list[tuple[bytes, str, str]] = [
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"GIF87a", "gif", "image/gif"),
    (b"GIF89a", "gif", "image/gif"),
]

AVATAR_MEDIA_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}


def sniff_image(content: bytes) -> tuple[str, str] | None:
    """Return (extension, media_type) from magic bytes, or None if not an image."""
    for signature, extension, media_type in _IMAGE_SIGNATURES:
        if content.startswith(signature):
            return extension, media_type
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


@router.get("/")
async def list_users(request: Request, db: AsyncSession = Depends(get_db)):
    """GET /api/users — list all users (authenticated)."""
    get_current_user_id(request)
    result = await db.execute(select(User.id, User.username))
    rows = result.all()
    return [{"id": r.id, "username": r.username} for r in rows]


@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "user-service"}


@router.get("/me")
async def read_users_me(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_current_user_id(request)
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


@router.patch("/me")
async def update_me(request: Request, data: UserUpdate, db: AsyncSession = Depends(get_db)):
    user_id = get_current_user_id(request)
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


@router.post("/me/avatar")
async def upload_avatar(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    user_id = get_current_user_id(request)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    content = await file.read(MAX_AVATAR_BYTES + 1)
    if len(content) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=413, detail="Image must be 2 MB or smaller")
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    sniffed = sniff_image(content)
    if sniffed is None:
        raise HTTPException(status_code=400, detail="File must be a PNG, JPEG, GIF or WebP image")

    ext, _ = sniffed
    filename = f"{uuid.uuid4()}.{ext}"
    path = os.path.join("uploads", filename)

    with open(path, "wb") as f:
        f.write(content)

    user.profile_picture = f"/api/users/avatars/{filename}"
    await db.commit()
    return {"profile_picture": user.profile_picture}


@router.post("/me/password")
async def change_password(request: Request, data: ChangePasswordRequest, db: AsyncSession = Depends(get_db)):
    user_id = get_current_user_id(request)
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


@router.get("/avatars/{filename}")
async def get_avatar(filename: str):
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    media_type = AVATAR_MEDIA_TYPES.get(ext)
    if media_type is None:
        raise HTTPException(status_code=404, detail="Not found")

    path = os.path.join("uploads", filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Not found")

    # Never let the extension decide the type, and refuse to be framed/sniffed.
    return FileResponse(
        path,
        media_type=media_type,
        headers={"X-Content-Type-Options": "nosniff", "Content-Disposition": "inline"},
    )


@router.get("/profile/{user_id}")
async def get_user_profile(user_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    get_current_user_id(request)
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


@router.get("/search")
async def search_users(request: Request, q: str = "", db: AsyncSession = Depends(get_db)):
    get_current_user_id(request)
    if len(q) < 2:
        return []
    result = await db.execute(
        select(User).where(User.username.ilike(f"%{q}%")).limit(10)
    )
    users = result.scalars().all()
    return [{"id": u.id, "username": u.username, "profile_picture": u.profile_picture} for u in users]


# Registered last to avoid shadowing string paths above
@router.get("/{user_id:int}")
async def get_user_by_id(user_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """GET /api/users/:id — returns username, email, profile_picture (authenticated)."""
    get_current_user_id(request)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "profile_picture": user.profile_picture,
    }


@router.patch("/{user_id:int}")
async def update_user_by_id(
    user_id: int,
    request: Request,
    data: UserUpdateById,
    db: AsyncSession = Depends(get_db),
):
    """PATCH /api/users/:id — any authenticated user may update any profile."""
    get_current_user_id(request)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if data.username is not None:
        existing = await db.execute(select(User).where(User.username == data.username, User.id != user_id))
        if existing.scalars().first():
            raise HTTPException(status_code=400, detail="Username already taken")
        user.username = data.username
    if data.email is not None:
        existing = await db.execute(select(User).where(User.email == data.email, User.id != user_id))
        if existing.scalars().first():
            raise HTTPException(status_code=400, detail="Email already in use")
        user.email = data.email
    if data.password is not None:
        if len(data.password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
        user.hashed_password = get_password_hash(data.password)
    if data.profile_picture is not None:
        user.profile_picture = data.profile_picture

    await db.commit()
    await db.refresh(user)
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "profile_picture": user.profile_picture,
    }
