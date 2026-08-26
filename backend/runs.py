"""Research run lifecycle.

A run is an asyncio.Task plus its event list, held in the RUNS dict for the life of the process.
That is what survives a client closing the tab.
A process restart ends every run, and the brief lives in the browser, so the recovery is to start it again.
Phases are plan, gather, gap, report; the gather stage itself lives in research.py.
The finished payload is the research result: the report plus its per-subquestion note sections.
"""

import asyncio
import time
import uuid

from providers import Spend, complete
from research import PROMPTS, PageCache, gather, lines

RUNS = {}
FINISHED_TTL = 3600  # a finished run is evicted this long after the client could have collected it
MAX_ROUNDS = 2  # a gap check may add subquestions once
MAX_SUBQUESTIONS = 7
PLAN_MAX_TOKENS = 1024
REPORT_MAX_TOKENS = 16000


class Run:
    def __init__(self, brief, models, depth, title=None):
        self.id = uuid.uuid4().hex
        self.brief = brief
        # The planner receives clarifications in brief; the original question names the workspace.
        self.title = title or brief
        self.models = models  # {"search": id, "note": id, "report": id}
        self.depth = depth  # sources per subquestion
        self.status = "running"
        self.phase = "plan"
        self.events = []
        self.spend = Spend()
        self.pages = PageCache()
        self.payload = None
        self.error = None
        self.finished_at = None
        self.task = None

    def emit(self, kind, **data):
        self.events.append({"seq": len(self.events) + 1, "kind": kind, **data})

    def state(self, after=0):
        return {
            "id": self.id,
            "status": self.status,
            "phase": self.phase,
            "spend": self.spend.as_dict(),
            "events": self.events[after:],
            "payload": self.payload,
            "error": self.error,
        }


def answered(sections):
    """Sections with notes, used for contiguous `qN` report and card numbering."""
    return [s for s in sections if s["notes"]]


def result_payload(title, sections, report):
    """The provider-blind research result: report text plus the notes behind each answered subquestion.

    Section order matches the report's `qN` headings, so a client can cite either against the other.
    """
    return {
        "name": title[:60],
        "report": {"name": "Research report.md", "text": report},
        "sections": [
            {"question": s["question"], "notes": [{"note": n["note"], "url": n["url"]} for n in s["notes"]]}
            for s in sections
        ],
    }


async def _run(run):
    try:
        run.emit("phase", phase="plan")
        # Planning uses medium effort because its subquestions determine every downstream call.
        planned = lines(
            await complete(run.models["report"], PROMPTS["plan"], run.brief,
                           max_tokens=PLAN_MAX_TOKENS, effort="medium", spend=run.spend),
            MAX_SUBQUESTIONS,
        )
        if not planned:
            raise ValueError("could not turn that brief into subquestions")
        run.emit("plan", questions=planned)

        sections, asked = [], []
        for round_no in range(MAX_ROUNDS):
            run.phase = "gather"
            run.emit("phase", phase="gather", round=round_no + 1, questions=planned)
            found = await asyncio.gather(*(
                gather(q, run.models["search"], run.models["note"], limit=run.depth, spend=run.spend,
                       pages=run.pages, on_source=lambda q, r: run.emit("source", question=q, **r))
                for q in planned
            ))
            sections += found
            asked += planned
            if round_no + 1 >= MAX_ROUNDS:
                break
            run.phase = "gap"
            run.emit("phase", phase="gap")
            try:
                verdict = await complete(
                    run.models["report"], PROMPTS["gap"], _notes_prompt(run.brief, sections),
                    max_tokens=PLAN_MAX_TOKENS, spend=run.spend,
                )
            except Exception as err:
                # Deciding to stop is the safe default when the judge itself is unavailable.
                run.emit("warn", message=f"gap check skipped: {err}")
                break
            planned = [] if verdict.strip().upper().startswith("DONE") else lines(verdict, 3)
            if not planned:
                break

        run.phase = "report"
        # Report headings and cards share the filtered, contiguous qN list.
        found = answered(sections)
        run.emit("phase", phase="report", answered=len(found), planned=len(sections))
        try:
            report = await complete(
                run.models["report"], PROMPTS["report"], _notes_prompt(run.brief, found),
                max_tokens=REPORT_MAX_TOKENS, effort="medium", spend=run.spend,
            )
        except Exception as err:
            # Preserve gathered notes when report synthesis fails.
            run.error = f"report stage failed, notes returned unsynthesised: {err}"
            run.emit("warn", message=run.error)
            report = f"""(The report stage failed: {err})

The gathered notes follow.

""" + _notes_prompt(run.brief, found)
        run.payload = result_payload(run.title, found, report)
        run.status = "done"
        run.phase = "done"
        run.emit("done")
    except asyncio.CancelledError:
        run.status = "cancelled"
        run.emit("cancelled")
        raise
    except Exception as err:
        run.status = "error"
        run.error = str(err)
        run.emit("error", message=str(err))
    finally:
        run.pages.clear()  # the corpus was only ever needed to produce the notes
        run.finished_at = time.time()


def _notes_prompt(brief, sections):
    parts = [f"Research brief: {brief}\n"]
    for i, section in enumerate(sections, 1):
        parts.append(f"\n## q{i}. {section['question']}\n")
        for n in section["notes"]:
            # Source URLs are the fallback title.
            parts.append(f"\nSource: {n.get('title') or n['url']} ({n['url']})\n{n['note']}\n")
        if not section["notes"]:
            parts.append("\n(no sources could be read for this subquestion)\n")
    return "".join(parts)


def start(brief, models, depth=6, title=None):
    evict()
    run = Run(brief, models, depth, title=title)
    RUNS[run.id] = run
    run.task = asyncio.create_task(_run(run))
    return run


def forget(run_id):
    """Drop a run after the client stores its payload."""
    RUNS.pop(run_id, None)
    evict()


def evict():
    """Drop finished runs older than FINISHED_TTL during research-route activity."""
    cutoff = time.time() - FINISHED_TTL
    for run_id in [i for i, r in RUNS.items() if r.finished_at and r.finished_at < cutoff]:
        del RUNS[run_id]


if __name__ == "__main__":  # self-check: python runs.py
    # The payload's sections are the answered subquestions in report order, notes reduced to {note, url}.
    plan_sections = [
        {"question": "one", "notes": [{"url": "https://a.example/1", "note": "NOTE_A", "title": "extra"}]},
        {"question": "two", "notes": []},
        {"question": "three", "notes": [{"url": "https://a.example/3", "note": "NOTE_C"}]},
    ]
    found = answered(plan_sections)
    assert [s["question"] for s in found] == ["one", "three"], found
    payload = result_payload("brief text", found, "REPORT_BODY")
    assert payload["report"] == {"name": "Research report.md", "text": "REPORT_BODY"}
    assert [s["question"] for s in payload["sections"]] == ["one", "three"], "sections follow the answered order"
    assert payload["sections"][0]["notes"] == [{"note": "NOTE_A", "url": "https://a.example/1"}], "notes carry note and url only"

    # Report failure preserves the gathered notes.
    async def _resilience_checks():
        real_gather, real_complete = gather, complete

        async def canned_gather(question, *a, **k):
            return {"question": question, "notes": [{"url": "https://a.example/1", "note": "NOTE_BODY"}], "failed": []}

        async def complete_but_no_report(model_id, system, prompt, **k):
            if system is PROMPTS["plan"]:
                return "first subquestion here"
            if system is PROMPTS["report"]:
                raise RuntimeError("Error code: 529 - overloaded_error")
            return "DONE"

        globals().update(gather=canned_gather, complete=complete_but_no_report)
        try:
            run = Run("brief", {"search": "m", "note": "m", "report": "m"}, 2)
            await _run(run)
        finally:
            globals().update(gather=real_gather, complete=real_complete)
        assert run.status == "done", (run.status, run.error)
        assert "report stage failed" in run.error, run.error
        assert "NOTE_BODY" in run.payload["report"]["text"], "a failed report still hands over the notes"
        assert run.payload["sections"][0]["notes"], "and the note sections survive too"

    asyncio.run(_resilience_checks())

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
