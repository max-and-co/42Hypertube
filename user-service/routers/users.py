import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user_id, get_password_hash, verify_password, get_db, form_error, parse_form
from models import User
from routers.auth import user_payload
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
async def update_me(request: Request, db: AsyncSession = Depends(get_db)):
    """Settings form: expected refusals answer 200 {"ok": false} (see auth.form_error)."""
    user_id = get_current_user_id(request)
    data, error = await parse_form(request, UserUpdate)
    if error:
        return error
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if data.email is not None and data.email.lower() != user.email.lower():
        result = await db.execute(select(User).where(func.lower(User.email) == data.email.lower(), User.id != user_id))
        if result.scalars().first():
            return form_error("Email already in use")
        user.email = data.email.lower()

    if data.username is not None and data.username != user.username:
        result = await db.execute(
            select(User).where(func.lower(User.username) == data.username.lower(), User.id != user_id)
        )
        if result.scalars().first():
            return form_error("Username already taken")
        user.username = data.username

    if data.first_name is not None:
        user.first_name = data.first_name
    if data.last_name is not None:
        user.last_name = data.last_name
    if data.preferred_language is not None:
        user.preferred_language = data.preferred_language

    await db.commit()
    await db.refresh(user)
    return {"ok": True, "user": user_payload(user)}


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
        return form_error("Image must be 2 MB or smaller")
    if not content:
        return form_error("Uploaded file is empty")

    sniffed = sniff_image(content)
    if sniffed is None:
        return form_error("File must be a PNG, JPEG, GIF or WebP image")

    ext, _ = sniffed
    filename = f"{uuid.uuid4()}.{ext}"
    path = os.path.join("uploads", filename)

    with open(path, "wb") as f:
        f.write(content)

    user.profile_picture = f"/api/users/avatars/{filename}"
    await db.commit()
    return {"ok": True, "profile_picture": user.profile_picture}


@router.post("/me/password")
async def change_password(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_current_user_id(request)
    data, error = await parse_form(request, ChangePasswordRequest)
    if error:
        return error
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.hashed_password:
        return form_error("Password change not available for OAuth accounts")
    if not verify_password(data.current_password, user.hashed_password):
        return form_error("Current password is incorrect")

    user.hashed_password = get_password_hash(data.new_password)
    await db.commit()
    return {"ok": True, "message": "Password updated successfully"}


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
async def get_user_profile(user_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Public profile for the profile page (the REST API is GET /users/:id).
    A stale or mistyped profile link is an expected answer: 200 {"ok": false},
    so the browser console stays clean."""
    get_current_user_id(request)
    if not user_id.isdigit() or len(user_id) > 9:
        return form_error("User not found")
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalars().first()
    if not user:
        return form_error("User not found")
    return {
        "ok": True,
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "preferred_language": user.preferred_language,
        "profile_picture": user.profile_picture,
    }


@router.get("/search")
async def search_users(request: Request, q: str = Query("", max_length=30), db: AsyncSession = Depends(get_db)):
    get_current_user_id(request)
    q = q.strip()
    if len(q) < 2:
        return []
    # Escape LIKE wildcards so "%" or "_" match literally.
    pattern = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    result = await db.execute(
        select(User).where(User.username.ilike(f"%{pattern}%", escape="\\")).limit(10)
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
    """PATCH /api/users/:id

    The subject lets any authenticated user update any profile, so username and
    profile picture can be changed on anyone. The credentials that control an
    account (e-mail, password) can only be changed by its owner: otherwise any
    member could take over any other account (403).
    """
    current_id = get_current_user_id(request)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if (data.email is not None or data.password is not None) and current_id != user_id:
        raise HTTPException(status_code=403, detail="Only the account owner can change its e-mail or password")

    if data.username is not None:
        existing = await db.execute(
            select(User).where(func.lower(User.username) == data.username.lower(), User.id != user_id)
        )
        if existing.scalars().first():
            raise HTTPException(status_code=409, detail="Username already taken")
        user.username = data.username
    if data.email is not None:
        existing = await db.execute(select(User).where(func.lower(User.email) == data.email.lower(), User.id != user_id))
        if existing.scalars().first():
            raise HTTPException(status_code=409, detail="Email already in use")
        user.email = data.email.lower()
    if data.password is not None:
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
