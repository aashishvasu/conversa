"""Pick the sections of a document that answer a question.

The head of a reference page is navigation and preamble, so "first N characters" is the least useful slice of it.

Ported from magpi (MIT, grainologic/magpi, src/topic.ts); the weights below are its tuned values.
"""

import re

# A term in a heading counts far more than the same term in a body.
# Long sections mention everything, so without this weight a big overview outranks the section that answers.
HEADING_WEIGHT = 8
# Body mentions saturate: the second mention says much less than the first, and the hundredth says nothing.
# Without this a long overview wins by repetition alone.
TF_SATURATION = 1.2
# Runners-up below this share of the top score are padding.
RELEVANCE_FLOOR = 0.25

# Words carrying no topic signal.
# Terms under 3 chars are dropped by length anyway.
STOP = {
    "the", "and", "for", "with", "how", "does", "did", "you", "your", "use", "using",
    "from", "that", "this", "what", "when", "where", "which", "why", "can", "has",
    "have", "are", "was", "get", "set", "its", "into", "than", "then", "them", "they",
    "not", "but", "all", "any", "one",
}


def _terms(topic):
    found = re.findall(r"[a-z0-9_.-]+", topic.lower())
    return list(dict.fromkeys(t for t in found if len(t) > 2 and t not in STOP))


def split_sections(markdown):
    """Split on markdown headings. Text before the first heading counts as a section.

    PDFs and plain text carry no headings, so those fall back to paragraph blocks.
    Scoring then reduces to term frequency, which still beats returning the first N characters.
    """
    sections = [s for s in re.split(r"\n(?=#{1,6} )", markdown) if s.strip()]
    return sections if len(sections) > 1 else _blocks(markdown)


def _blocks(text, size=2000):
    out, current = [], ""
    for paragraph in text.split("\n\n"):
        if current and len(current) + len(paragraph) > size:
            out.append(current)
            current = ""
        current += ("\n\n" if current else "") + paragraph
    if current.strip():
        out.append(current)
    return out


def _score(section, wanted):
    heading, _, _ = section.partition("\n")
    heading = heading.lower()
    whole = section.lower()
    points = 0.0
    for t in wanted:
        if t in heading:
            points += HEADING_WEIGHT
        tf = whole.count(t)
        points += tf / (tf + TF_SATURATION)
    return points


def match_topic(markdown, topic, budget):
    """Best-scoring sections that fit `budget` characters, highest first.

    None when the topic is empty or matches nothing, which is the caller's signal to fall back to the head of the document.
    """
    wanted = _terms(topic or "")
    if not wanted:
        return None
    ranked = sorted(
        ((s, _score(s, wanted)) for s in split_sections(markdown)),
        key=lambda x: x[1],
        reverse=True,
    )
    ranked = [(s, p) for s, p in ranked if p > 0]
    if not ranked:
        return None

    # Budget alone would pad the answer with whatever happens to fit, and a weak match displaces a strong one.
    floor = ranked[0][1] * RELEVANCE_FLOOR
    picked, used = [], 0
    for section, points in ranked:
        if points < floor:
            continue
        if picked and used + len(section) > budget:
            continue
        # The top section always goes in, truncated if it alone overruns the budget.
        picked.append(section[:budget] if not picked and len(section) > budget else section)
        used += len(picked[-1])
        if used >= budget:
            break
    return "\n\n".join(picked)


if __name__ == "__main__":  # self-check: python topic.py
    doc = """# Library overview

This library watches things and reads things and writes things. Overview overview.
It is a long preamble that mentions watch and directory and change repeatedly:
watch watch watch directory directory change change change.

## Installation

Run the installer.

## Watching a directory for changes

Call `watch_dir()` with a path. It fires on every change.
"""

    m = match_topic(doc, "watch a directory for changes", 2000)
    assert m.startswith("## Watching a directory"), m
    # HEADING_WEIGHT is what makes this hold: the preamble repeats every term more times, and loses on heading terms.
    assert "Library overview" not in m.split("\n")[0], m

    # An unmatched topic returns None so the caller falls back to the head of the document.
    assert match_topic(doc, "quantum chromodynamics", 2000) is None
    assert match_topic(doc, "", 2000) is None
    # Stopwords alone carry no signal.
    assert match_topic(doc, "how does the what", 2000) is None

    # The top section is returned even when it alone overruns the budget.
    assert len(match_topic(doc, "watching directory", 30)) == 30

    # Text ahead of the first heading counts as a section.
    assert len(split_sections("intro text\n\n# One\n\n# Two")) == 3

    # Headingless text (a PDF, a source file) still splits, so topic selection applies there too.
    flat = "\n\n".join(f"paragraph {i} " + "filler " * 60 for i in range(10))
    assert len(split_sections(flat)) > 1, "headingless text must still split"
    target = flat + "\n\nThe checkpoint starves when a reader never closes."
    assert "checkpoint starves" in match_topic(target, "checkpoint starvation", 1500)

    print("topic selfcheck OK")
