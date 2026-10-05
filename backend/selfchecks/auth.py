"""Selfcheck: python -m selfchecks.auth"""

import time

import jwt
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded

import api.auth as auth
from api.auth import LOGIN_RATE_LIMIT, limiter, mint_token, rate_limit_handler, require_auth

# A minted token verifies, and require_auth accepts it as a bearer header.
require_auth(f"Bearer {mint_token()}")
for bad in (None, "no-scheme", "Bearer garbage"):
    try:
        require_auth(bad)
        raise AssertionError(f"accepted {bad!r}")
    except HTTPException as e:
        assert e.status_code == 401, e

# A validly signed token with no exp would never expire, so it is refused.
timeless = jwt.encode({"iat": int(time.time())}, auth.JWT_SECRET, algorithm="HS256")
try:
    require_auth(f"Bearer {timeless}")
    raise AssertionError("accepted a token with no exp")
except HTTPException as e:
    assert e.status_code == 401, e

# The login route compares non-ASCII without raising, and throttles past LOGIN_RATE_LIMIT.
app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
app.include_router(auth.router)
client = TestClient(app)
real_password = auth.APP_PASSWORD
auth.APP_PASSWORD = "correct horse"
try:
    assert client.post("/api/login", json={"password": "pässwörd"}).status_code == 401
    assert client.post("/api/login", json={"password": "correct horse"}).status_code == 200
    limiter.reset()
    allowed = int(LOGIN_RATE_LIMIT.split("/")[0])
    responses = [client.post("/api/login", json={"password": "correct horse"}) for _ in range(allowed + 1)]
    assert [r.status_code for r in responses[:allowed]] == [200] * allowed
    assert responses[-1].status_code == 429
    assert responses[-1].json()["detail"]["code"] == "too_many_attempts"
finally:
    auth.APP_PASSWORD = real_password

print("auth selfcheck OK")
