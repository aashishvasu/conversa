"""Session auth: the password-for-token exchange and the dependency that guards every other route.

One shared password from the APP_PASSWORD env var, traded for a signed expiring JWT.
"""

import hmac
import os
import secrets
import time

import jwt
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

# Idempotent, and it has to run here too: importing this module before main reads the env otherwise finds nothing.
load_dotenv()

APP_PASSWORD = os.environ.get("APP_PASSWORD")
# Signing key for session tokens.
# If unset, generate a random one per process: secure by default, though restarting logs everyone out.
# Set it to persist sessions.
JWT_SECRET = os.environ.get("JWT_SECRET") or secrets.token_urlsafe(32)
TOKEN_TTL = int(os.environ.get("TOKEN_TTL_SECONDS", str(7 * 24 * 3600)))

router = APIRouter()


def mint_token():
    # iat lets the client compute the half-life for sliding renewal.
    now = int(time.time())
    return jwt.encode({"iat": now, "exp": now + TOKEN_TTL}, JWT_SECRET, algorithm="HS256")


def require_auth(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, {"code": "missing_token", "message": "missing token"})
    try:
        jwt.decode(authorization[7:], JWT_SECRET, algorithms=["HS256"])
    except jwt.InvalidTokenError:  # covers expired and tampered tokens
        raise HTTPException(401, {"code": "invalid_token", "message": "invalid or expired token"})


class LoginBody(BaseModel):
    password: str


@router.post("/api/login")
def login(body: LoginBody):
    # Single shared secret, constant-time compare.
    # Add a per-IP attempt limiter here if brute force becomes a concern.
    if not APP_PASSWORD:
        raise HTTPException(503, {"code": "password_unconfigured", "message": "server password not configured"})
    if not hmac.compare_digest(body.password, APP_PASSWORD):
        raise HTTPException(401, {"code": "bad_password", "message": "bad password"})
    return {"token": mint_token()}


@router.post("/api/refresh")
def refresh(_=Depends(require_auth)):
    # Sliding session: any still-valid token can be traded for a fresh full-TTL one.
    return {"token": mint_token()}

