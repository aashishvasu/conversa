"""Selfcheck: python -m selfchecks.runs"""

import asyncio
import time
from contextlib import suppress

from research import runs as r
from research.runs import FINISHED_TTL, PROMPTS, RUNS, Run, answered, evict, forget, report_summary, result_payload

# The payload's sections are the answered subquestions in report order, notes reduced to {note, url}.
plan_sections = [
    {"question": "one", "notes": [{"url": "https://a.example/1", "note": "NOTE_A", "title": "extra"}]},
    {"question": "two", "notes": []},
    {"question": "three", "notes": [{"url": "https://a.example/3", "note": "NOTE_C"}]},
]
found = answered(plan_sections)
assert [s["question"] for s in found] == ["one", "three"], found
report = "## Summary\n\nFIRST\n\nSECOND\n\nTHIRD\n\n## q1. one\n\nREPORT_BODY"
payload = result_payload("brief text", found, report)
assert payload["summary"] == "FIRST\n\nSECOND", "the assistant handoff keeps at most two model-written paragraphs"
assert report_summary("## q1. no summary") == "", "a malformed report never becomes a long chat message"
assert payload["report"] == {"name": "Research report.md", "text": report}
assert [s["question"] for s in payload["sections"]] == ["one", "three"], "sections follow the answered order"
assert payload["sections"][0]["notes"] == [{"note": "NOTE_A", "url": "https://a.example/1"}], "notes carry note and url only"

# Prompt overrides are copied to one run; a later request keeps the module defaults.
custom = Run("goal", {"search": "m", "note": "m", "report": "m"}, 2, prompts={"plan": "CUSTOM_PLAN"})
plain = Run("goal", {"search": "m", "note": "m", "report": "m"}, 2)
assert custom.prompts["plan"] == "CUSTOM_PLAN"
assert plain.prompts["plan"] == PROMPTS["plan"]
assert PROMPTS["plan"] != "CUSTOM_PLAN", "per-run overrides never mutate global prompts"


# Report failure preserves the gathered notes.
# The run loop reads gather and complete off its module, so the stubs are set there.
async def _resilience_checks():
    real_gather, real_complete = r.gather, r.complete

    async def canned_gather(question, *a, **k):
        return {"question": question, "notes": [{"url": "https://a.example/1", "note": "NOTE_BODY"}], "failed": []}

    async def complete_but_no_report(model_id, system, prompt, **k):
        if system is r.PROMPTS["plan"]:
            return "first subquestion here"
        if system is r.PROMPTS["report"]:
            raise RuntimeError("Error code: 529 - overloaded_error")
        return "DONE"

    r.gather, r.complete = canned_gather, complete_but_no_report
    try:
        run = Run("brief", {"search": "m", "note": "m", "report": "m"}, 2)
        await r._run(run)
    finally:
        r.gather, r.complete = real_gather, real_complete
    assert run.status == "done", (run.status, run.error)
    assert "report stage failed" in run.error, run.error
    assert "NOTE_BODY" in run.payload["report"]["text"], "a failed report still hands over the notes"
    assert run.payload["sections"][0]["notes"], "and the note sections survive too"

asyncio.run(_resilience_checks())


async def _idempotent_start_check():
    real_run = r._run

    async def parked(_run):
        await asyncio.Event().wait()

    RUNS.clear()
    r._run = parked
    try:
        first, created = r.start("goal", {"search": "m", "note": "m", "report": "m"}, run_id="browser-run")
        duplicate, resumed = r.start("other goal", {"search": "m", "note": "m", "report": "m"}, run_id="browser-run")
        assert created is False and resumed is True
        assert duplicate is first and len(RUNS) == 1, "a duplicate browser start does not launch a second task"
        assert first.id == "browser-run" and first.status == "running"
        # A lost start response may be retried after completion; retention still returns that terminal run.
        first.status = "done"
        terminal, terminal_resumed = r.start("other goal", {"search": "m", "note": "m", "report": "m"}, run_id="browser-run")
        assert terminal_resumed is True and terminal is first and len(RUNS) == 1
        # Explicit collection (or a process restart, which has no RUNS entry) permits a replacement.
        forget(first.id)
        replacement, replaced = r.start("goal", {"search": "m", "note": "m", "report": "m"}, run_id="browser-run")
        assert replaced is False and replacement is not first and replacement.id == "browser-run"
        first.task.cancel()
        replacement.task.cancel()
        with suppress(asyncio.CancelledError):
            await first.task
        with suppress(asyncio.CancelledError):
            await replacement.task
    finally:
        r._run = real_run
        RUNS.clear()


asyncio.run(_idempotent_start_check())

# A collected run is forgotten, and an uncollected one is swept once it is past its window.
# Retention is bounded by the next bit of research activity, and by the process ending.
RUNS.clear()
kept = Run("b", {}, 1)
RUNS[kept.id] = kept
taken = Run("b", {}, 1)
RUNS[taken.id] = taken
forget(taken.id)
assert taken.id not in RUNS and kept.id in RUNS, "collecting drops one run and leaves the others"

stale = Run("b", {}, 1)
stale.finished_at = time.time() - FINISHED_TTL - 1
RUNS[stale.id] = stale
running = Run("b", {}, 1)
RUNS[running.id] = running
evict()
assert stale.id not in RUNS, "a finished run past its window is swept"
assert running.id in RUNS, "a run that never finished is left alone"
RUNS.clear()

print("runs selfcheck OK")
