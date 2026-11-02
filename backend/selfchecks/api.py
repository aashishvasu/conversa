"""Selfcheck: python -m selfchecks.api"""

from pydantic import ValidationError

from api.chat import ChatRequest, ImageBlock, Msg, SystemParts, render_system
from api.research import (
    PREPARE_SYSTEM,
    PrepareRequest,
    ResearchRequest,
    parse_prepare_response,
)
from api.sse import sse

assert sse(text="a\nb") == 'data: {"text": "a\\nb"}\n\n'
image = Msg.model_validate({"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/webp", "data": "x"}}]})
image_block = image.content[0]
assert isinstance(image_block, ImageBlock) and image_block.source.media_type == "image/webp"
assert not ChatRequest(messages=[]).allow_tools
try:
    Msg.model_validate({"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/avif", "data": "x"}}]})
except ValidationError:
    pass
else:
    raise AssertionError("unsupported image formats are rejected")

assert "objective" in PREPARE_SYSTEM and "at most three" in PREPARE_SYSTEM
answer = parse_prepare_response('preface ```json {"action":"answer","brief":null} ```')
assert answer.action == "answer" and answer.brief is None
research = parse_prepare_response('{"action":"research","brief":{"objective":"Compare Project Orion databases","deliverable":"A recommendation","scope":["regulated launch"],"constraints":["cite current sources"],"questions":[{"question":"Which region?","reason":"changes compliance","default":"US"}]}}')
assert research.brief is not None
assert research.brief.objective == "Compare Project Orion databases"
assert research.brief.scope == ["regulated launch"]
request = ResearchRequest.model_validate({"id": "r1", "brief": {"objective": "x", "deliverable": "d", "scope": ["s"], "constraints": ["c"], "questions": []}, "answers": {"Which region?": "US"}, "models": {"search": "m", "note": "m", "report": "m"}})
assert request.answers == {"Which region?": "US"}
try:
    ResearchRequest.model_validate({"id": "r1", "goal": "x", "models": {"search": "m", "note": "m", "report": "m"}})
except ValidationError:
    pass
else:
    raise AssertionError("missing answers accepted")
try:
    ResearchRequest.model_validate({"id": "r1", "goal": "x", "answers": {}, "settings": {}, "models": {"search": "m", "note": "m", "report": "m"}})
except ValidationError:
    pass
else:
    raise AssertionError("redundant settings accepted")
for bad_models in ({"search": "m", "report": "m"}, {"search": "m", "note": "m", "report": ""}, {"search": "m", "note": "m", "report": "m", "extra": "m"}):
    try:
        ResearchRequest.model_validate({"id": "r1", "goal": "x", "answers": {}, "models": bad_models})
    except ValidationError:
        pass
    else:
        raise AssertionError("invalid research models accepted")
for bad_answers in ({"": "US"}, {"region": ""}, {"region": 1}):
    try:
        ResearchRequest.model_validate({"id": "r1", "goal": "x", "answers": bad_answers, "models": {"search": "m", "note": "m", "report": "m"}})
    except ValidationError:
        pass
    else:
        raise AssertionError("invalid answers accepted")
for bad_brief in (
    '{"action":"research","brief":{"objective":"x","deliverable":"x","scope":"launch","constraints":["x"],"questions":[]}}',
    '{"action":"research","brief":{"objective":"x","deliverable":"x","scope":["launch"],"constraints":[],"questions":[]}}',
):
    try:
        parse_prepare_response(bad_brief)
    except ValueError:
        pass
    else:
        raise AssertionError("string or empty brief lists accepted")
for malformed in ('not json', '{"action":"research","brief":null}', '{"action":"answer","brief":null,"extra":true}', '{"action":"research","brief":{"objective":"x","deliverable":"x","scope":"x","constraints":"x","questions":[{"question":"1","reason":"2","default":"3"},{"question":"4","reason":"5","default":"6"},{"question":"7","reason":"8","default":"9"},{"question":"10","reason":"11","default":"12"}]}}'):
    try:
        parse_prepare_response(malformed)
    except ValueError:
        pass
    else:
        raise AssertionError(f"invalid preparation response accepted: {malformed}")

# Checkpoint v1 to v2 migration asserts
from research.state import CHECKPOINT_VERSION, empty_state, validate_checkpoint
v1_checkpoint = {
    "version": 1,
    "revision": 3,
    "brief": {"objective": "x", "deliverable": "d", "scope": ["scope 1", "scope 2"], "constraints": ["c"], "questions": [], "answers": {}},
    "frontier": [{"id": "T1", "question": "q", "status": "pending", "attempts": 0}],
    "sources": {},
    "evidence": [],
    "gaps": [],
    "decisions": [],
    "breakers": [],
    "budgets": {"calls": 0, "sources": 0, "elapsed": 0.0, "no_progress": 0},
    "operations": {"queries": {}, "fetch_failures": {}, "completed": {}, "reformulations": {}},
}
migrated = validate_checkpoint(v1_checkpoint)
assert migrated["version"] == 2
assert migrated["theory"] == {"hypothesis": "", "confidence": "low", "supporting": [], "contradicting": [], "revised_at_wave": 0}
assert migrated["coverage"] == {"scope 1": [], "scope 2": []}

# Structured system prompt: object form validates and renders into tagged text.
structured = ChatRequest.model_validate({
    "messages": [],
    "system": {
        "instructions": "Be brief.",
        "docs": [{"name": "lore.md", "text": "Dragons."}],
        "summary": "Earlier.",
        "evidence": True,
        "runtime": {"timezone": "Asia/Kolkata", "locale": "en-GB", "use_memory": True, "use_recall": False, "use_cache": True, "enabled_tools": ["search_web"]},
    },
})
assert isinstance(structured.system, SystemParts)
rendered = render_system(structured.system, "claude-sonnet-5", ["search_web", "fetch_url"])
assert isinstance(rendered, list) and len(rendered) == 2
stable, volatile = rendered
assert stable.startswith("<runtime>") and stable.endswith("</docs>")
assert "model: claude-sonnet-5" in stable and "date: " in stable
assert "timezone: Asia/Kolkata" in stable and "locale: en-GB" in stable
assert "tools: search_web, fetch_url" in stable
assert "memory: on" in stable and "recall: off" in stable
assert "instructions: " in stable and "docs: " in stable and '<doc name="lore.md">' in stable
assert "<summary>" in volatile and "Earlier." in volatile
assert "untrusted data" in volatile
# Without evidence the artifact instruction is omitted.
no_evidence = render_system(SystemParts.model_validate({"instructions": "Be brief.", "runtime": {}}), "m", [])
assert isinstance(no_evidence, str) and "untrusted data" not in no_evidence
# The server tools argument is authoritative. Research prepare has no tool loop, so a
# client-supplied enabled_tools hint never renders a tools line.
research_hint = render_system(SystemParts.model_validate({"runtime": {"enabled_tools": ["search_web"]}}), "m", [])
assert isinstance(research_hint, str) and "tools:" not in research_hint
server_tools = render_system(SystemParts.model_validate({"runtime": {"enabled_tools": []}}), "m", ["search_web"])
assert isinstance(server_tools, str) and "tools: search_web" in server_tools
# Research preparation accepts the same structured system object.
prepared = PrepareRequest.model_validate({"messages": [], "system": {"instructions": "Be brief.", "runtime": {}}, "model": "m"})
assert isinstance(prepared.system, SystemParts)
# String and list forms pass through unchanged.
assert render_system("plain", "m", []) == "plain"
assert render_system(["a", "b"], "m", []) == ["a", "b"]
# Without use_cache the renderer returns one joined string.
joined = render_system(SystemParts.model_validate({"instructions": "Be brief.", "runtime": {}}), "m", [])
assert isinstance(joined, str) and "<instructions>" in joined and "<runtime>" in joined
# An unknown part key is rejected.
try:
    ChatRequest.model_validate({"messages": [], "system": {"unknown": "x", "runtime": {}}})
except ValidationError:
    pass
else:
    raise AssertionError("unknown system part accepted")
# Runtime is the one required key.
try:
    ChatRequest.model_validate({"messages": [], "system": {"instructions": "Be brief."}})
except ValidationError:
    pass
else:
    raise AssertionError("structured system without runtime accepted")
# The system-preview endpoint reuses the chat request contract: a structured system
# object plus top-level enabled_tools. The render path is identical to chat.
preview_req = ChatRequest.model_validate({
    "messages": [],
    "system": {"instructions": "Be brief.", "runtime": {}},
    "enabled_tools": ["search_web"],
})
assert isinstance(preview_req.system, SystemParts)
assert preview_req.enabled_tools == ["search_web"]

print("api selfcheck OK")
