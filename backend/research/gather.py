"""Deterministic search, fetch, and evidence extraction."""

import asyncio
import json
import re

import providers
from providers import complete
from tools import fetch as app_fetch
from tools import search as app_search
from tools.conversa_tool import ToolCall, execute_tool
from tools.fetch import canonicalize
from tools.registry import resolve_research_tools
from .parsing import Note, note_from_text, object_from_text
from .prompts import PROMPTS

SCAN_MULTIPLIER = 4
TRIAGE_MAX_TOKENS = 300
SEARCH_MAX_USES = 6
FETCH_CONCURRENCY = 6
NOTE_MAX_TOKENS = 1500
NOTE_MAX_PAGES = 3
NOTHING = "NOTHING RELEVANT"
PAGE_HINT = '\n\nIf you need more of the document, reply with only {"fetch_offset": OFFSET} to read the next window.'
FATAL_TEXT = ("unauthorized", "forbidden", "401", "403", "credit", "quota", "invalid model", "authentication", "api key")
RETRYABLE_TEXT = ("timeout", "timed out", "rate", "429", "502", "503", "504", "connection", "temporarily")


def _mentions_fatal(text):
    return any(word in text for word in FATAL_TEXT)


def _fatal_provider(error):
    if isinstance(error, app_fetch.FetchError):
        return False
    return _mentions_fatal(str(error).lower())


def _retryable(error):
    if isinstance(error, app_fetch.FetchPolicyError):
        return False
    if isinstance(error, app_fetch.FetchError):
        return error.status is None or error.status >= 500 or error.status == 429
    text = str(error).lower()
    if _mentions_fatal(text):
        return False
    return any(word in text for word in RETRYABLE_TEXT)


async def _retry(call, retries=2):
    for attempt in range(retries + 1):
        try:
            return await call()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if attempt >= retries or not _retryable(error):
                raise
            await asyncio.sleep(0.5 * 2 ** attempt)


async def search(query, model_id, limit=8, search_prompt=None, spend=None):
    provider, model = providers.split_model(model_id)
    hosted = None
    entry = providers.PROVIDERS.get(provider)
    if entry and entry.get("search_tool"):
        hosted = _hosted_finder(provider)
    try:
        hits = await _retry(lambda: app_search.search(query, limit))
    except Exception:
        if hosted is None:
            raise
        hits = await _retry(lambda: hosted(query, model, limit, provider, search_prompt or PROMPTS["search"], spend, model_id))
    if hits is None:
        if hosted is None:
            raise RuntimeError(f"provider {provider} has no hosted search and no app search key is configured")
        hits = await _retry(lambda: hosted(query, model, limit, provider, search_prompt or PROMPTS["search"], spend, model_id))
    return app_search.filter_hits(hits, limit)


async def _search_anthropic(query, model, limit, provider, prompt, spend=None, model_id=None):
    tools = [{"type": providers.PROVIDERS[provider]["search_tool"], "name": "web_search", "max_uses": SEARCH_MAX_USES, "blocked_domains": app_search.BLOCKED_DOMAINS}]
    message = await providers.CLIENTS[provider].messages.create(model=model, max_tokens=4096, system=prompt, messages=[{"role": "user", "content": query}], tools=tools)
    if spend:
        usage = providers.anthropic_usage(message.usage)
        spend.add(model_id, usage["input"], usage["output"], usage["cache_read"], usage["cache_write"], usage["search_requests"])
    hits = []
    for block in message.content:
        if getattr(block, "type", "") == "web_search_tool_result" and isinstance(getattr(block, "content", None), list):
            hits.extend({"title": getattr(result, "title", None), "url": result.url} for result in block.content if getattr(result, "type", "") == "web_search_result")
    return hits[:limit * 3]


def _responses_hits(response, limit):
    hits = []
    for item in response.output or []:
        for part in getattr(item, "content", None) or []:
            for annotation in getattr(part, "annotations", None) or []:
                if providers.field(annotation, "type") == "url_citation" and providers.field(annotation, "url"):
                    hits.append({"title": providers.field(annotation, "title"), "url": providers.field(annotation, "url")})
            for url in re.findall(r"https?://[^\s<>()\[\]{}\"']+", providers.field(part, "text") or ""):
                hits.append({"title": None, "url": url.rstrip(".,;:")})
    return hits[:limit * 3]


async def _search_responses(query, model, limit, provider, prompt, spend=None, model_id=None):
    tool = providers.PROVIDERS[provider]["search_tool"]
    response = await providers.CLIENTS[provider].responses.create(model=model, input=query, instructions=prompt, max_output_tokens=4096, tools=[{"type": tool}], tool_choice={"type": tool})
    if spend and response.usage:
        spend.add(model_id, providers.field(response.usage, "input_tokens") or 0, providers.field(response.usage, "output_tokens") or 0, search_requests=1)
    return _responses_hits(response, limit)


def _hosted_finder(provider):
    entry = providers.PROVIDERS.get(provider)
    if not entry or not entry.get("search_tool"):
        return None
    return {"anthropic": _search_anthropic, "responses": _search_responses}.get(entry["dialect"])


async def note(question, page, model_id, spend=None, note_prompt=None):
    prompt = f"Research question: {question}\n\nSource: {page.get('title') or page['url']} ({page['url']})\n\n<document>\n{page['content']}\n</document>"
    text = await complete(model_id, note_prompt or PROMPTS["note"], prompt, max_tokens=NOTE_MAX_TOKENS, spend=spend)
    if not text or NOTHING in text[:80]:
        return None
    parsed = note_from_text(text)
    return parsed if parsed and parsed.relevant else None


async def _page(url, question, offset=0):
    return await app_fetch.fetch(url, topic=question, offset=offset)


async def _page_window(url, question, offset):
    """Read one further window of a page through the note stage's fetch_url tool."""
    tool = next((candidate for candidate in resolve_research_tools("note") if candidate.name == "fetch_url"), None)
    if tool is None:
        return None
    call = ToolCall(id=f"page-{offset}", name=tool.name, arguments={"url": url, "topic": question, "offset": offset})
    result = await execute_tool(tool, call)
    return None if result.error else json.loads(result.content)


def _dedupe_claims(claims):
    seen, unique = set(), []
    for claim in claims:
        key = (claim.text, claim.stance)
        if key not in seen:
            seen.add(key)
            unique.append(claim)
    return unique


async def _note_windows(question, url, page, note_model, spend, note_prompt):
    """Note one source, following the note model's requests for later windows of the same page."""
    gists, claims = [], []
    loop, page_deadline = asyncio.get_running_loop(), None
    for page_index in range(NOTE_MAX_PAGES):
        next_offset = page.get("nextOffset")
        hint = PAGE_HINT.replace("OFFSET", str(next_offset)) if next_offset is not None else ""
        note_obj = await _retry(lambda: note(question, page, note_model, spend=spend, note_prompt=note_prompt + hint))
        if note_obj is None:
            break
        if note_obj.gist:
            gists.append(note_obj.gist)
        claims.extend(note_obj.claims)
        if next_offset is None or note_obj.fetch_offset != next_offset or note_obj.fetch_offset == page.get("offset") or page_index + 1 == NOTE_MAX_PAGES:
            break
        page_deadline = page_deadline or loop.time() + app_fetch.FETCH_DEADLINE
        remaining = page_deadline - loop.time()
        if remaining <= 0:
            break
        try:
            window = await asyncio.wait_for(_page_window(url, question, note_obj.fetch_offset), remaining)
        except asyncio.TimeoutError:
            break
        if window is None:
            break
        page = window
    if not gists and not claims:
        return None
    return Note(gist=" ".join(gists), claims=_dedupe_claims(claims))


def _next_source_id(registry, evidence):
    ids = [source.get("id", "") for source in registry.values()]
    ids.extend(item.get("source_id", "") for item in evidence)
    numbers = [int(value[1:]) for value in ids if value.startswith("S") and value[1:].isdigit()]
    return f"S{max(numbers, default=0) + 1}"


async def reformulate_query(question, brief, model, spend=None):
    system = "You are a research query reformulation specialist. Given a research question and overall brief objective/scope, generate a JSON array containing 2 to 3 distinct, targeted, search-engine optimized query variations to find relevant information. Return ONLY a JSON array of strings. Do not include markdown code block formatting or any other text."
    prompt = f"Research Question: {question}\nOverall Brief Objective: {brief.get('objective')}\nScope: {brief.get('scope')}"
    try:
        response = await complete(model, system, prompt, max_tokens=300, spend=spend)
        variants = object_from_text(response)
        if isinstance(variants, list) and all(isinstance(v, str) for v in variants):
            queries = list(dict.fromkeys(v.strip() for v in variants if v.strip()))
            if queries:
                return queries[:3]
    except Exception:
        pass
    return [question]


def _triage_picks(payload, keep, count):
    """Extract 1-based candidate indices from a triage response, or None when unusable."""
    if isinstance(payload, dict):
        payload = next((value for value in payload.values() if isinstance(value, list)), None)
    if not isinstance(payload, list):
        return None
    picks = []
    for value in payload:
        try:
            index = int(value)
        except (TypeError, ValueError):
            return None
        if not 1 <= index <= count or index in picks:
            continue
        picks.append(index)
    return picks or None


async def _triage(sources, question, keep, spend):
    """Rank the scan set on the utility model and return the top `keep` candidates.

    Classification failure falls back to the search ranking rather than ending the task;
    a fatal provider error still propagates.
    """
    if len(sources) <= keep:
        return sources
    lines = []
    for index, source in enumerate(sources, 1):
        parts = [str(index), source.get("title") or "", str(source["url"])]
        if source.get("snippet"):
            parts.append(source["snippet"])
        lines.append(" | ".join(parts))
    system = (
        "You are a research triage assistant. Given a research question and numbered search-result "
        "candidates, select the candidates most likely to contain relevant, substantive information. "
        f"Return ONLY a JSON array of at most {keep} candidate numbers (1-based, most relevant first)."
    )
    prompt = f"Research question: {question}\n\nCandidates:\n" + "\n".join(lines)
    try:
        text = await complete(providers.DEFAULT_UTILITY_MODEL, system, prompt, max_tokens=TRIAGE_MAX_TOKENS, spend=spend)
        picks = _triage_picks(object_from_text(text), keep, len(sources))
    except asyncio.CancelledError:
        raise
    except Exception as error:
        if _fatal_provider(error):
            raise
        picks = None
    if not picks:
        return sources[:keep]
    chosen = [sources[index - 1] for index in picks[:keep]]
    chosen_ids = {id(source) for source in chosen}
    chosen.extend(source for source in sources if id(source) not in chosen_ids)
    return chosen[:keep]


async def _fetch_and_note(source_row, url, question, note_model, spend, note_prompt, semaphore):
    async with semaphore:
        try:
            try:
                page = await _retry(lambda: _page(url, question))
            except app_fetch.FetchPolicyError as error:
                return {"success": False, "source_id": source_row["id"], "url": url, "error": error, "type": "fetch"}
            except app_fetch.FetchError as error:
                return {"success": False, "source_id": source_row["id"], "url": url, "error": error, "type": "fetch"}

            final_url = canonicalize(str(page.get("url") or url))
            try:
                note_obj = await _note_windows(question, final_url, page, note_model, spend, note_prompt)
                return {
                    "success": True,
                    "source_id": source_row["id"],
                    "url": url,
                    "final_url": final_url,
                    "page": page,
                    "note": note_obj,
                }
            except Exception as error:
                if _fatal_provider(error):
                    raise
                return {"success": False, "source_id": source_row["id"], "url": url, "final_url": final_url, "error": error, "type": "note", "title": page.get("title") or source_row["title"]}
        except Exception as error:
            if _fatal_provider(error):
                raise
            return {"success": False, "source_id": source_row["id"], "url": url, "error": error, "type": "general"}


async def gather_task(task, brief, search_model, note_model, registry, evidence, seen_urls, limit=6, spend=None, emit=None, search_prompt=None, note_prompt=None, operations=None):
    """Run one frontier task and append source-backed evidence to the run registries."""
    question = task["question"]
    reformulations = []
    if operations is not None:
        reformulations_dict = operations.setdefault("reformulations", {})
        if question in reformulations_dict:
            reformulations = reformulations_dict[question]
    if not reformulations:
        reformulations = await reformulate_query(question, brief, search_model, spend=spend)
        if operations is not None:
            operations.setdefault("reformulations", {})[question] = reformulations

    sources = []
    search_error = None
    fatal_err = None
    scan_limit = limit * SCAN_MULTIPLIER
    for q in reformulations:
        try:
            hits = await search(q, search_model, limit=scan_limit, search_prompt=search_prompt or PROMPTS["search"], spend=spend)
            if hits:
                sources.extend(hits)
        except Exception as error:
            if _fatal_provider(error):
                fatal_err = error
                break
            search_error = error

    if fatal_err:
        raise fatal_err
    if not sources and search_error:
        if emit:
            emit("breaker", task_id=task["id"], branch="search", message=f"search failed: {search_error}")
        return {"task_id": task["id"], "evidence": [], "gaps": [f"search failed for {question}: {search_error}"]}

    sources = app_search.filter_hits(sources, scan_limit)
    scanned = len(sources)
    sources = await _triage(sources, question, limit, spend)
    if emit and sources:
        emit("triage", task_id=task["id"], scanned=scanned, selected=len(sources))
    rows = []

    # Pass 1: Serial deduplication and source id allocation
    reserved = []
    for source in sources:
        url = canonicalize(str(source["url"]))
        if url in registry:
            known = registry[url]
            known.setdefault("task_ids", []).append(task["id"])
            for item in evidence:
                if item["source_id"] == known["id"] and task["id"] not in item.setdefault("task_ids", []):
                    item["task_ids"].append(task["id"])
            if emit:
                emit("source_reused", task_id=task["id"], source_id=known["id"], url=url)
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        source_row = {"id": _next_source_id(registry, evidence), "url": url, "title": source.get("title") or url, "task_ids": [task["id"]]}
        registry[url] = source_row
        reserved.append((source_row, url))

    # Pass 2: Concurrent fetch and note under semaphore
    semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)
    tasks = [_fetch_and_note(source_row, url, question, note_model, spend, note_prompt or PROMPTS["note"], semaphore) for source_row, url in reserved]
    res_list = await asyncio.gather(*tasks)

    # Pass 3: Serial updates and evidence appending
    for source_row, url in reserved:
        res = next((r for r in res_list if r["source_id"] == source_row["id"]), None)
        if not res:
            continue

        if res["success"]:
            final_url = res["final_url"]
            page = res["page"]
            note_obj = res["note"]
            if final_url != url:
                known = registry.get(final_url)
                if known and known is not source_row:
                    registry.pop(url, None)
                    known.setdefault("task_ids", []).append(task["id"])
                    if emit:
                        emit("source_reused", task_id=task["id"], source_id=known["id"], url=final_url)
                    continue
                registry.pop(url, None)
                source_row["url"] = final_url
                registry[final_url] = source_row
                seen_urls.add(final_url)
            if note_obj and (note_obj.gist or note_obj.claims):
                record = {
                    "id": f"E{len(evidence) + 1}",
                    "source_id": source_row["id"],
                    "task_id": task["id"],
                    "task_ids": list(source_row["task_ids"]),
                    "question": question,
                    "excerpt": note_obj.gist,
                    "claims": [claim.model_dump() for claim in note_obj.claims],
                    "title": page.get("title") or source_row["title"],
                }
                evidence.append(record)
                rows.append(record)
            else:
                rows.append({"source_id": source_row["id"], "gap": "nothing relevant"})
            if emit:
                emit("source", task_id=task["id"], source_id=source_row["id"], url=final_url, evidence_id=rows[-1].get("id"))
        else:
            for key, value in list(registry.items()):
                if value is source_row:
                    registry.pop(key, None)
            error = res["error"]
            err_str = str(error)
            if emit:
                emit("source_failed", task_id=task["id"], source_id=source_row["id"], url=url, message=err_str)
                emit("breaker", task_id=task["id"], branch="fetch", url=url, message=err_str)
            rows.append({"url": url, "error": err_str, "source_id": source_row["id"]})

    return {"task_id": task["id"], "evidence": rows, "gaps": [] if rows else [f"no usable evidence for {question}"]}

