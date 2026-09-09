"""Passphrase generation for transient transfers.

A phrase is five lowercase hyphen-separated words: verb-verb-adjective-adjective-animal.
The word pools live in wordlists.json so the vocabulary stays data, not a code dump.
"""

import json
import math
import re
from pathlib import Path
from secrets import choice

_WORDS = json.loads((Path(__file__).with_name("wordlists.json")).read_text(encoding="utf-8"))
VERBS = _WORDS["verbs"]
ADJECTIVES = _WORDS["adjectives"]
ANIMALS = _WORDS["animals"]

_WORD = re.compile(r"[a-z]+")


def generate():
    return f"{choice(VERBS)}-{choice(VERBS)}-{choice(ADJECTIVES)}-{choice(ADJECTIVES)}-{choice(ANIMALS)}"


def normalize(text):
    """Return the canonical phrase, or None when the input is not five lowercase words."""
    words = _WORD.findall(str(text or "").lower())
    if len(words) != 5:
        return None
    return "-".join(words)


def entropy_bits():
    return math.log2(len(VERBS) ** 2 * len(ADJECTIVES) ** 2 * len(ANIMALS))
