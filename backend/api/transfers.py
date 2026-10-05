"""Transient cross-device transfer endpoints.

Create stores an export payload under a fresh phrase; retrieve returns it for the
same phrase. Both require the bearer token. Phrases travel in request bodies, never
URLs or logs, and a malformed, unknown, or expired phrase yields the same 404.
"""

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError

from api.auth import require_auth
from transfers.store import STORE, TRANSFER_MAX_ENTRY_BYTES, CapacityFull, EntryTooLarge

router = APIRouter()

_ENVELOPE_OVERHEAD = 64
_ENVELOPE_LIMIT = TRANSFER_MAX_ENTRY_BYTES + _ENVELOPE_OVERHEAD

_TRANSFER_TOO_LARGE = {
    "code": "transfer_too_large",
    "message": "transfer payload exceeds the per-entry size limit",
}
_BAD_TRANSFER = {
    "code": "bad_transfer",
    "message": "expected {scope, data}",
}
_NO_SUCH_TRANSFER = {
    "code": "no_such_transfer",
    "message": "no such transfer, or it has expired",
}


class CreateBody(BaseModel):
    scope: Literal["conversation", "snapshot"]
    data: Any


async def _read_limited_body(request: Request, max_bytes: int) -> bytes:
    """Read the request body up to max_bytes, rejecting oversized bodies early."""
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(413, _TRANSFER_TOO_LARGE)
        except ValueError:
            pass

    chunks = []
    read = 0
    async for chunk in request.stream():
        read += len(chunk)
        if read > max_bytes:
            raise HTTPException(413, _TRANSFER_TOO_LARGE)
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/api/transfers")
async def create_transfer(request: Request, _=Depends(require_auth)):
    raw = await _read_limited_body(request, _ENVELOPE_LIMIT)
    try:
        body = CreateBody.model_validate_json(raw)
    except ValidationError:
        raise HTTPException(400, _BAD_TRANSFER)
    if not isinstance(body.data, dict):
        raise HTTPException(400, _BAD_TRANSFER)
    try:
        return await STORE.create(body.scope, body.data)
    except EntryTooLarge:
        raise HTTPException(413, _TRANSFER_TOO_LARGE)
    except CapacityFull:
        raise HTTPException(507, {"code": "transfers_full", "message": "the transfer store is full, try again later"})


@router.post("/api/transfers/retrieve")
async def retrieve_transfer(request: Request, _=Depends(require_auth)):
    raw = await _read_limited_body(request, _ENVELOPE_LIMIT)
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(404, _NO_SUCH_TRANSFER)
    if not isinstance(parsed, dict):
        raise HTTPException(404, _NO_SUCH_TRANSFER)
    phrase = parsed.get("phrase")
    if not isinstance(phrase, str):
        raise HTTPException(404, _NO_SUCH_TRANSFER)
    entry = await STORE.retrieve(phrase)
    if entry is None:
        raise HTTPException(404, _NO_SUCH_TRANSFER)
    return entry
