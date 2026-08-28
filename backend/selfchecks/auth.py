"""Selfcheck: python -m selfchecks.auth"""

from fastapi import HTTPException

from api.auth import mint_token, require_auth

# A minted token verifies, and require_auth accepts it as a bearer header.
require_auth(f"Bearer {mint_token()}")
for bad in (None, "no-scheme", "Bearer garbage"):
    try:
        require_auth(bad)
        raise AssertionError(f"accepted {bad!r}")
    except HTTPException as e:
        assert e.status_code == 401, e

print("auth selfcheck OK")
