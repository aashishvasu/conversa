"""Selfcheck: python -m selfchecks.tool_runner"""

import asyncio
from contextlib import contextmanager

import providers.chat as chat
import providers.dialects as dialects
from tools import ConversaTool, ToolArguments, ToolCall, ToolFailed, ToolOutput, ToolRejected, ToolUnavailable


class Obj:
    def __init__(self, **values):
        self.__dict__.update(values)


class CountArguments(ToolArguments):
    count: int


executed = []


async def lookup(arguments: CountArguments):
    executed.append(arguments.count)
    return ToolOutput({"private": arguments.count}, {"source": "lookup", "count": arguments.count, "content": "private", "echo": f'{{"private":{arguments.count}}}'})


tool = ConversaTool("lookup", "Look up a count.", CountArguments, lookup)


class AnthropicStream:
    def __init__(self, events, message):
        self.events = events
        self.message = message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def __aiter__(self):
        return self._events()

    async def _events(self):
        for event in self.events:
            yield event

    async def get_final_message(self):
        return self.message


class AnthropicMessages:
    def __init__(self, streams):
        self.streams = iter(streams)
        self.requests = []

    def stream(self, **kwargs):
        self.requests.append(kwargs)
        return next(self.streams)


class AnthropicClient:
    def __init__(self, streams):
        self.messages = AnthropicMessages(streams)


class ResponsesClient:
    def __init__(self, streams):
        self.streams = iter(streams)
        self.requests = []
        self.responses = self

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        return next(self.streams)


class ResponseStream:
    def __init__(self, events):
        self.events = events

    def __aiter__(self):
        return self._events()

    async def _events(self):
        for event in self.events:
            yield event


class CompatibleCompletions:
    def __init__(self):
        self.requests = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        return ResponseStream([Obj(choices=[Obj(delta={"content": "compatible"})], usage=None), Obj(choices=[], usage=Obj(prompt_tokens=2, completion_tokens=1, prompt_tokens_details=None))])


class CompatibleClient:
    def __init__(self):
        self.chat = Obj(completions=CompatibleCompletions())


async def collect(events):
    return [event async for event in events]


def usage(input_tokens, output_tokens):
    return Obj(input_tokens=input_tokens, output_tokens=output_tokens, cache_read_input_tokens=0, cache_creation_input_tokens=0, server_tool_use=None)


@contextmanager
def mock_client(provider: str, client: object):
    original = dialects.CLIENTS[provider]
    dialects.CLIENTS[provider] = client
    try:
        yield client
    finally:
        dialects.CLIENTS[provider] = original


def anthropic_pair(first_content, second_text="done"):
    return AnthropicClient([
        AnthropicStream([], Obj(content=first_content, usage=usage(1, 1))),
        AnthropicStream([Obj(type="content_block_delta", delta=Obj(type="text_delta", text=second_text))], Obj(content=[], usage=usage(1, 1))),
    ])


async def check_anthropic() -> None:
    global executed
    executed = []
    first = Obj(content=[{"type": "tool_use", "id": "a-1", "name": "lookup", "input": {}}], usage=usage(3, 1))
    second = Obj(content=[{"type": "text", "text": "done"}], usage=usage(5, 2))
    client = AnthropicClient([
        AnthropicStream([
            Obj(type="content_block_start", index=0, content_block={"type": "tool_use", "id": "a-1", "name": "lookup", "input": {}}),
            Obj(type="content_block_delta", index=0, delta=Obj(type="input_json_delta", partial_json='{"count":2}')),
        ], first),
        AnthropicStream([Obj(type="content_block_delta", delta=Obj(type="text_delta", text="done"))], second),
    ])
    with mock_client("anthropic", client):
        frames = await collect(chat.stream_chat("anthropic", "claude-sonnet-5", [{"role": "user", "content": "go"}], None, 32, "", 1.0, [tool]))
    assert executed == [2], executed
    assert client.messages.requests[0]["tools"] == dialects.anthropic_tools([tool]), client.messages.requests[0]
    assert not any(item.get("type", "").startswith("web_") for item in client.messages.requests[0]["tools"]), client.messages.requests[0]
    result = client.messages.requests[1]["messages"][-1]["content"][0]
    assert result == {"type": "tool_result", "tool_use_id": "a-1", "content": '{"private":2}'}, result
    tool_frames = [frame["tool"] for frame in frames if "tool" in frame]
    assert tool_frames[-1] == {"id": "a-1", "name": "lookup", "status": "completed", "trace": {"source": "lookup", "count": 2, "echo": "[redacted]"}}, tool_frames
    assert "private" not in str(tool_frames), tool_frames
    assert {"text": "done"} in frames, frames
    assert frames[-2]["usage"] == {"model": "claude-sonnet-5", "calls": 2, "input": 8, "output": 3, "cache_read": 0, "cache_write": 0, "usd": 0.000046, "unpriced": 0}, frames[-2]
    assert frames[-1] == {"done": True}, frames[-1]


async def check_invalid_arguments_and_budget() -> None:
    global executed
    executed = []
    first = Obj(content=[{"type": "tool_use", "id": "bad", "name": "lookup", "input": {"count": "2"}}], usage=usage(1, 1))
    second = Obj(content=[], usage=usage(1, 1))
    client = AnthropicClient([AnthropicStream([], first), AnthropicStream([Obj(type="content_block_delta", delta=Obj(type="text_delta", text="recovered"))], second)])
    with mock_client("anthropic", client):
        frames = await collect(chat.stream_chat("anthropic", "claude-sonnet-5", [{"role": "user", "content": "go"}], None, 32, "", 1.0, [tool]))
    result = client.messages.requests[1]["messages"][-1]["content"][0]
    assert executed == [] and '"invalid_arguments"' in result["content"], (executed, result)
    assert client.messages.requests[1]["tools"] == dialects.anthropic_tools([tool]), client.messages.requests[1]
    assert [frame["tool"]["status"] for frame in frames if "tool" in frame] == ["running", "error"], frames

    executed = []
    calls = [
        {"type": "tool_use", "id": "one", "name": "lookup", "input": {"count": 1}},
        {"type": "tool_use", "id": "two", "name": "lookup", "input": {"count": 2}},
    ]
    client = AnthropicClient([AnthropicStream([], Obj(content=calls, usage=usage(1, 1))), AnthropicStream([Obj(type="content_block_delta", delta=Obj(type="text_delta", text="bounded"))], Obj(content=[], usage=usage(1, 1)))])
    with mock_client("anthropic", client):
        await collect(chat.stream_chat("anthropic", "claude-sonnet-5", [{"role": "user", "content": "go"}], None, 32, "", 1.0, [tool], max_tool_calls=1))
    outputs = client.messages.requests[1]["messages"][-1]["content"]
    assert executed == [1] and [output["tool_use_id"] for output in outputs] == ["one", "two"], (executed, outputs)
    assert "tool_call_limit" in outputs[1]["content"], outputs

    executed = []
    first = Obj(content=[{"type": "tool_use", "id": "round-one", "name": "lookup", "input": {"count": 1}}], usage=usage(1, 1))
    second = Obj(content=[{"type": "tool_use", "id": "round-two", "name": "lookup", "input": {"count": 2}}], usage=usage(1, 1))
    final = Obj(content=[{"type": "text", "text": "bounded"}], usage=usage(1, 1))
    client = AnthropicClient([
        AnthropicStream([], first),
        AnthropicStream([], second),
        AnthropicStream([Obj(type="content_block_delta", delta=Obj(type="text_delta", text="bounded"))], final),
    ])
    with mock_client("anthropic", client):
        frames = await collect(chat.stream_chat("anthropic", "claude-sonnet-5", [{"role": "user", "content": "go"}], None, 32, "", 1.0, [tool], max_tool_rounds=1))
    assert executed == [1] and len(client.messages.requests) == 3, (executed, client.messages.requests)
    limited = client.messages.requests[2]["messages"][-1]["content"][0]
    assert limited["is_error"] and "tool_round_limit" in limited["content"], limited
    assert any(frame.get("tool", {}).get("status") == "error" for frame in frames), frames
    assert {"text": "bounded"} in frames, frames


async def check_hosted_fallback() -> None:
    async def unavailable(_arguments: CountArguments):
        raise ToolUnavailable("app backend unavailable")

    search_tool = ConversaTool("search_web", "Search web.", CountArguments, unavailable)
    fetch_tool = ConversaTool("fetch_url", "Fetch url.", CountArguments, unavailable)

    # 1. Non-web tool unavailable does not enable hosted web tools
    non_web_tool = ConversaTool("lookup", "Look up a count.", CountArguments, unavailable)
    call = [{"type": "tool_use", "id": "missing", "name": "lookup", "input": {"count": 1}}]
    with mock_client("anthropic", anthropic_pair(call, "no hosted")) as client:
        frames = await collect(chat.stream_chat("anthropic", "claude-sonnet-5", [{"role": "user", "content": "go"}], None, 32, "", 1.0, [non_web_tool]))
    assert "tools" not in client.messages.requests[1], client.messages.requests[1]
    assert {"text": "no hosted"} in frames, frames

    # 2. search_web unavailable enables only hosted search (not hosted fetch)
    search_call = [{"type": "tool_use", "id": "s1", "name": "search_web", "input": {"count": 1}}]
    with mock_client("anthropic", anthropic_pair(search_call, "hosted")) as client:
        await collect(chat.stream_chat("anthropic", "claude-sonnet-5", [{"role": "user", "content": "go"}], None, 32, "", 1.0, [search_tool]))
    fallback_tools = client.messages.requests[1]["tools"]
    assert any(t.get("name") == "web_search" for t in fallback_tools), fallback_tools
    assert not any(t.get("name") == "web_fetch" for t in fallback_tools), fallback_tools

    # 3. Retain other selected app tools when search_web becomes unavailable
    with mock_client("anthropic", anthropic_pair(search_call, "retained")) as client:
        await collect(chat.stream_chat("anthropic", "claude-sonnet-5", [{"role": "user", "content": "go"}], None, 32, "", 1.0, [search_tool, tool]))
    round2_tools = client.messages.requests[1]["tools"]
    assert any(t.get("name") == "lookup" for t in round2_tools), round2_tools
    assert any(t.get("name") == "web_search" for t in round2_tools), round2_tools
    assert not any(t.get("name") == "search_web" for t in round2_tools), round2_tools

    # 4. fetch_url unavailable enables only hosted web_fetch, not web_search, retaining other local tool
    fetch_call = [{"type": "tool_use", "id": "f1", "name": "fetch_url", "input": {"count": 1}}]
    with mock_client("anthropic", anthropic_pair(fetch_call, "fetched")) as client:
        await collect(chat.stream_chat("anthropic", "claude-sonnet-5", [{"role": "user", "content": "go"}], None, 32, "", 1.0, [fetch_tool, tool]))
    round2_fetch = client.messages.requests[1]["tools"]
    assert any(t.get("name") == "lookup" for t in round2_fetch), round2_fetch
    assert any(t.get("name") == "web_fetch" for t in round2_fetch), round2_fetch
    assert not any(t.get("name") == "web_search" for t in round2_fetch), round2_fetch
    assert not any(t.get("name") == "fetch_url" for t in round2_fetch), round2_fetch

    # 5. Responses search_web unavailable enables hosted search entry, retains lookup, removes app search_web
    first_resp = Obj(
        output=[{"type": "function_call", "id": "item-s", "call_id": "rs-1", "name": "search_web", "arguments": '{"count":1}'}],
        usage={"input_tokens": 4, "output_tokens": 1, "input_tokens_details": None},
    )
    final_resp = Obj(output=[], usage={"input_tokens": 4, "output_tokens": 1, "input_tokens_details": None})
    resp_client = ResponsesClient([
        ResponseStream([Obj(type="response.completed", response=first_resp)]),
        ResponseStream([Obj(type="response.output_text.delta", delta="done"), Obj(type="response.completed", response=final_resp)]),
    ])
    with mock_client("openai", resp_client) as client:
        await collect(chat.stream_chat("openai", "gpt-5.6-sol", [{"role": "user", "content": "go"}], None, 32, "", 1.0, [search_tool, tool]))
    resp_round2 = client.requests[1]["tools"]
    assert any(t.get("type") == "function" and t.get("name") == "lookup" for t in resp_round2), resp_round2
    assert any(t.get("type") == "web_search" for t in resp_round2), resp_round2
    assert not any(t.get("name") == "search_web" for t in resp_round2), resp_round2


async def check_call_failure_keeps_tools() -> None:
    async def failed(_arguments: CountArguments):
        raise ToolFailed("request failed")

    failed_tool = ConversaTool("lookup", "Look up a count.", CountArguments, failed)
    call = [{"type": "tool_use", "id": "failed", "name": "lookup", "input": {"count": 1}}]
    with mock_client("anthropic", anthropic_pair(call, "recovered")) as client:
        frames = await collect(chat.stream_chat("anthropic", "claude-sonnet-5", [{"role": "user", "content": "go"}], None, 32, "", 1.0, [failed_tool]))
    assert client.messages.requests[1]["tools"] == dialects.anthropic_tools([failed_tool]), client.messages.requests[1]
    assert any((frame.get("tool", {}).get("trace") or {}).get("code") == "tool_error" for frame in frames), frames
    assert {"text": "recovered"} in frames, frames


async def check_policy_rejection_blocks_fallback() -> None:
    async def rejected_search(_arguments: CountArguments):
        raise ToolRejected("blocked query")

    search_tool = ConversaTool("search_web", "Search web.", CountArguments, rejected_search)
    calls = [{"type": "tool_use", "id": "blocked", "name": "search_web", "input": {"count": 1}}]
    with mock_client("anthropic", anthropic_pair(calls, "cannot search")) as client:
        frames = await collect(chat.stream_chat("anthropic", "claude-sonnet-5", [{"role": "user", "content": "go"}], None, 32, "", 1.0, [search_tool]))
    assert not any(t.get("name") == "web_search" for t in client.messages.requests[1].get("tools", [])), client.messages.requests[1]
    assert {"text": "cannot search"} in frames, frames


async def check_responses() -> None:
    global executed
    executed = []
    first_response = Obj(output=[{"type": "reasoning", "id": "reason-1", "encrypted_content": "state"}, {"type": "function_call", "id": "item-1", "call_id": "r-1", "name": "lookup", "arguments": ""}], usage={"input_tokens": 4, "output_tokens": 1, "input_tokens_details": {"cached_tokens": 1}})
    final_response = Obj(output=[], usage={"input_tokens": 6, "output_tokens": 2, "input_tokens_details": {"cached_tokens": 2}})
    client = ResponsesClient([
        ResponseStream([
            Obj(type="response.output_item.added", item={"type": "function_call", "id": "item-1", "call_id": "r-1", "name": "lookup", "arguments": ""}),
            Obj(type="response.function_call_arguments.delta", item_id="item-1", delta='{"count":3}'),
            Obj(type="response.completed", response=first_response),
        ]),
        ResponseStream([Obj(type="response.output_text.delta", delta="answer"), Obj(type="response.completed", response=final_response)]),
    ])
    with mock_client("openai", client):
        frames = await collect(chat.stream_chat("openai", "gpt-5.6-sol", [{"role": "user", "content": "go"}], None, 32, "", 1.0, [tool]))
    assert executed == [3], executed
    assert client.requests[0]["tools"] == dialects.responses_tools([tool]), client.requests[0]
    followup = client.requests[1]["input"]
    assert followup[-1] == {"type": "function_call_output", "call_id": "r-1", "output": '{"private":3}'}, followup
    assert any(item.get("type") == "reasoning" and item.get("encrypted_content") == "state" for item in followup), followup
    assert {"text": "answer"} in frames, frames
    assert frames[-2]["usage"] == {"model": "openai/gpt-5.6-sol", "calls": 2, "input": 10, "output": 3, "cache_read": 3, "cache_write": 0, "usd": 0.000101, "unpriced": 0}, frames[-2]


async def check_compatible_omits_tools() -> None:
    client = CompatibleClient()
    with mock_client("compatible", client):
        await collect(chat.stream_chat("compatible", "operator-model", [{"role": "user", "content": "go"}], None, 32, "", 1.0, [tool]))
    assert "tools" not in client.chat.completions.requests[0], client.chat.completions.requests[0]

    class NoUsageCompletions:
        async def create(self, **_kwargs):
            return ResponseStream([Obj(choices=[Obj(delta={"content": "text"})], usage=None)])

    no_usage_client = Obj(chat=Obj(completions=NoUsageCompletions()))
    with mock_client("compatible", no_usage_client):
        frames = await collect(chat.stream_chat("compatible", "operator-model", [{"role": "user", "content": "go"}], None, 32, "", 1.0, allow_hosted_tools=False))
    assert not any("usage" in frame for frame in frames), frames


async def main() -> None:
    await check_anthropic()
    await check_invalid_arguments_and_budget()
    await check_hosted_fallback()
    await check_call_failure_keeps_tools()
    await check_policy_rejection_blocks_fallback()
    await check_responses()
    await check_compatible_omits_tools()


asyncio.run(main())
print("tool runner selfcheck OK")
