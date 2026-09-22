"""Evidence-bound report assembly."""

import json
import re

from providers import complete
from .parsing import object_from_text
from .prompts import REPORT, VERIFY

CITATION = re.compile(r"\[E(\d+)\]")


def evidence_prompt(brief, evidence):
    lines = [f"Brief: {json.dumps(brief, ensure_ascii=False)}", "Evidence:"]
    for item in evidence:
        lines.append(f"[{item['id']}] ({item.get('title') or item['source_id']}) {item.get('excerpt') or item.get('note', '')}")
    return "\n\n".join(lines)


def citation_ids(text):
    return {f"E{number}" for number in CITATION.findall(text or "")}


def reject_unknown(text, evidence):
    known = {item["id"] for item in evidence}
    unknown = sorted(citation_ids(text) - known)
    if unknown:
        raise ValueError(f"unknown evidence IDs: {', '.join(unknown)}")


def compile_links(text, sources):
    def replace(match):
        evidence_id = f"E{match.group(1)}"
        source = sources[evidence_id]
        return f"[{evidence_id}]({source['url']})"
    return CITATION.sub(replace, text)


async def write(brief, evidence, model_id, spend=None):
    text = await complete(model_id, REPORT, evidence_prompt(brief, evidence), max_tokens=16000, effort="medium", spend=spend)
    reject_unknown(text, evidence)
    return text


async def verify_and_correct(text, brief, evidence, model_id, spend=None):
    """Run one semantic citation pass. Unknown IDs are rejected before and after it."""
    reject_unknown(text, evidence)
    response = await complete(model_id, VERIFY, json.dumps({"brief": brief, "draft": text, "evidence": evidence}, ensure_ascii=False), max_tokens=5000, spend=spend)
    try:
        result = object_from_text(response)
    except (TypeError, ValueError) as error:
        raise ValueError("citation verifier returned invalid JSON") from error
    if not isinstance(result, dict) or not isinstance(result.get("valid"), bool) or not isinstance(result.get("corrections", ""), str) or not isinstance(result.get("gaps", []), list):
        raise ValueError("citation verifier returned an invalid result")
    corrected = result["corrections"] or text
    reject_unknown(corrected, evidence)
    if not result["valid"] and not result["corrections"]:
        raise ValueError("citation verification failed: " + "; ".join(str(gap) for gap in result["gaps"]))
    return corrected, [str(gap) for gap in result["gaps"]]


def payload(title, report, evidence, sources, gaps, decisions=None):
    by_id = {source["id"]: source for source in sources.values()}
    links = {item["id"]: by_id[item["source_id"]] for item in evidence if item.get("source_id") in by_id}
    linked = compile_links(report, links)
    summary_match = re.search(r"(?is)^##\s+summary\s*$\n(.*?)(?=^##\s|\Z)", linked, re.MULTILINE)
    summary = (summary_match.group(1).strip() if summary_match else "")
    return {
        "name": (title or "Research")[:60],
        "summary": summary,
        "report": {"name": "Research report.md", "text": linked},
        "sections": [{"question": item.get("question", item.get("task_id")), "notes": [{"note": item.get("note", item.get("excerpt", "")), "url": by_id[item["source_id"]]["url"]}]} for item in evidence if item.get("source_id") in by_id],
        "evidence": evidence,
        "sources": list(sources.values()),
        "gaps": gaps,
        "decisions": decisions or [],
    }
