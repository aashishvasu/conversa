"""Pick document sections that answer a topic."""

import re

HEADING_WEIGHT = 8
TF_SATURATION = 1.2
RELEVANCE_FLOOR = 0.25
STOP = {
    "the", "and", "for", "with", "how", "does", "did", "you", "your", "use", "using",
    "from", "that", "this", "what", "when", "where", "which", "why", "can", "has",
    "have", "are", "was", "get", "set", "its", "into", "than", "then", "them", "they",
    "not", "but", "all", "any", "one",
}


def _terms(topic: str) -> list[str]:
    found = re.findall(r"[a-z0-9_.-]+", topic.lower())
    return list(dict.fromkeys(term for term in found if len(term) > 2 and term not in STOP))


def split_sections(markdown: str) -> list[str]:
    """Split markdown headings, or headingless text into paragraph blocks."""
    sections = [section for section in re.split(r"\n(?=#{1,6} )", markdown) if section.strip()]
    return sections if len(sections) > 1 else _blocks(markdown)


def _blocks(text: str, size: int = 2000) -> list[str]:
    out, current = [], ""
    for paragraph in text.split("\n\n"):
        if current and len(current) + len(paragraph) > size:
            out.append(current)
            current = ""
        current += ("\n\n" if current else "") + paragraph
    if current.strip():
        out.append(current)
    return out


def _score(section: str, wanted: list[str]) -> float:
    heading, _, _ = section.partition("\n")
    heading = heading.lower()
    whole = section.lower()
    points = 0.0
    for term in wanted:
        if term in heading:
            points += HEADING_WEIGHT
        frequency = whole.count(term)
        points += frequency / (frequency + TF_SATURATION)
    return points


def match_topic(markdown: str, topic: str, budget: int) -> str | None:
    """Return the relevant sections that fit `budget`, highest scoring first."""
    wanted = _terms(topic or "")
    if not wanted:
        return None
    ranked = sorted(((section, _score(section, wanted)) for section in split_sections(markdown)), key=lambda item: item[1], reverse=True)
    ranked = [(section, points) for section, points in ranked if points > 0]
    if not ranked:
        return None

    floor = ranked[0][1] * RELEVANCE_FLOOR
    picked, used = [], 0
    for section, points in ranked:
        if points < floor:
            continue
        if picked and used + len(section) > budget:
            continue
        picked.append(section[:budget] if not picked and len(section) > budget else section)
        used += len(picked[-1])
        if used >= budget:
            break
    return "\n\n".join(picked)
