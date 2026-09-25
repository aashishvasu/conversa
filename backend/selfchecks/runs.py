"""Selfcheck: python -m selfchecks.runs"""

import asyncio
import json
import time
from contextlib import suppress

from research import gather as g
from research import report
from research import runs as r
from research.runs import RUNS, Run
from research.state import empty_state, validate_checkpoint


def brief():
    return {"objective": "Investigate Project Orion", "deliverable": "A sourced brief", "scope": ["Project Orion"], "constraints": ["cite evidence"], "questions": [], "answers": {"region": "US"}}


# WHY: reformulate_query makes a live provider call, so stub g.complete to keep selfchecks hermetic and free.
async def echo_reformulate(model, system, prompt, **kwargs):
    question = prompt.split("Research Question: ", 1)[1].split("\n", 1)[0]
    return f'["{question}"]'


async def workflow_checks():
    real = g.search, g._page, g.note, g.complete, r.complete, report.complete
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

    g.search, g._page, g.note, g.complete, r.complete, report.complete = search, page, note, echo_reformulate, complete, complete
    old_min = r.MIN_EVIDENCE
    r.MIN_EVIDENCE = 1
    try:
        run = Run(brief(), {"search": "m", "note": "m", "report": "m"}, depth=2)
        await r._run(run)
    finally:
        r.MIN_EVIDENCE = old_min
        g.search, g._page, g.note, g.complete, r.complete, report.complete = real
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
    real = g.search, g.complete, r.complete, report.complete
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
    g.search, g.complete, r.complete, report.complete = repeated, echo_reformulate, complete, complete
    try:
        run = Run(brief(), {"search": "m", "note": "m", "report": "m"}, depth=1)
        await r._run(run)
    finally:
        g.search, g.complete, r.complete, report.complete = real
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
        r.complete, report.complete = real[2], real[3]
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

# Coverage gate: premature finish converts to continue once, then passes.
gate_run = Run(brief(), {"search": "m", "note": "m", "report": "m"}, depth=1)
gate_run.evidence.append({"id": "E1", "source_id": "S1", "question": "unrelated topic", "title": "x", "excerpt": "y" * 500})
finish = {"action": "finish", "resolve": [], "prune": [], "add": [], "merge": [], "gaps": []}
gated = r._coverage_gate(gate_run, finish)
assert gated["action"] == "continue" and gated["gaps"] and gate_run.data["budgets"]["coverage_override"]
assert any(event["kind"] == "breaker" and event.get("branch") == "coverage" for event in gate_run.events)
assert r._coverage_gate(gate_run, finish)["action"] == "finish", "one override per run"
covered_run = Run(brief(), {"search": "m", "note": "m", "report": "m"}, depth=1)
old_min = r.MIN_EVIDENCE
r.MIN_EVIDENCE = 1
try:
    covered_run.evidence.extend({"id": f"E{i}", "source_id": "S1", "question": "Investigate Project Orion", "title": "t", "excerpt": "e"} for i in range(1, 3))
    assert r._coverage_gate(covered_run, finish)["action"] == "finish"
finally:
    r.MIN_EVIDENCE = old_min

# Coordinator payload: gists only, no raw evidence rows.
payload = r._coordinator_payload(gate_run, [{"evidence": [{"id": "E1"}], "gaps": ["worker gap"]}])
assert "new_results" not in payload and payload["new_evidence_ids"] == ["E1"] and payload["worker_gaps"] == ["worker gap"]
assert len(payload["evidence"][0]["gist"]) == 240
assert isinstance(payload["exhausted_queries"], list) and isinstance(payload["scope_coverage"], dict)

# Outcome strings for terminal and active runs.
models = {"search": "m", "note": "m", "report": "m"}
finished_run = Run(brief(), models, depth=1)
finished_run.status = "done"
finished_run.finished_at = time.time()
r.RUNS[finished_run.id] = finished_run
assert r.start(brief(), models, run_id=finished_run.id)[1] == "already_finished"
busy_run = Run(brief(), models, depth=1)
busy_run.status = "running"
r.RUNS[busy_run.id] = busy_run
assert r.start(brief(), models, run_id=busy_run.id)[1] == "already_running"
r.forget(finished_run.id)
r.forget(busy_run.id)

print("runs selfcheck OK")
