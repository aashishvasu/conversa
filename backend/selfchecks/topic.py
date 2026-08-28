"""Selfcheck: python -m selfchecks.topic"""

from research.topic import match_topic, split_sections

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
