import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from auth import (
    create_access_token, verify_password, set_auth_cookie, get_db,
    FRONTEND_URL,
    FT_CLIENT_ID, FT_CLIENT_SECRET, FT_REDIRECT_URI,
    GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, GITHUB_REDIRECT_URI,
)
from models import User

router = APIRouter()


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
    result = await db.execute(
        select(User).where(User.oauth_id == oauth_id, User.oauth_provider == provider)
    )
    user = result.scalars().first()

    if not user and email:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalars().first()

    if not user:
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


# ── RESTful OAuth2 token endpoint ─────────────────────────────────────────────

@router.post("/token")
async def oauth_token(request: Request, db: AsyncSession = Depends(get_db)):
    """
    OAuth2 token endpoint (Resource Owner Password Credentials).
    Accepts application/x-www-form-urlencoded OR application/json.
    Fields: client_id (username or email), client_secret (password).
    Returns a Bearer token.
    """
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        client_id = body.get("client_id", "")
        client_secret = body.get("client_secret", "")
    else:
        form = await request.form()
        client_id = form.get("client_id", "")
        client_secret = form.get("client_secret", "")

    if not client_id or not client_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="client_id and client_secret are required",
        )

    result = await db.execute(
        select(User).where(or_(User.username == client_id, User.email == client_id))
    )
    user = result.scalars().first()

    if not user or not user.hashed_password or not verify_password(client_secret, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid client credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(data={"sub": str(user.id)})
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 60 * 60 * 24 * 7,
    }


# ── 42 SSO ────────────────────────────────────────────────────────────────────

@router.get("/42/login")
async def ft_login():
    url = (
        "https://api.intra.42.fr/oauth/authorize"
        f"?client_id={FT_CLIENT_ID}"
        f"&redirect_uri={FT_REDIRECT_URI}"
        "&response_type=code"
    )
    return RedirectResponse(url=url)


@router.get("/42/callback")
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
    set_auth_cookie(redirect, user.id)
    return redirect


# ── GitHub SSO ────────────────────────────────────────────────────────────────

@router.get("/github/login")
async def github_login():
    url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&redirect_uri={GITHUB_REDIRECT_URI}"
        "&scope=user:email"
    )
    return RedirectResponse(url=url)


@router.get("/github/callback")
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
    set_auth_cookie(redirect, user.id)
    return redirect
