"""Selfcheck: python -m selfchecks.runs"""

import asyncio
import json
from contextlib import suppress

from research import gather as g
from research import report
from research import runs as r
from research.runs import RUNS, Run
from research.state import empty_state, validate_checkpoint


def brief():
    return {"objective": "Investigate Project Orion", "deliverable": "A sourced brief", "scope": ["current public sources"], "constraints": ["cite evidence"], "questions": [], "answers": {"region": "US"}}


async def workflow_checks():
    real = g.search, g._page, g.note, r.complete, report.complete
    calls = []

    async def search(query, model, limit=8, search_prompt=None, spend=None):
        calls.append(("search", query))
        if "follow" in query:
            return [{"title": "same", "url": "https://EXAMPLE.test/page?utm_source=x"}]
        return [{"title": "source", "url": "https://example.test/page"}]

    async def page(url, question):
        calls.append(("fetch", url))
        return {"url": "https://example.test/page#fragment", "title": "Source", "content": "supported fact"}

    async def note(question, page, model, spend=None, note_prompt=None):
        return "The source supports the fact."

    coord = [
        '{"action":"continue","resolve":["T1"],"prune":[],"add":[{"question":"follow-up question","reason":"cover a gap"}],"merge":[],"gaps":["check follow-up"]}',
        '{"action":"finish","resolve":["T2"],"prune":[],"add":[],"merge":[],"gaps":[]}',
    ]

    async def complete(model, system, prompt, **kwargs):
        if system == r.COORDINATOR:
            return coord.pop(0)
        if system == report.REPORT:
            return "## Summary\n\nSupported fact [E1]"
        if system == report.VERIFY:
            return '{"valid":true,"corrections":"","gaps":[]}'
        return ""

    g.search, g._page, g.note, r.complete, report.complete = search, page, note, complete, complete
    try:
        run = Run(brief(), {"search": "m", "note": "m", "report": "m"}, depth=2)
        await r._run(run)
    finally:
        g.search, g._page, g.note, r.complete, report.complete = real
    assert run.status == "done", (run.status, run.error)
    checkpoint_events = [event for event in run.events if event["kind"] == "checkpoint"]
    assert checkpoint_events and all(isinstance(event["checkpoint"], dict) for event in checkpoint_events)
    resume_data = checkpoint_events[0]["checkpoint"]
    resume_data["frontier"][0]["status"] = "running"
    resume_data["frontier"][0]["operation_id"] = "uncompleted"
    prior_calls = resume_data["budgets"]["calls"]
    resumed = Run(brief(), {"search": "new", "note": "new", "report": "new"}, checkpoint_data=resume_data)
    assert resumed.frontier[0]["status"] == "pending"
    assert resumed.update_calls() == prior_calls, "checkpoint resume must retain spent call budget without double counting"
    retry_data = validate_checkpoint(resume_data)
    retry_data["evidence"] = []
    retry_data["frontier"][0].update(status="pruned", attempts=1, operation_id="failed-op")
    retry_data["operations"]["completed"]["failed-op"] = True
    retry_data["operations"]["queries"]["investigate project orion"] = 2
    retried = Run(brief(), {"search": "new", "note": "new", "report": "new"}, checkpoint_data=retry_data, restart_failed=True)
    assert retried.frontier[0]["status"] == "pending" and "failed-op" not in retried.data["operations"]["completed"]
    assert "investigate project orion" not in retried.data["operations"]["queries"]
    assert any(task["question"] == "follow-up question" for task in run.frontier)
    assert len(run.evidence) == 1 and len(calls) == 3, calls
    run.evidence[0]["excerpt"] = "x" * 1000
    assert len(json.loads(r._worker_context(run))["known_findings"][0]["excerpt"]) == 600
    assert run.data["budgets"]["calls"] == run.prior_calls + run.spend.calls + run.data["budgets"].get("fallback_calls", 0)
    assert any(event["kind"] == "source_reused" for event in run.events), "run-wide URL reuse is visible"


async def breaker_and_resume_checks():
    real = g.search, r.complete, report.complete
    async def repeated(query, *args, **kwargs):
        return []
    decisions = 0
    async def complete(model, system, prompt, **kwargs):
        nonlocal decisions
        if system == r.COORDINATOR:
            decisions += 1
            if decisions == 1:
                return '{"action":"continue","resolve":[],"prune":[],"add":[{"question":"Investigate Project Orion","reason":"retry"}],"merge":[],"gaps":["missing"]}'
            return '{"action":"continue","resolve":[],"prune":[],"add":[],"merge":[],"gaps":["missing"]}'
        if system == report.REPORT:
            return "## Summary\n\nNo claim [E1]"
        if system == report.VERIFY:
            return '{"valid":true,"corrections":"","gaps":[]}'
        return ""
    g.search, r.complete, report.complete = repeated, complete, complete
    try:
        run = Run(brief(), {"search": "m", "note": "m", "report": "m"}, depth=1)
        await r._run(run)
    finally:
        g.search, r.complete, report.complete = real
    assert run.status == "error" and "no evidence" in run.error
    assert any(event["kind"] == "breaker" for event in run.events)
    assert run.data["breakers"], "breaker history must survive in checkpoints"

    old_calls = r.MAX_CALLS
    r.MAX_CALLS = 0
    r.complete, report.complete = complete, complete
    try:
        partial = Run(brief(), {"search": "m", "note": "m", "report": "m"}, depth=1)
        partial.sources["https://example.test/page"] = {"id": "S1", "url": "https://example.test/page", "title": "Source", "task_ids": ["T1"]}
        partial.evidence.append({"id": "E1", "source_id": "S1", "task_id": "T1", "question": "Investigate Project Orion", "excerpt": "fact", "note": "fact", "title": "Source"})
        await r._run(partial)
    finally:
        r.MAX_CALLS = old_calls
        r.complete, report.complete = real[1], real[2]
    assert partial.status == "partial" and partial.payload["gaps"], partial.state()

    checkpoint = empty_state(brief(), {"id": "T1", "question": "Investigate Project Orion"})
    checkpoint["sources"]["https://example.test/page"] = {"id": "S1", "url": "https://example.test/page", "title": "Source", "task_ids": ["T1"]}
    checkpoint["evidence"].append({"id": "E1", "source_id": "S1", "task_id": "T1", "task_ids": ["T1"], "excerpt": "fact", "note": "fact", "title": "Source"})
    checkpoint["frontier"][0]["status"] = "done"
    assert validate_checkpoint(checkpoint)["revision"] == 0


asyncio.run(workflow_checks())
asyncio.run(breaker_and_resume_checks())

try:
    report.reject_unknown("claim [E9]", [{"id": "E1"}])
except ValueError:
    pass
else:
    raise AssertionError("unknown citation accepted")
source = {"id": "S1", "url": "https://example.test/page"}
assert report.compile_links("claim [E1]", {"E1": source}) == "claim [E1](https://example.test/page)"

# Retention, ack, and revision checks
mock_run = Run(brief(), {"search": "m", "note": "m", "report": "m"}, depth=1)
mock_run.status = "done"
mock_run.finished_at = 100.0
r.RUNS[mock_run.id] = mock_run
assert mock_run.state()["revision"] == 0
assert not r.ack("nonexistent")
active_run = Run(brief(), {"search": "m", "note": "m", "report": "m"}, depth=1)
r.RUNS[active_run.id] = active_run
assert not r.ack(active_run.id), "active run cannot be acked"
assert r.ack(mock_run.id)
assert mock_run.id not in r.RUNS
r.RUNS[active_run.id] = active_run
r.forget(active_run.id)

old_ttl = r.FINISHED_TTL
try:
    r.FINISHED_TTL = 10
    stale_run = Run(brief(), {"search": "m", "note": "m", "report": "m"}, depth=1)
    stale_run.status = "done"
    stale_run.finished_at = 50.0
    r.RUNS[stale_run.id] = stale_run
    r.evict()
    assert stale_run.id not in r.RUNS, "stale finished runs must be evicted past TTL"
finally:
    r.FINISHED_TTL = old_ttl

print("runs selfcheck OK")
