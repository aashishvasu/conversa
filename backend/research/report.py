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


SECTION_WRITER = """Write the requested markdown report sections from only their assigned evidence. Keep every supplied heading exactly as written. Every factual claim must cite supplied evidence IDs exactly like [E1]. Do not add a heading or claim unsupported by that section's evidence. For a Gaps section, state only the supplied gaps. Return markdown only."""


def _section_prompt(brief, sections):
    blocks = []
    evidence_heading_added = False
    for heading, evidence, gaps in sections:
        if heading != "Summary" and not evidence_heading_added:
            blocks.append("## Evidence")
            evidence_heading_added = True
        heading_level = "##" if heading == "Summary" else "###"
        context = evidence_prompt(brief, evidence) if evidence else f"Brief: {json.dumps(brief, ensure_ascii=False)}"
        if gaps:
            context += "\n\nDeclared gaps:\n" + "\n".join(f"- {gap}" for gap in gaps)
        blocks.append(f"{heading_level} {heading}\n{context}")
    return "Write each section below independently, using only its context. Keep the supplied headings exactly.\n\n" + "\n\n--- SECTION ---\n\n".join(blocks)


def _section_plan(brief, evidence, coverage, gaps):
    by_id = {item["id"]: item for item in evidence}
    sections = [("Summary", evidence, [])]
    for scope_item in brief.get("scope", []):
        ids = coverage.get(scope_item, [])
        subset = [by_id[evidence_id] for evidence_id in ids if evidence_id in by_id]
        if subset:
            sections.append((str(scope_item), subset, []))
    if gaps:
        sections.append(("Gaps", [], gaps))
    return sections


def _section_batches(sections, count):
    count = min(count, len(sections))
    size = (len(sections) + count - 1) // count
    return [sections[index:index + size] for index in range(0, len(sections), size)]


async def write(brief, evidence, model_id, spend=None, coverage=None, gaps=None, run=None):
    if run is not None:
        coverage = run.data.get("coverage") if coverage is None else coverage
        gaps = run.data.get("gaps", []) if gaps is None else gaps
        budgets = run.data.get("budgets", {})
        remaining = max(0, run.max_calls - budgets.get("calls", 0))
    else:
        remaining = None
    gaps = [str(gap) for gap in gaps or [] if str(gap).strip()]

    if not isinstance(coverage, dict) or not coverage:
        if remaining is not None and remaining < 2:
            raise ValueError("research call budget exhausted before report writing and verification")
        text = await complete(model_id, REPORT, evidence_prompt(brief, evidence), max_tokens=16000, effort="medium", spend=spend)
        reject_unknown(text, evidence)
        return text

    sections = _section_plan(brief, evidence, coverage, gaps)
    if not sections:
        raise ValueError("no report sections can be written from the coverage ledger")
    section_budget = len(sections) if remaining is None else remaining - 1
    if section_budget < 1:
        raise ValueError("research call budget exhausted before report writing and verification")
    if section_budget == 1:
        text = await complete(model_id, SECTION_WRITER, _section_prompt(brief, sections), max_tokens=16000, effort="medium", spend=spend)
        reject_unknown(text, evidence)
        if not re.search(r"(?m)^## Summary\s*$", text):
            text = "## Summary\n\n" + text.strip()
        if not re.search(r"(?m)^## Evidence\s*$", text):
            text = text.rstrip() + "\n\n## Evidence"
        return text

    summary = await complete(model_id, SECTION_WRITER, _section_prompt(brief, sections[:1]), max_tokens=16000, effort="medium", spend=spend)
    reject_unknown(summary, evidence)
    if "## Summary" not in summary:
        summary = "## Summary\n\n" + summary.strip()

    evidence_sections = sections[1:]
    written = []
    if evidence_sections:
        for batch in _section_batches(evidence_sections, section_budget - 1):
            text = await complete(model_id, SECTION_WRITER, _section_prompt(brief, batch), max_tokens=16000, effort="medium", spend=spend)
            available = {item["id"]: item for _, subset, _ in batch for item in subset}
            reject_unknown(text, list(available.values()))
            written.append(re.sub(r"(?im)^## Evidence\s*", "", text).strip())
    stitched = f"{summary.strip()}\n\n## Evidence"
    if written:
        stitched += "\n\n" + "\n\n".join(written)
    return stitched


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
        "sections": [{"question": item.get("question", item.get("task_id")), "notes": [{"note": item.get("excerpt", item.get("note", "")), "url": by_id[item["source_id"]]["url"]}]} for item in evidence if item.get("source_id") in by_id],
        "evidence": evidence,
        "sources": list(sources.values()),
        "gaps": gaps,
        "decisions": decisions or [],
    }
