#!/usr/bin/env python3
"""Bridge tests, in the shape of test_endpoint.py: stdlib only, numbered blocks.

Blocks 1-4 are pure translation and need nothing running -- no model, no
server, no network. Block 5 needs the whole stack and is skipped, not failed,
when it is not up.

That split is the point. A failure in 1-4 is a bug in this repository. A
failure in 5 with 1-4 green is a bug in the *environment* -- the runtime, the
model, the network -- and there is no reason to read the translation code.

    python3 tests/test_bridge.py            # blocks 1-4
    python3 tests/test_bridge.py --live     # also block 5
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bridge"))

from translate import (  # noqa: E402
    StreamTranslator,
    to_anthropic_response,
    to_openai_request,
)

BRIDGE = os.environ.get("MAC_IA_BRIDGE", "http://127.0.0.1:1235")

_failures: list[str] = []
_checks = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global _checks
    _checks += 1
    if condition:
        print(f"  [ OK ] {label}")
    else:
        print(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))
        _failures.append(label)


def parse_events(raw: list[bytes]) -> list[tuple[str, dict]]:
    """Decode the framed SSE bytes back into (event_name, payload) pairs."""
    events = []
    for blob in raw:
        text = blob.decode("utf-8")
        name = ""
        payload = {}
        for line in text.strip().splitlines():
            if line.startswith("event: "):
                name = line[7:].strip()
            elif line.startswith("data: "):
                payload = json.loads(line[6:])
        events.append((name, payload))
    return events


def run(translator: StreamTranslator, chunks: list[dict]) -> list[tuple[str, dict]]:
    raw: list[bytes] = []
    for chunk in chunks:
        raw.extend(translator.feed(chunk))
    raw.extend(translator.finish())
    return parse_events(raw)


# --------------------------------------------------------------------------- #

def block1_request() -> None:
    print("\n[1/5] Request translation  (Anthropic -> OpenAI)")

    out = to_openai_request(
        {
            "model": "m",
            "max_tokens": 100,
            "system": "You are terse.",
            "messages": [{"role": "user", "content": "hi"}],
        }
    )
    check("system becomes a leading system message",
          out["messages"][0] == {"role": "system", "content": "You are terse."},
          str(out["messages"][:1]))
    check("max_tokens carried over", out.get("max_tokens") == 100)

    out = to_openai_request(
        {
            "model": "m",
            "system": [{"type": "text", "text": "A"}, {"type": "text", "text": "B"}],
            "messages": [{"role": "user", "content": "hi"}],
        }
    )
    check("system given as blocks is flattened",
          out["messages"][0]["content"] == "AB", str(out["messages"][0]))

    out = to_openai_request(
        {
            "model": "m",
            "messages": [{"role": "user", "content": "weather?"}],
            "tools": [
                {
                    "name": "get_weather",
                    "description": "Get weather",
                    "input_schema": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"],
                    },
                }
            ],
            "tool_choice": {"type": "any"},
        }
    )
    function = out["tools"][0]["function"]
    check("tool becomes type=function", out["tools"][0]["type"] == "function")
    check("tool name preserved", function["name"] == "get_weather")
    check("input_schema becomes parameters verbatim",
          function["parameters"]["required"] == ["city"], str(function["parameters"]))
    check("tool_choice any -> required", out.get("tool_choice") == "required",
          str(out.get("tool_choice")))

    # The round trip that matters: assistant makes a call, user returns
    # its result, and the ids have to line up on the way out.
    out = to_openai_request(
        {
            "model": "m",
            "messages": [
                {"role": "user", "content": "weather?"},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "checking"},
                        {"type": "tool_use", "id": "call_1", "name": "get_weather",
                         "input": {"city": "Paris"}},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "call_1", "content": "12C"},
                        {"type": "text", "text": "and tomorrow?"},
                    ],
                },
            ],
        }
    )
    roles = [m["role"] for m in out["messages"]]
    check("roles ordered user, assistant, tool, user",
          roles == ["user", "assistant", "tool", "user"], str(roles))
    assistant = out["messages"][1]
    check("tool_use becomes tool_calls", bool(assistant.get("tool_calls")))
    check("tool arguments serialised to a JSON string",
          json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"city": "Paris"},
          str(assistant["tool_calls"][0]["function"]["arguments"]))
    check("tool_use_id becomes tool_call_id unchanged",
          out["messages"][2]["tool_call_id"] == "call_1", str(out["messages"][2]))
    check("tool result precedes the trailing user text",
          out["messages"][2]["role"] == "tool" and out["messages"][3]["role"] == "user")

    out = to_openai_request(
        {
            "model": "m",
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "c", "name": "f", "input": {}}],
                }
            ],
        }
    )
    check("tool-only assistant turn has content=None, not an empty string",
          out["messages"][0]["content"] is None, str(out["messages"][0]))

    out = to_openai_request(
        {
            "model": "m",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "what is this"},
                    {"type": "image", "source": {"type": "base64",
                                                 "media_type": "image/png", "data": "AAA"}},
                ],
            }],
        }
    )
    parts = out["messages"][0]["content"]
    check("image becomes an image_url data URI",
          isinstance(parts, list)
          and parts[1]["image_url"]["url"] == "data:image/png;base64,AAA", str(parts))

    out = to_openai_request({"model": "m", "messages": [], "thinking": {"type": "adaptive"},
                             "output_config": {"effort": "high"}})
    check("thinking / output_config are dropped, not forwarded",
          "thinking" not in out and "output_config" not in out, str(sorted(out)))


def block2_response() -> None:
    print("\n[2/5] Response translation  (OpenAI -> Anthropic, non-streaming)")

    out = to_anthropic_response(
        {"choices": [{"message": {"role": "assistant", "content": "Hello"},
                      "finish_reason": "stop"}],
         "usage": {"prompt_tokens": 10, "completion_tokens": 2}},
        "m",
    )
    check("text becomes one text block",
          out["content"] == [{"type": "text", "text": "Hello"}], str(out["content"]))
    check("stop -> end_turn", out["stop_reason"] == "end_turn")
    check("usage remapped", out["usage"] == {"input_tokens": 10, "output_tokens": 2},
          str(out["usage"]))
    check("id looks like an Anthropic message id", out["id"].startswith("msg_"))

    out = to_anthropic_response(
        {"choices": [{"message": {"tool_calls": [
            {"id": "call_9", "type": "function",
             "function": {"name": "get_weather", "arguments": '{"city":"Lyon"}'}}]},
            "finish_reason": "tool_calls"}]},
        "m",
    )
    block = out["content"][0]
    check("tool_calls become a tool_use block", block["type"] == "tool_use")
    check("tool id preserved for the round trip", block["id"] == "call_9")
    check("tool name exact", block["name"] == "get_weather")
    check("arguments parsed into a dict", block["input"] == {"city": "Lyon"}, str(block["input"]))
    check("tool_calls -> tool_use", out["stop_reason"] == "tool_use")

    # A runtime that returns calls but forgets finish_reason is common, and
    # end_turn there would end the agent loop with the calls never executed.
    out = to_anthropic_response(
        {"choices": [{"message": {"tool_calls": [
            {"id": "c", "function": {"name": "f", "arguments": "{}"}}]}}]},
        "m",
    )
    check("tool calls force tool_use even with finish_reason missing",
          out["stop_reason"] == "tool_use", out["stop_reason"])

    out = to_anthropic_response(
        {"choices": [{"message": {"tool_calls": [
            {"id": "c", "function": {"name": "f", "arguments": "{not json"}}]},
            "finish_reason": "tool_calls"}]},
        "m",
    )
    check("malformed arguments surface as a marker, they do not raise",
          "__unparsed_arguments__" in out["content"][0]["input"], str(out["content"][0]["input"]))

    out = to_anthropic_response(
        {"choices": [{"message": {"content": "cut"}, "finish_reason": "length"}]}, "m")
    check("length -> max_tokens", out["stop_reason"] == "max_tokens")


def block3_stream_text() -> None:
    print("\n[3/5] Streaming, text  (the framing OpenAI never sends)")

    events = run(
        StreamTranslator("m"),
        [
            {"choices": [{"delta": {"role": "assistant"}}]},
            {"choices": [{"delta": {"content": "Hel"}}]},
            {"choices": [{"delta": {"content": "lo"}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        ],
    )
    names = [name for name, _ in events]
    check("opens with message_start", names[0] == "message_start", str(names[:1]))
    check("ends message_delta then message_stop",
          names[-2:] == ["message_delta", "message_stop"], str(names[-2:]))
    check("exactly one content_block_start",
          names.count("content_block_start") == 1, str(names))
    check("every opened block is closed",
          names.count("content_block_start") == names.count("content_block_stop"), str(names))

    text = "".join(
        payload["delta"]["text"] for name, payload in events
        if name == "content_block_delta" and payload["delta"]["type"] == "text_delta"
    )
    check("deltas reassemble to the original text", text == "Hello", repr(text))
    check("stop_reason end_turn",
          events[-2][1]["delta"]["stop_reason"] == "end_turn")

    # A truncated upstream produces no terminal chunk. finish() must still
    # close the message, or the client waits on it forever.
    translator = StreamTranslator("m")
    raw = list(translator.feed({"choices": [{"delta": {"content": "partial"}}]}))
    raw.extend(translator.finish())
    names = [name for name, _ in parse_events(raw)]
    check("an interrupted stream is still closed properly",
          names[-2:] == ["message_delta", "message_stop"]
          and "content_block_stop" in names, str(names))

    translator = StreamTranslator("m")
    list(translator.feed({"choices": [{"delta": {"content": "x"}, "finish_reason": "stop"}]}))
    first = list(translator.finish())
    second = list(translator.finish())
    check("finish() is idempotent", second == [], f"{len(second)} extra events")
    check("first finish() emitted the terminators", len(first) >= 2)


def block4_stream_tools() -> None:
    print("\n[4/5] Streaming, tool calls  (fragmented arguments)")

    events = run(
        StreamTranslator("m"),
        [
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_1", "type": "function",
                 "function": {"name": "get_weather", "arguments": ""}}]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": '{"ci'}}]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": 'ty":"Paris"}'}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        ],
    )
    starts = [p for n, p in events if n == "content_block_start"]
    check("one tool block opened", len(starts) == 1, str(len(starts)))
    check("block declared as tool_use", starts and starts[0]["content_block"]["type"] == "tool_use")
    check("tool id preserved", starts and starts[0]["content_block"]["id"] == "call_1")
    check("tool name preserved", starts and starts[0]["content_block"]["name"] == "get_weather")

    partial = "".join(
        p["delta"]["partial_json"] for n, p in events
        if n == "content_block_delta" and p["delta"]["type"] == "input_json_delta"
    )
    check("fragments concatenate to valid JSON",
          json.loads(partial) == {"city": "Paris"}, repr(partial))
    check("stop_reason tool_use", events[-2][1]["delta"]["stop_reason"] == "tool_use")

    # Some runtimes send id, name and the whole argument string in one chunk.
    events = run(
        StreamTranslator("m"),
        [{"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "c", "type": "function",
             "function": {"name": "f", "arguments": '{"a":1}'}}]},
            "finish_reason": "tool_calls"}]}],
    )
    partial = "".join(
        p["delta"]["partial_json"] for n, p in events
        if n == "content_block_delta" and p["delta"]["type"] == "input_json_delta"
    )
    check("a single-chunk tool call works too", json.loads(partial) == {"a": 1}, repr(partial))

    # Text first, then a call: two blocks, and the indices must not collide.
    events = run(
        StreamTranslator("m"),
        [
            {"choices": [{"delta": {"content": "let me check"}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "c", "type": "function",
                 "function": {"name": "f", "arguments": "{}"}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        ],
    )
    names = [n for n, _ in events]
    check("text then tool opens two blocks",
          names.count("content_block_start") == 2, str(names))
    check("both blocks closed",
          names.count("content_block_stop") == 2, str(names))
    indices = [p["index"] for n, p in events if n == "content_block_start"]
    check("blocks numbered 0 then 1", indices == [0, 1], str(indices))

    # Two calls in one turn -- parallel tool use.
    events = run(
        StreamTranslator("m"),
        [
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "a", "function": {"name": "f", "arguments": "{}"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 1, "id": "b", "function": {"name": "g", "arguments": "{}"}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        ],
    )
    ids = [p["content_block"]["id"] for n, p in events if n == "content_block_start"]
    check("two parallel calls become two blocks", ids == ["a", "b"], str(ids))
    names = [n for n, _ in events]
    check("both parallel blocks closed",
          names.count("content_block_start") == names.count("content_block_stop"), str(names))


def block5_live() -> None:
    print(f"\n[5/5] Live round trip against {BRIDGE}")
    payload = {
        "model": "local",
        "max_tokens": 256,
        "messages": [{"role": "user", "content": "What is the weather in Paris? Use the tool."}],
        "tools": [{
            "name": "get_weather",
            "description": "Get the current weather for a city.",
            "input_schema": {
                "type": "object",
                "properties": {"city": {"type": "string", "description": "City name"}},
                "required": ["city"],
            },
        }],
    }
    request = urllib.request.Request(
        f"{BRIDGE}/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        print(f"  [SKIP] bridge unreachable ({exc}).")
        print("         Start it with:  python3 bridge/server.py")
        return

    blocks = [b for b in body.get("content", []) if b.get("type") == "tool_use"]
    check("non-streaming: response carries a tool_use block", bool(blocks),
          json.dumps(body)[:300])
    if blocks:
        check("non-streaming: tool name exact", blocks[0]["name"] == "get_weather",
              blocks[0]["name"])
        check("non-streaming: arguments are a dict", isinstance(blocks[0]["input"], dict))
        check("non-streaming: schema honoured, 'city' present",
              "city" in blocks[0]["input"], str(blocks[0]["input"]))
    check("non-streaming: stop_reason is tool_use", body.get("stop_reason") == "tool_use",
          str(body.get("stop_reason")))

    # Streaming is the half that actually carries the risk: the framing is
    # invented by the bridge, so a client can only see it end to end.
    payload["stream"] = True
    request = urllib.request.Request(
        f"{BRIDGE}/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            lines = [line.decode("utf-8", "replace").rstrip("\n") for line in response]
    except urllib.error.URLError as exc:
        check("streaming: request completed", False, str(exc))
        return

    names, payloads = [], []
    for line in lines:
        if line.startswith("event: "):
            names.append(line[7:].strip())
        elif line.startswith("data: "):
            try:
                payloads.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass

    check("streaming: opens with message_start", names[:1] == ["message_start"], str(names[:3]))
    check("streaming: ends with message_stop", names[-1:] == ["message_stop"], str(names[-3:]))
    check("streaming: every block opened is closed",
          names.count("content_block_start") == names.count("content_block_stop"), str(names))

    opened = [p for p in payloads if p.get("type") == "content_block_start"]
    tools = [p for p in opened if p["content_block"]["type"] == "tool_use"]
    check("streaming: a tool_use block is opened", bool(tools), str(names))
    if tools:
        check("streaming: tool name exact",
              tools[0]["content_block"]["name"] == "get_weather",
              tools[0]["content_block"]["name"])
        fragments = "".join(
            p["delta"]["partial_json"] for p in payloads
            if p.get("type") == "content_block_delta"
            and p["delta"].get("type") == "input_json_delta"
        )
        try:
            parsed = json.loads(fragments)
            ok, detail = isinstance(parsed, dict) and "city" in parsed, str(parsed)
        except json.JSONDecodeError as exc:
            ok, detail = False, f"{exc}: {fragments!r}"
        check("streaming: fragments rebuild valid JSON honouring the schema", ok, detail)

    deltas = [p for p in payloads if p.get("type") == "message_delta"]
    check("streaming: stop_reason is tool_use",
          bool(deltas) and deltas[-1]["delta"]["stop_reason"] == "tool_use",
          str(deltas[-1:]))


def main() -> int:
    print("Bridge translation tests -- stdlib only, no model required for 1-4.")
    block1_request()
    block2_response()
    block3_stream_text()
    block4_stream_tools()
    if "--live" in sys.argv:
        block5_live()
    else:
        print("\n[5/5] Live round trip -- skipped (pass --live to run it)")

    print(f"\n{_checks - len(_failures)}/{_checks} checks passed")
    if _failures:
        print("\nFailed:")
        for name in _failures:
            print(f"  - {name}")
        print("\nBlocks 1-4 are pure translation: a failure here is a bug in")
        print("bridge/translate.py, and there is no reason to look at the")
        print("network, the runtime or the model.")
        return 1
    print("Translation is sound. If a real agent still misbehaves, the problem")
    print("is upstream of the bridge -- model, context length, or KV quantisation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
