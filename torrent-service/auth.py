import os
import jwt
from fastapi import Request, HTTPException, status

ALGORITHM = "HS256"

def get_secret() -> str:
    secret = os.getenv("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY environment variable is not set")
    return secret


def decode_token(token: str) -> int:
    try:
        payload = jwt.decode(token, get_secret(), algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )
        return int(user_id)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except jwt.PyJWTError as e:
        print(f"JWT Decode error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )


def get_current_user_id(request: Request) -> int:
    """Accept both Authorization: Bearer <token> header and HttpOnly cookie."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return decode_token(auth_header[7:])

    token = request.cookies.get("access_token")
    if token:
        return decode_token(token)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
    )


def get_current_user_from_cookie(request: Request) -> int:
    return get_current_user_id(request)
