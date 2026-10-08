import re
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from auth import (
    COOKIE_SECURE, create_access_token, verify_password, set_auth_cookie, get_db,
    FRONTEND_URL,
    FT_CLIENT_ID, FT_CLIENT_SECRET, FT_REDIRECT_URI,
    GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, GITHUB_REDIRECT_URI,
)
from models import User
from schemas import USERNAME_RE

router = APIRouter()

STATE_COOKIE = "oauth_state"
STATE_MAX_AGE = 10 * 60


def _login_error() -> RedirectResponse:
    response = RedirectResponse(url=f"{FRONTEND_URL}/login?error=oauth_failed", status_code=302)
    response.delete_cookie(STATE_COOKIE, samesite="lax")
    return response


def _redirect_with_state(base_url: str, params: dict[str, str]) -> RedirectResponse:
    """Send the browser to the provider with a random `state`, remembered in a
    short-lived HttpOnly cookie. The callback refuses any code whose state does
    not match, so another site cannot log a victim into the attacker's account
    (login CSRF)."""
    state = secrets.token_urlsafe(32)
    response = RedirectResponse(url=f"{base_url}?{urlencode({**params, 'state': state})}")
    response.set_cookie(
        STATE_COOKIE, state, max_age=STATE_MAX_AGE, httponly=True, samesite="lax", secure=COOKIE_SECURE
    )
    return response


def _state_is_valid(request: Request, state: str | None) -> bool:
    expected = request.cookies.get(STATE_COOKIE)
    return bool(state and expected and secrets.compare_digest(state, expected))


def _safe_username(raw: str, fallback: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_.-]", "", raw or "")[:30]
    return candidate if USERNAME_RE.fullmatch(candidate) else fallback


def _safe_name(raw: str | None) -> str:
    return " ".join((raw or "").split())[:50]


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
    """`email` must already be verified by the provider: an existing password
    account with the same address is linked to this provider login."""
    result = await db.execute(
        select(User).where(User.oauth_id == oauth_id, User.oauth_provider == provider)
    )
    user = result.scalars().first()

    if not user:
        result = await db.execute(select(User).where(func.lower(User.email) == email.lower()))
        user = result.scalars().first()

    if not user:
        result = await db.execute(select(User).where(func.lower(User.username) == username.lower()))
        if result.scalars().first():
            username = f"{username[:23]}_{oauth_id[:6]}"
        user = User(
            email=email.lower(),
            username=username,
            first_name=first_name or "Member",
            last_name=last_name or "Member",
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


def _signed_in(user: User) -> RedirectResponse:
    redirect = RedirectResponse(url=f"{FRONTEND_URL}/home", status_code=302)
    redirect.delete_cookie(STATE_COOKIE, samesite="lax")
    set_auth_cookie(redirect, user.id)
    return redirect


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
    try:
        if "application/json" in content_type:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError
        else:
            body = await request.form()
        client_id = str(body.get("client_id") or "")[:254]
        client_secret = str(body.get("client_secret") or "")[:128]
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed request body")

    if not client_id or not client_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="client_id and client_secret are required",
        )

    result = await db.execute(
        select(User).where(or_(func.lower(User.username) == client_id.lower(), func.lower(User.email) == client_id.lower()))
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
    return _redirect_with_state(
        "https://api.intra.42.fr/oauth/authorize",
        {"client_id": FT_CLIENT_ID, "redirect_uri": FT_REDIRECT_URI, "response_type": "code"},
    )


@router.get("/42/callback")
async def ft_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    # A user who clicks "cancel" comes back with ?error=access_denied and no code.
    if not code or not _state_is_valid(request, state):
        return _login_error()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
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
            access_token = token_resp.json().get("access_token") if token_resp.status_code == 200 else None
            if not access_token:
                return _login_error()

            user_resp = await client.get(
                "https://api.intra.42.fr/v2/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if user_resp.status_code != 200:
                return _login_error()
            d = user_resp.json()
    except (httpx.HTTPError, ValueError):
        return _login_error()

    email = str(d.get("email") or "")
    if not d.get("id") or not email:
        return _login_error()

    user = await _find_or_create_oauth_user(
        db,
        provider="42",
        oauth_id=str(d["id"]),
        email=email,  # 42 intra addresses are institution-verified
        username=_safe_username(str(d.get("login") or ""), f"ft_{d['id']}"),
        first_name=_safe_name(d.get("first_name")),
        last_name=_safe_name(d.get("last_name")),
    )
    return _signed_in(user)


# ── GitHub SSO ────────────────────────────────────────────────────────────────

@router.get("/github/login")
async def github_login():
    return _redirect_with_state(
        "https://github.com/login/oauth/authorize",
        {"client_id": GITHUB_CLIENT_ID, "redirect_uri": GITHUB_REDIRECT_URI, "scope": "user:email"},
    )


@router.get("/github/callback")
async def github_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    if not code or not _state_is_valid(request, state):
        return _login_error()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
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
            access_token = token_resp.json().get("access_token") if token_resp.status_code == 200 else None
            if not access_token:
                return _login_error()

            api_headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"}
            user_resp = await client.get("https://api.github.com/user", headers=api_headers)
            emails_resp = await client.get("https://api.github.com/user/emails", headers=api_headers)
            if user_resp.status_code != 200 or emails_resp.status_code != 200:
                return _login_error()
            d = user_resp.json()
            emails = emails_resp.json()
    except (httpx.HTTPError, ValueError):
        return _login_error()

    # Only an address GitHub has verified may be used: otherwise anyone could
    # add a victim's address to their GitHub account and take over the
    # matching Hypertube account.
    verified = [e for e in emails if isinstance(e, dict) and e.get("verified") and e.get("email")]
    primary = next((e for e in verified if e.get("primary")), verified[0] if verified else None)
    if not d.get("id") or primary is None:
        return _login_error()

    display_name = _safe_name(d.get("name"))
    parts = display_name.split(" ", 1) if display_name else []
    first_name = parts[0] if parts else ""
    last_name = parts[1] if len(parts) > 1 else ""

    user = await _find_or_create_oauth_user(
        db,
        provider="github",
        oauth_id=str(d["id"]),
        email=str(primary["email"]),
        username=_safe_username(str(d.get("login") or ""), f"gh_{d['id']}"),
        first_name=first_name,
        last_name=last_name,
    )
    return _signed_in(user)
