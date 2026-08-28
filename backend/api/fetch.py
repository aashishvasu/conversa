"""The page-fetch endpoint behind the context editor's URL box."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import require_auth
from research import fetcher

router = APIRouter()


class FetchRequest(BaseModel):
    url: str
    topic: str | None = None  # returns the sections answering it, not the page head


@router.post("/api/fetch")
async def fetch_url(req: FetchRequest, _=Depends(require_auth)):
    # Every FetchError is about the URL the caller supplied, blocked targets included, so it maps to 400 with the reason.
    try:
        return await fetcher.fetch(req.url, req.topic)
    except fetcher.FetchError as e:
        raise HTTPException(400, {"code": "fetch_failed", "message": str(e)})
