"""Selfcheck: python -m selfchecks.errors"""

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from api.errors import register_error_handlers

app = FastAPI()
register_error_handlers(app)


class Body(BaseModel):
    count: int


@app.get("/dict")
async def dict_error():
    raise HTTPException(404, {"code": "no_such", "message": "gone", "retryable": False})


@app.get("/str")
async def str_error():
    raise HTTPException(401, "unauthorized", headers={"WWW-Authenticate": "Bearer"})


@app.post("/validate")
async def validate(body: Body):
    return {"count": body.count}


@app.get("/boom")
async def boom():
    raise RuntimeError("SENTINEL-RAW upstream detail")


client = TestClient(app, raise_server_exceptions=False)

d = client.get("/dict")
assert d.status_code == 404 and d.json()["detail"] == {"code": "no_such", "message": "gone", "retryable": False}, d.text

s = client.get("/str")
assert s.status_code == 401 and s.json()["detail"]["message"] == "unauthorized"
assert s.headers.get("www-authenticate") == "Bearer", "auth headers must survive normalization"

v = client.post("/validate", json={"count": "SENTINEL-INPUT not-an-int"})
assert v.status_code == 422 and v.json()["detail"]["code"] == "invalid_request"
assert "SENTINEL-INPUT" not in v.text, "validation errors must not echo submitted input"

b = client.get("/boom")
assert b.status_code == 500 and b.json()["detail"]["code"]
assert "SENTINEL-RAW" not in b.text, "unhandled errors must not leak raw exception text"
assert isinstance(b.json()["detail"]["retryable"], bool)

print("errors selfcheck OK")
