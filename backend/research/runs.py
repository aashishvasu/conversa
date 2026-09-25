"""Research run lifecycle and frontier assembly."""

import asyncio
import json
import os
import re
import time
import uuid
from copy import deepcopy
from urllib.parse import urlsplit

from providers import Spend, complete
from tools.fetch import canonicalize
from .gather import gather_task
from .parsing import object_from_text
from .prompts import COORDINATOR, PROMPTS
from .report import payload as report_payload, verify_and_correct, write as write_report
from .state import checkpoint, empty_state, validate_checkpoint

RUNS = {}
FINISHED_TTL = int(os.environ.get("RESEARCH_RESULT_TTL", "3600"))
MAX_ACTIVE_RUNS = int(os.environ.get("MAX_ACTIVE_RUNS", "2"))
MAX_WAVES = int(os.environ.get("RESEARCH_MAX_WAVES", "8"))
MAX_TASKS = int(os.environ.get("RESEARCH_MAX_TASKS", "18"))
MAX_CALLS = int(os.environ.get("RESEARCH_MAX_CALLS", "48"))
MAX_SOURCES = int(os.environ.get("RESEARCH_MAX_SOURCES", "24"))
MAX_ELAPSED = float(os.environ.get("RESEARCH_MAX_SECONDS", "900"))
MIN_EVIDENCE = int(os.environ.get("RESEARCH_MIN_EVIDENCE", "8"))
DEFAULT_RESEARCH_DEPTH = int(os.environ.get("DEFAULT_RESEARCH_DEPTH", "5"))


class RunLimitError(Exception):
    pass


def _reopen_failed_tasks(data):
    supported = {task_id for item in data["evidence"] for task_id in (item.get("task_ids") or [item.get("task_id")]) if task_id}
    completed = data["operations"].setdefault("completed", {})
    for task in data["frontier"]:
        if task.get("status") == "pruned" and task.get("id") not in supported and task.get("attempts", 0) < 3:
            task["status"] = "pending"
            completed.pop(task.get("operation_id"), None)
            query = " ".join(task.get("question", "").lower().split())
            data["operations"].setdefault("queries", {}).pop(query, None)


def _brief(value):
    if isinstance(value, dict):
        brief = deepcopy(value)
        for name in ("scope", "constraints"):
            if isinstance(brief.get(name), str):
                brief[name] = [brief[name]]
        return brief
    return {"objective": str(value), "deliverable": "A sourced research brief", "scope": ["The requested subject"], "constraints": ["Use current public sources"], "questions": []}


class Run:
    def __init__(self, brief, models, depth=DEFAULT_RESEARCH_DEPTH, title=None, prompts=None, run_id=None, checkpoint_data=None, restart_failed=False):
        self.id = run_id or uuid.uuid4().hex
        self.brief = _brief(brief)
        self.title = title or self.brief.get("objective", "Research")
        self.models = models
        self.depth = depth
        self.prompts = {**PROMPTS, **(prompts or {})}
        self.status = "running"
        self.phase = "researching"
        self.events = []
        self.spend = Spend()
        self.payload = None
        self.error = None
        self.finished_at = None
        self.task = None
        self.started_at = time.monotonic()
        broad = {"id": "T1", "question": self.brief.get("objective", "Explore the requested subject"), "reason": "broad initial exploration"}
        resumed_from_checkpoint = checkpoint_data is not None
        self.data = validate_checkpoint(checkpoint_data) if resumed_from_checkpoint else empty_state(self.brief, broad)
        self.data["brief"] = self.brief
        self.prior_calls = self.data["budgets"].get("calls", 0) if resumed_from_checkpoint else 0
        self.prior_elapsed = float(self.data["budgets"].get("elapsed", 0.0)) if resumed_from_checkpoint else 0.0
        if resumed_from_checkpoint:
            self.data["budgets"]["fallback_calls"] = 0
        completed = self.data["operations"].setdefault("completed", {})
        for task in self.data["frontier"]:
            if task.get("status") == "running":
                task["status"] = "done" if completed.get(task.get("operation_id")) else "pending"
        if restart_failed:
            _reopen_failed_tasks(self.data)
        self.sources = self.data["sources"]
        self.evidence = self.data["evidence"]
        self.frontier = self.data["frontier"]
        self.seen_urls = set(self.sources)
        if not resumed_from_checkpoint:
            self.emit("task_added", task=deepcopy(self.frontier[0]))

    def emit(self, kind, **data):
        event = {"seq": len(self.events) + 1, "kind": kind, **data}
        self.events.append(event)
        if kind == "breaker":
            self.data["breakers"].append(deepcopy(event))

    def checkpoint(self):
        snapshot = checkpoint(self.data)
        self.emit("checkpoint", revision=snapshot["revision"], checkpoint=snapshot)

    def update_calls(self):
        budget = self.data["budgets"]
        budget["calls"] = self.prior_calls + self.spend.calls + budget.get("fallback_calls", 0)
        return budget["calls"]

    def state(self, after=0):
        return {"id": self.id, "revision": self.data.get("revision", 0), "status": self.status, "phase": self.phase, "spend": self.spend.as_dict(), "events": self.events[after:], "payload": self.payload, "error": self.error, "checkpoint": deepcopy(self.data), "evidence": self.evidence, "sources": list(self.sources.values()), "gaps": self.data["gaps"], "decisions": self.data["decisions"], "breakers": self.data["breakers"]}


def _valid_coord(value):
    return isinstance(value, dict) and value.get("action") in {"continue", "finish"} and all(isinstance(value.get(key), list) for key in ("resolve", "prune", "add", "merge", "gaps"))


def _worker_context(run):
    findings = [{"id": item["id"], "question": item.get("question"), "excerpt": (item.get("excerpt") or item.get("note", ""))[:600]} for item in run.evidence[-12:]]
    return json.dumps({"mission": run.brief, "known_findings": findings, "gaps": run.data["gaps"], "seen_urls": sorted(run.seen_urls)}, ensure_ascii=False)


async def _coordinator(run, results):
    prompt = json.dumps(_coordinator_payload(run, results), ensure_ascii=False)
    system = run.prompts.get("coordinator", COORDINATOR)
    response = await complete(run.models["report"], system, prompt, max_tokens=3000, spend=run.spend)
    try:
        value = object_from_text(response)
    except Exception:
        value = None
    if not _valid_coord(value):
        repair = await complete(run.models["report"], system + "\nRepair the invalid response and return the required JSON.", prompt, max_tokens=3000, spend=run.spend)
        try:
            value = object_from_text(repair)
        except Exception:
            value = None
    if not _valid_coord(value):
        raise ValueError("coordinator returned an invalid transition")
    return value


def _scope_tokens(text):
    return {token for token in re.findall(r"[a-z0-9]+", str(text).lower()) if len(token) > 3}


def _scope_coverage(run):
    """Count evidence per brief scope item.

    Matches question and title only; note bodies carry page noise that
    inflates coverage.
    """
    coverage = {}
    for item in run.brief.get("scope", []):
        tokens = _scope_tokens(item)
        coverage[item] = len(run.evidence) if not tokens else sum(1 for ev in run.evidence if tokens & _scope_tokens(f"{ev.get('question', '')} {ev.get('title', '')}"))
    return coverage


def _uncovered_scope(run):
    gap_text = " ".join(run.data["gaps"]).lower()
    uncovered = []
    for item, count in _scope_coverage(run).items():
        if count:
            continue
        if any(token in gap_text for token in _scope_tokens(item)):
            continue
        uncovered.append(item)
    return uncovered


def _coverage_gate(run, decision):
    """Reject a premature finish once per run; the second finish passes."""
    if decision["action"] != "finish" or run.data["budgets"].get("coverage_override"):
        return decision
    uncovered = _uncovered_scope(run)
    if len(run.evidence) >= MIN_EVIDENCE and not uncovered:
        return decision
    run.data["budgets"]["coverage_override"] = True
    run.emit("breaker", branch="coverage", message=f"finish rejected: {len(run.evidence)} evidence items, uncovered scope: {uncovered or 'none'}")
    target = ", ".join(uncovered) if uncovered else "the full scope"
    return {**decision, "action": "continue", "gaps": [*decision["gaps"], f"coverage gate: gather more evidence for {target} (minimum {MIN_EVIDENCE} items)"]}


def _coordinator_payload(run, results):
    """Project evidence to gists so the coordinator input stays bounded."""
    url_by_id = {row["id"]: url for url, row in run.sources.items()}
    return {
        "brief": run.brief,
        "tasks": [{"id": task["id"], "question": task["question"], "status": task.get("status"), "reason": task.get("reason", "")} for task in run.frontier],
        "evidence": [{"id": item["id"], "task_id": item.get("task_id"), "domain": urlsplit(url_by_id.get(item.get("source_id"), "") or "").netloc, "question": item.get("question"), "gist": (item.get("excerpt") or item.get("note") or "")[:240]} for item in run.evidence],
        "new_evidence_ids": [item["id"] for result in results for item in result.get("evidence", []) if item.get("id")],
        "worker_gaps": sorted({gap for result in results for gap in result.get("gaps", []) if gap}),
        "gaps": run.data["gaps"],
        "exhausted_queries": sorted(query for query, count in run.data["operations"].get("queries", {}).items() if count >= 2),
        "budgets": {key: run.data["budgets"].get(key) for key in ("calls", "sources", "elapsed", "no_progress")},
        "scope_coverage": _scope_coverage(run),
    }


def _apply_coord(run, decision):
    by_id = {task["id"]: task for task in run.frontier}
    for task_id in decision["resolve"]:
        if task_id in by_id:
            by_id[task_id]["status"] = "done"
    for task_id in decision["prune"]:
        if task_id in by_id:
            by_id[task_id]["status"] = "pruned"
            run.emit("task_pruned", task=deepcopy(by_id[task_id]), message="coordinator pruned task")
            run.emit("breaker", task_id=task_id, branch="coordinator", message="task pruned")
    for task_id in decision["merge"]:
        if task_id in by_id:
            by_id[task_id]["status"] = "pruned"
            run.emit("task_merged", task=deepcopy(by_id[task_id]), message="duplicate task pruned")
    questions = {" ".join(task.get("question", "").lower().split()) for task in run.frontier}
    for item in decision["add"]:
        if not isinstance(item, dict) or not isinstance(item.get("question"), str) or not item["question"].strip() or len(run.frontier) >= MAX_TASKS:
            continue
        question = " ".join(item["question"].split())
        if question.lower() in questions:
            run.emit("breaker", branch="duplicate", message=f"duplicate task rejected: {question}")
            continue
        task = {"id": f"T{len(run.frontier) + 1}", "question": question, "reason": str(item.get("reason", "follow-up")), "status": "pending", "attempts": 0}
        run.frontier.append(task)
        by_id[task["id"]] = task
        questions.add(question.lower())
        run.emit("task_added", task=deepcopy(task))
    if decision["action"] == "finish" and not decision["gaps"]:
        run.data["gaps"].clear()
    for gap in decision["gaps"]:
        if str(gap).strip() and str(gap).strip() not in run.data["gaps"]:
            run.data["gaps"].append(str(gap).strip())
    run.data["decisions"].append(decision)
    run.checkpoint()


async def _write(run):
    run.phase = "writing"
    run.emit("phase", phase="writing")
    run.checkpoint()
    draft = await write_report(run.brief, run.evidence, run.models["report"], run.spend)
    run.phase = "verifying"
    run.emit("phase", phase="verifying")
    run.checkpoint()
    try:
        report, gaps = await verify_and_correct(draft, run.brief, run.evidence, run.models["report"], run.spend)
    except Exception as error:
        run.data["gaps"].append(f"citation verification failed: {error}")
        run.payload = report_payload(run.title, draft, run.evidence, run.sources, run.data["gaps"], run.data["decisions"])
        run.status = "partial"
        run.phase = "partial"
        run.emit("partial", message=str(error))
        run.checkpoint()
        return
    run.data["gaps"].extend(gap for gap in gaps if gap not in run.data["gaps"])
    run.payload = report_payload(run.title, report, run.evidence, run.sources, run.data["gaps"], run.data["decisions"])
    run.status = "done" if not run.data["gaps"] else "partial"
    run.phase = "done" if run.status == "done" else "partial"
    run.emit(run.status, payload=run.payload)
    run.checkpoint()


async def _run(run):
    try:
        if run.phase == "writing":
            await _write(run)
            return
        run.phase = "researching"
        run.emit("phase", phase="researching")
        if not any(task.get("status") == "pending" for task in run.frontier):
            run.emit("breaker", branch="restart", message="restart found no pending tasks; finishing from the checkpoint")
        no_progress = run.data["budgets"].get("no_progress", 0)
        for wave in range(MAX_WAVES):
            elapsed = run.prior_elapsed + time.monotonic() - run.started_at
            budget = run.data["budgets"]
            budget["elapsed"] = elapsed
            run.update_calls()
            if elapsed >= MAX_ELAPSED or budget["calls"] >= MAX_CALLS or len(run.sources) >= MAX_SOURCES:
                run.emit("breaker", branch="global", message="research budget reached")
                if "research stopped at a global breaker" not in run.data["gaps"]:
                    run.data["gaps"].append("research stopped at a global breaker")
                break
            pending = [task for task in run.frontier if task.get("status") == "pending"]
            if not pending:
                break
            selected = []
            for task in pending:
                query = " ".join(task["question"].lower().split())
                count = run.data["operations"].setdefault("queries", {}).get(query, 0)
                if count >= 2:
                    task["status"] = "pruned"
                    run.emit("task_pruned", task=deepcopy(task), message="same normalized query used twice")
                    run.emit("breaker", task_id=task["id"], branch="query", message="same normalized query used twice")
                    continue
                if task.get("attempts", 0) >= 3:
                    task["status"] = "pruned"
                    run.emit("task_pruned", task=deepcopy(task), message="task attempt ceiling reached")
                    run.emit("breaker", task_id=task["id"], branch="task", message="task attempt ceiling reached")
                    continue
                task["attempts"] = task.get("attempts", 0) + 1
                task["operation_id"] = f"{task['id']}:{task['attempts']}"
                if run.data["operations"].setdefault("completed", {}).get(task["operation_id"]):
                    task["status"] = "done"
                    continue
                task["status"] = "running"
                run.emit("task_started", task=deepcopy(task))
                run.data["operations"].setdefault("queries", {})[query] = count + 1
                selected.append(task)
                if len(selected) == 3:
                    break
            if not selected:
                break
            run.emit("wave", number=wave + 1, task_ids=[task["id"] for task in selected])
            budget.setdefault("fallback_calls", 0)
            budget["fallback_calls"] += len(selected)
            run.update_calls()
            before = len(run.evidence)
            worker_context = _worker_context(run)
            search_prompt = f"{run.prompts.get('search', '')}\nShared worker context:\n{worker_context}"
            note_prompt = run.prompts.get("note", "")
            def worker_event(kind, **data):
                if kind == "breaker" and data.get("branch") == "fetch" and data.get("url"):
                    failures = run.data["operations"].setdefault("fetch_failures", {})
                    url = canonicalize(data["url"])
                    failures[url] = failures.get(url, 0) + 1
                    data["attempts"] = failures[url]
                    if failures[url] >= 2:
                        data["message"] = "fetch failure ceiling reached: " + data.get("message", "")
                run.emit(kind, **data)
            results = await asyncio.gather(*(gather_task(task, run.brief, run.models["search"], run.models.get("note", run.models["report"]), run.sources, run.evidence, run.seen_urls, run.depth, run.spend, worker_event, search_prompt, note_prompt, operations=run.data["operations"]) for task in selected))
            for task, result in zip(selected, results):
                task["status"] = "done" if any(record.get("id") for record in result.get("evidence", [])) else "pruned"
                run.emit("task_resolved" if task["status"] == "done" else "task_pruned", task=deepcopy(task))
                run.data["operations"].setdefault("completed", {})[task["operation_id"]] = True
                for record in result.get("evidence", []):
                    if record.get("id"):
                        run.emit("evidence", task_id=task["id"], evidence=deepcopy(record))
                for gap in result.get("gaps", []):
                    if gap and gap not in run.data["gaps"]:
                        run.data["gaps"].append(gap)
            run.data["budgets"]["sources"] = len(run.sources)
            progressed = len(run.evidence) > before
            if not progressed:
                no_progress += 1
                run.data["budgets"]["no_progress"] = no_progress
            else:
                no_progress = 0
                run.data["budgets"]["no_progress"] = 0
            run.checkpoint()
            budget["elapsed"] = run.prior_elapsed + time.monotonic() - run.started_at
            run.update_calls()
            if budget["elapsed"] >= MAX_ELAPSED or budget["calls"] >= MAX_CALLS or len(run.sources) >= MAX_SOURCES:
                run.emit("breaker", branch="global", message="research budget reached")
                if "research stopped at a global breaker" not in run.data["gaps"]:
                    run.data["gaps"].append("research stopped at a global breaker")
                break
            if no_progress >= 2:
                run.emit("breaker", branch="global", message="two consecutive waves made no progress")
                if "research stopped after two no-progress waves" not in run.data["gaps"]:
                    run.data["gaps"].append("research stopped after two no-progress waves")
                break
            try:
                decision = await _coordinator(run, results)
                run.update_calls()
            except Exception as error:
                run.emit("breaker", branch="coordinator", message=str(error))
                run.data["gaps"].append(f"coordinator stopped gathering: {error}")
                break
            decision = _coverage_gate(run, decision)
            _apply_coord(run, decision)
            if decision["action"] == "finish":
                break
        if not run.evidence:
            run.status = "error"
            run.phase = "error"
            run.error = "research produced no evidence"
            run.emit("error", message=run.error)
            run.checkpoint()
            return
        try:
            await _write(run)
        except Exception as error:
            run.status = "error"
            run.phase = "writing"
            run.error = f"report stage failed: {error}"
            run.emit("error", message=run.error)
            run.checkpoint()
    except asyncio.CancelledError:
        run.status = "cancelled"
        run.phase = "cancelled"
        run.emit("cancelled")
        run.checkpoint()
        raise
    except Exception as error:
        run.status = "error"
        run.phase = "error"
        run.error = str(error)
        run.emit("error", message=str(error))
        run.checkpoint()
    finally:
        run.finished_at = time.time()
        run.task = None


def start(brief, models, depth=DEFAULT_RESEARCH_DEPTH, title=None, prompts=None, run_id=None, checkpoint_data=None, restart_failed=False):
    """Start or reattach a run. Returns (run, outcome) where outcome is one of
    created, resumed_from_checkpoint, restarted, already_running, already_finished."""
    evict()
    if run_id and (existing := RUNS.get(run_id)):
        if existing.status == "error" and existing.task is None:
            existing.models = models
            existing.brief = _brief(brief)
            existing.title = title or existing.brief.get("objective", existing.title)
            existing.data["brief"] = existing.brief
            completed = existing.data["operations"].setdefault("completed", {})
            for task in existing.frontier:
                if task.get("status") == "running":
                    task["status"] = "done" if completed.get(task.get("operation_id")) else "pending"
            if restart_failed:
                _reopen_failed_tasks(existing.data)
            existing.status = "running"
            existing.phase = "researching"
            existing.error = None
            existing.started_at = time.monotonic()
            existing.finished_at = None
            existing.emit("resumed", outcome="restarted")
            existing.task = asyncio.create_task(_run(existing))
            return existing, "restarted"
        if existing.status == "running":
            return existing, "already_running"
        return existing, "already_finished"
    if sum(run.status == "running" for run in RUNS.values()) >= MAX_ACTIVE_RUNS:
        raise RunLimitError(f"at most {MAX_ACTIVE_RUNS} research runs at once")
    run = Run(brief, models, depth, title, prompts, run_id, checkpoint_data, restart_failed)
    RUNS[run.id] = run
    if checkpoint_data is not None:
        run.emit("resumed", outcome="resumed_from_checkpoint")
    run.task = asyncio.create_task(_run(run))
    return run, "resumed_from_checkpoint" if checkpoint_data is not None else "created"


def ack(run_id):
    run = RUNS.get(run_id)
    if not run or run.status == "running":
        return False
    RUNS.pop(run_id, None)
    return True


def forget(run_id):
    RUNS.pop(run_id, None)
    evict()


def evict():
    cutoff = time.time() - FINISHED_TTL
    for run_id in [key for key, run in RUNS.items() if run.finished_at and run.finished_at < cutoff]:
        del RUNS[run_id]
