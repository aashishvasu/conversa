"""Parsing and validation for model-produced research objects."""

import json
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError


class Claim(BaseModel):
    text: str
    stance: Literal["supports", "contradicts", "neutral"] = "neutral"
    confidence: Literal["low", "medium", "high"] = "low"
    as_of: str = ""


class Note(BaseModel):
    relevant: bool = True
    gist: str = ""
    claims: list[Claim] = []
    fetch_offset: int | None = Field(default=None, ge=0)


def object_from_text(text):
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S | re.I)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except ValueError:
        start = text.find("{")
        if start < 0:
            raise
        value, _ = json.JSONDecoder().raw_decode(text[start:])
        return value


def note_from_text(text):
    """Validate a raw note reply, returning a Note or None when it is unusable."""
    try:
        payload = object_from_text(text)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return Note.model_validate(payload)
    except ValidationError:
        return None
