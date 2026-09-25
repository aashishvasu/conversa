"""Selfcheck: python -m selfchecks.report"""

import asyncio
from types import SimpleNamespace

from research import report


BRIEF = {"objective": "Study the subject", "deliverable": "A sourced report", "scope": ["Scope A", "Scope B"], "constraints": ["Use citations"]}
EVIDENCE = [
    {"id": "E1", "source_id": "S1", "title": "Source A", "excerpt": "Fact A"},
    {"id": "E2", "source_id": "S2", "title": "Source B", "excerpt": "Fact B"},
]


async def checks():
    original = report.complete
    calls = []

    async def complete(model, system, prompt, **kwargs):
        calls.append((system, prompt))
        if system == report.REPORT:
            return "## Summary\n\nLegacy report [E1]"
        if system == report.VERIFY:
            return '{"valid":true,"corrections":"","gaps":[]}'
        if all(marker in prompt for marker in ("## Summary", "## Evidence", "### Scope A", "### Scope B", "### Gaps")):
            return "## Summary\n\nSummary [E1] [E2]\n\n## Evidence\n\n### Scope A\n\nFact A [E1]\n\n### Scope B\n\nFact B [E2]\n\n### Gaps\n\nKnown limitation."
        if "## Summary" in prompt:
            return "## Summary\n\nSummary [E1] [E2]"
        if "### Scope A" in prompt:
            return "### Scope A\n\nFact A [E1]"
        if "### Scope B" in prompt:
            return "### Scope B\n\nFact B [E2]"
        if "### Gaps" in prompt:
            return "### Gaps\n\nKnown limitation."
        return ""

    report.complete = complete
    try:
        run = SimpleNamespace(
            max_calls=12,
            data={"budgets": {"calls": 2}, "coverage": {"Scope A": ["E1"], "Scope B": ["E2"]}, "gaps": ["Known limitation"]},
        )
        draft = await report.write(BRIEF, EVIDENCE, "model", coverage=run.data["coverage"], gaps=run.data["gaps"], run=run)
        assert "## Summary" in draft and "## Evidence" in draft
        assert "### Scope A" in draft and "[E1]" in draft
        assert "### Scope B" in draft and "[E2]" in draft
        assert "### Gaps" in draft and "Known limitation" in draft
        scope_a_prompt = next(prompt for system, prompt in calls if system == report.SECTION_WRITER and "### Scope A" in prompt)
        assert "[E1]" in scope_a_prompt and "[E2]" not in scope_a_prompt, "scope sections receive only their ledger evidence"
        scope_b_prompt = next(prompt for system, prompt in calls if system == report.SECTION_WRITER and "### Scope B" in prompt)
        assert "[E2]" in scope_b_prompt and "[E1]" not in scope_b_prompt, "scope sections receive only their ledger evidence"

        calls.clear()
        verified, gaps = await report.verify_and_correct(draft, BRIEF, EVIDENCE, "model")
        assert verified == draft and gaps == []
        assert len([call for call in calls if call[0] == report.VERIFY]) == 1, "the stitched report gets one verification pass"
        assert "### Scope A" in calls[0][1] and "### Scope B" in calls[0][1], "verification sees the whole stitched report"

        calls.clear()
        constrained = SimpleNamespace(
            max_calls=4,
            data={"budgets": {"calls": 2}, "coverage": {"Scope A": ["E1"], "Scope B": ["E2"]}, "gaps": ["Known limitation"]},
        )
        bounded = await report.write(BRIEF, EVIDENCE, "model", run=constrained)
        section_calls = [call for call in calls if call[0] == report.SECTION_WRITER]
        assert len(section_calls) <= constrained.max_calls - constrained.data["budgets"]["calls"] - 1, "section calls leave budget for verification"
        assert "### Scope A" in section_calls[0][1] and "### Scope B" in section_calls[0][1]
        assert "### Gaps" in section_calls[0][1] and "## Evidence" in bounded

        calls.clear()
        fallback = await report.write(BRIEF, EVIDENCE, "model", coverage={})
        assert fallback == "## Summary\n\nLegacy report [E1]"
        assert len(calls) == 1 and calls[0][0] == report.REPORT, "an empty coverage ledger keeps the single-pass writer"
    finally:
        report.complete = original


if __name__ == "__main__":
    asyncio.run(checks())
    print("research report selfcheck OK")
