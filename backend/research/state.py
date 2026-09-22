"""Research state and checkpoint validation."""

from copy import deepcopy
from tools.fetch import canonicalize

CHECKPOINT_VERSION = 1


def empty_state(brief, task):
    return {
        "version": CHECKPOINT_VERSION,
        "revision": 0,
        "brief": brief,
        "frontier": [{**task, "status": "pending", "attempts": 0}],
        "sources": {},
        "evidence": [],
        "gaps": [],
        "decisions": [],
        "breakers": [],
        "budgets": {"calls": 0, "sources": 0, "elapsed": 0.0, "no_progress": 0},
        "operations": {"queries": {}, "fetch_failures": {}, "completed": {}},
    }


def _list(value, name):
    if not isinstance(value, list):
        raise ValueError(f"checkpoint {name} must be an array")
    return value


def validate_checkpoint(value):
    """Validate and copy the browser-owned checkpoint before it enters a run."""
    if not isinstance(value, dict):
        raise ValueError("checkpoint must be an object")
    if value.get("version") != CHECKPOINT_VERSION:
        raise ValueError("unsupported checkpoint version")
    if not isinstance(value.get("revision"), int) or value["revision"] < 0:
        raise ValueError("checkpoint revision must be a non-negative integer")
    for key in ("brief", "frontier", "sources", "evidence", "gaps", "decisions", "breakers", "budgets", "operations"):
        if key not in value:
            raise ValueError(f"checkpoint missing {key}")
    if not isinstance(value["brief"], dict):
        raise ValueError("checkpoint brief must be an object")
    brief = value["brief"]
    if not isinstance(brief.get("objective"), str) or not brief["objective"].strip() or not isinstance(brief.get("deliverable"), str) or not brief["deliverable"].strip():
        raise ValueError("checkpoint brief has invalid objective or deliverable")
    for name in ("scope", "constraints"):
        if not isinstance(brief.get(name), list) or not brief[name] or any(not isinstance(item, str) or not item.strip() for item in brief[name]):
            raise ValueError(f"checkpoint brief {name} must be a non-empty string array")
    answers = brief.get("answers", {})
    if not isinstance(answers, dict) or any(not isinstance(key, str) or not key.strip() or not isinstance(item, str) or not item.strip() for key, item in answers.items()):
        raise ValueError("checkpoint brief answers must have non-empty string keys and values")
    _list(value["frontier"], "frontier")
    if not isinstance(value["sources"], dict) or not isinstance(value["budgets"], dict) or not isinstance(value["operations"], dict):
        raise ValueError("checkpoint registries must be objects")
    if any(not isinstance(value["operations"].get(name, {}), dict) for name in ("queries", "fetch_failures", "completed")):
        raise ValueError("checkpoint operations must be objects")
    _list(value["evidence"], "evidence")
    _list(value["gaps"], "gaps")
    _list(value["decisions"], "decisions")
    _list(value["breakers"], "breakers")
    task_ids = set()
    for task in value["frontier"]:
        if not isinstance(task, dict) or not isinstance(task.get("id"), str) or task.get("status") not in {"pending", "running", "done", "pruned"} or not isinstance(task.get("question"), str) or not isinstance(task.get("attempts", 0), int):
            raise ValueError("checkpoint contains an invalid frontier task")
        if task["id"] in task_ids:
            raise ValueError("checkpoint contains duplicate task IDs")
        task_ids.add(task["id"])
    source_ids = set()
    for key, source in value["sources"].items():
        if not isinstance(key, str) or not isinstance(source, dict) or not isinstance(source.get("id"), str) or not isinstance(source.get("url"), str) or not isinstance(source.get("task_ids", []), list):
            raise ValueError("checkpoint contains an invalid source")
        if not source["url"].lower().startswith(("http://", "https://")) or canonicalize(source["url"]) != key or source["id"] in source_ids:
            raise ValueError("checkpoint source keys must be canonical and unique")
        source_ids.add(source["id"])
    evidence_ids = set()
    for item in value["evidence"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("source_id"), str) or item["source_id"] not in source_ids:
            raise ValueError("checkpoint contains invalid evidence")
        if item["id"] in evidence_ids:
            raise ValueError("checkpoint contains duplicate evidence IDs")
        evidence_ids.add(item["id"])
    return deepcopy(value)


def checkpoint(state):
    state["revision"] += 1
    return deepcopy(state)
