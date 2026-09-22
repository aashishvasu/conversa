"""Deterministic search, fetch, and evidence extraction."""

import asyncio
import re

import providers
from providers import complete
from tools import fetch as app_fetch
from tools import search as app_search
from tools.fetch import canonicalize
from .prompts import PROMPTS

SEARCH_MAX_USES = 6
FETCH_CONCURRENCY = 6
NOTE_MAX_TOKENS = 1500
NOTHING = "NOTHING RELEVANT"


def _fatal_provider(error):
    text = str(error).lower()
    return any(word in text for word in ("unauthorized", "forbidden", "401", "403", "credit", "quota", "invalid model", "authentication", "api key"))


def _retryable(error):
    text = str(error).lower()
    if any(word in text for word in ("unauthorized", "forbidden", "401", "403", "credit", "quota", "invalid model", "authentication", "api key")):
        return False
    return any(word in text for word in ("timeout", "timed out", "rate", "429", "502", "503", "504", "connection", "temporarily"))


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
    return None if not text or NOTHING in text[:80] else text


async def _page(url, question):
    return await app_fetch.fetch(url, topic=question)


def _next_source_id(registry, evidence):
    ids = [source.get("id", "") for source in registry.values()]
    ids.extend(item.get("source_id", "") for item in evidence)
    numbers = [int(value[1:]) for value in ids if value.startswith("S") and value[1:].isdigit()]
    return f"S{max(numbers, default=0) + 1}"


async def gather_task(task, brief, search_model, note_model, registry, evidence, seen_urls, limit=6, spend=None, emit=None, search_prompt=None, note_prompt=None):
    """Run one frontier task and append source-backed evidence to the run registries."""
    question = task["question"]
    try:
        sources = await search(question, search_model, limit=limit, search_prompt=search_prompt or PROMPTS["search"], spend=spend)
    except Exception as error:
        if _fatal_provider(error):
            raise
        if emit:
            emit("breaker", task_id=task["id"], branch="search", message=f"search failed: {error}")
        return {"task_id": task["id"], "evidence": [], "leads": [], "gaps": [f"search failed for {question}: {error}"]}
    rows = []
    leads = [{"title": source.get("title"), "url": canonicalize(str(source["url"]))} for source in sources]
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
        try:
            page = await _retry(lambda: _page(url, question))
            final_url = canonicalize(str(page.get("url") or url))
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
            body = await _retry(lambda: note(question, page, note_model, spend=spend, note_prompt=note_prompt or PROMPTS["note"]))
            if body:
                record = {"id": f"E{len(evidence) + 1}", "source_id": source_row["id"], "task_id": task["id"], "task_ids": list(source_row["task_ids"]), "question": question, "excerpt": body, "note": body, "title": page.get("title") or source_row["title"]}
                evidence.append(record)
                rows.append(record)
            else:
                rows.append({"source_id": source_row["id"], "gap": "nothing relevant"})
            if emit:
                emit("source", task_id=task["id"], source_id=source_row["id"], url=final_url, evidence_id=rows[-1].get("id"))
        except Exception as error:
            for key, value in list(registry.items()):
                if value is source_row:
                    registry.pop(key, None)
            if _fatal_provider(error):
                raise
            if emit:
                emit("source_failed", task_id=task["id"], source_id=source_row["id"], url=url, message=str(error))
                emit("breaker", task_id=task["id"], branch="fetch", url=url, message=str(error))
            rows.append({"url": url, "error": str(error), "source_id": source_row["id"]})
    return {"task_id": task["id"], "evidence": rows, "leads": leads, "gaps": [] if rows else [f"no usable evidence for {question}"]}

