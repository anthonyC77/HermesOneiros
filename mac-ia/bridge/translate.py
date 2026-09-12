#!/usr/bin/env python3
"""Anthropic Messages <-> OpenAI chat-completions, as pure functions.

**Standard library only**, and no I/O anywhere in this file. Every function
here maps a dict to a dict, which is what makes the hard part -- the streaming
state machine -- testable without a server, a network, or a loaded model.

The two dialects agree on the idea and disagree on the shape:

===========================  ==========================================
Anthropic                    OpenAI
===========================  ==========================================
``system`` (its own field)   a leading ``{"role": "system"}`` message
``tools[].input_schema``     ``tools[].function.parameters``
``tool_use`` content block   ``assistant.tool_calls[]``
``tool_result`` block, in a  ``{"role": "tool", "tool_call_id": ...}``,
user message                 its own message
``stop_reason``              ``finish_reason``
===========================  ==========================================

Tool-call ids pass through untouched in both directions. That is what makes a
round trip work: the id the local model invents comes back as the client's
``tool_use_id`` and is handed straight back as ``tool_call_id``, so nothing has
to remember a mapping across requests.

Deliberately dropped, because the local runtime has no equivalent: ``thinking``,
``cache_control``, ``output_config``, ``metadata``. Dropping them is correct --
faking a response shape the model never produced would be worse than not
offering the feature.
"""

from __future__ import annotations

import json
import secrets
from typing import Any, Iterator

__all__ = [
    "to_openai_request",
    "to_anthropic_response",
    "StreamTranslator",
    "sse",
    "new_message_id",
]

#: Anthropic stop_reason <- OpenAI finish_reason.
_STOP_REASON = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "length": "max_tokens",
    "content_filter": "end_turn",
}


def new_message_id() -> str:
    return "msg_" + secrets.token_hex(12)


def sse(event: str, payload: dict[str, Any]) -> bytes:
    """One server-sent event, framed the way the Anthropic API frames them.

    Both the ``event:`` line and the ``data:`` line are required -- clients that
    dispatch on the event name see nothing at all if only ``data:`` is sent.
    """
    return f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n".encode("utf-8")


# --------------------------------------------------------------------------- #
# Request: Anthropic -> OpenAI
# --------------------------------------------------------------------------- #

def _text_of(content: Any) -> str:
    """Flatten Anthropic content to plain text, ignoring non-text blocks."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "".join(parts)


def _image_part(block: dict[str, Any]) -> dict[str, Any] | None:
    source = block.get("source") or {}
    kind = source.get("type")
    if kind == "base64":
        media = source.get("media_type", "image/png")
        data = source.get("data", "")
        return {"type": "image_url", "image_url": {"url": f"data:{media};base64,{data}"}}
    if kind == "url" and source.get("url"):
        return {"type": "image_url", "image_url": {"url": source["url"]}}
    return None


def _user_content(blocks: list[Any]) -> Any:
    """Build OpenAI user content, staying a plain string unless images force
    the array form. Plain strings are what every OpenAI-compatible runtime
    handles best; the array form is only worth reaching for when it carries
    something a string cannot."""
    text_parts: list[str] = []
    images: list[dict[str, Any]] = []
    for block in blocks:
        if isinstance(block, str):
            text_parts.append(block)
            continue
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text_parts.append(str(block.get("text", "")))
        elif block.get("type") == "image":
            part = _image_part(block)
            if part:
                images.append(part)
    text = "".join(text_parts)
    if not images:
        return text
    parts: list[dict[str, Any]] = []
    if text:
        parts.append({"type": "text", "text": text})
    parts.extend(images)
    return parts


def _tool_result_messages(blocks: list[Any]) -> list[dict[str, Any]]:
    """Turn ``tool_result`` blocks into standalone ``role: "tool"`` messages.

    OpenAI has no ``is_error`` flag, so an error is folded into the text. The
    model still needs to know the call failed -- silently returning the error
    body as if it were a normal result is how a model ends up confidently
    building on a failure.
    """
    messages = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        body = block.get("content")
        text = body if isinstance(body, str) else _text_of(body)
        if block.get("is_error"):
            text = f"Error: {text}"
        messages.append(
            {
                "role": "tool",
                "tool_call_id": str(block.get("tool_use_id", "")),
                "content": text,
            }
        )
    return messages


def _assistant_message(blocks: list[Any]) -> dict[str, Any]:
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in blocks:
        if isinstance(block, str):
            text_parts.append(block)
            continue
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            text_parts.append(str(block.get("text", "")))
        elif kind == "tool_use":
            tool_calls.append(
                {
                    "id": str(block.get("id", "")),
                    "type": "function",
                    "function": {
                        "name": str(block.get("name", "")),
                        "arguments": json.dumps(block.get("input") or {}),
                    },
                }
            )
        # thinking / redacted_thinking blocks are dropped on purpose.
    message: dict[str, Any] = {"role": "assistant"}
    text = "".join(text_parts)
    # An assistant turn that is only tool calls must carry content: null, not
    # "" -- some runtimes treat the empty string as a real (empty) answer and
    # stop instead of running the tools.
    message["content"] = text if text else None
    if tool_calls:
        message["tool_calls"] = tool_calls
    return message


def _tool_choice(choice: Any) -> Any:
    if not isinstance(choice, dict):
        return None
    kind = choice.get("type")
    if kind == "auto":
        return "auto"
    if kind == "any":
        return "required"
    if kind == "none":
        return "none"
    if kind == "tool" and choice.get("name"):
        return {"type": "function", "function": {"name": choice["name"]}}
    return None


def to_openai_request(body: dict[str, Any]) -> dict[str, Any]:
    """Translate an Anthropic ``/v1/messages`` body into an OpenAI one."""
    messages: list[dict[str, Any]] = []

    system = body.get("system")
    if system:
        text = system if isinstance(system, str) else _text_of(system)
        if text:
            messages.append({"role": "system", "content": text})

    for message in body.get("messages") or []:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")
        blocks = content if isinstance(content, list) else [content]

        if role == "assistant":
            messages.append(_assistant_message(blocks))
            continue

        # A user turn can hold tool results and ordinary text at once. The tool
        # results have to be emitted first and separately: OpenAI expects them
        # to follow the assistant turn that made the calls, with nothing in
        # between.
        tool_messages = _tool_result_messages(blocks)
        messages.extend(tool_messages)
        remaining = [
            b for b in blocks
            if not (isinstance(b, dict) and b.get("type") == "tool_result")
        ]
        if remaining:
            user_content = _user_content(remaining)
            if user_content:
                messages.append({"role": "user", "content": user_content})
        elif not tool_messages:
            # Preserve an empty user turn rather than silently dropping it and
            # leaving two assistant turns adjacent.
            messages.append({"role": "user", "content": ""})

    request: dict[str, Any] = {
        "model": body.get("model"),
        "messages": messages,
        "stream": bool(body.get("stream")),
    }
    if body.get("max_tokens") is not None:
        request["max_tokens"] = body["max_tokens"]
    for key in ("temperature", "top_p"):
        if body.get(key) is not None:
            request[key] = body[key]
    if body.get("stop_sequences"):
        request["stop"] = body["stop_sequences"]

    tools = body.get("tools")
    if tools:
        converted = []
        for tool in tools:
            if not isinstance(tool, dict) or not tool.get("name"):
                continue
            converted.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("input_schema")
                        or {"type": "object", "properties": {}},
                    },
                }
            )
        if converted:
            request["tools"] = converted
            choice = _tool_choice(body.get("tool_choice"))
            if choice is not None:
                request["tool_choice"] = choice

    if request["stream"]:
        # Ask for the trailing usage chunk. Runtimes that do not implement it
        # ignore the field, and the translator falls back to zeros.
        request["stream_options"] = {"include_usage": True}
    return request


# --------------------------------------------------------------------------- #
# Response: OpenAI -> Anthropic (non-streaming)
# --------------------------------------------------------------------------- #

def _usage(payload: dict[str, Any]) -> dict[str, int]:
    usage = payload.get("usage") or {}
    return {
        "input_tokens": int(usage.get("prompt_tokens") or 0),
        "output_tokens": int(usage.get("completion_tokens") or 0),
    }


def _parse_arguments(raw: Any) -> dict[str, Any]:
    """Tool arguments arrive as a JSON *string*. Malformed JSON becomes an
    explicit marker rather than an exception -- a bad tool call should reach
    the agent as a bad tool call, not take the whole request down."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"__unparsed_arguments__": str(raw)}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def to_anthropic_response(
    payload: dict[str, Any], model: str, message_id: str | None = None
) -> dict[str, Any]:
    """Translate a non-streaming OpenAI completion into an Anthropic message."""
    choices = payload.get("choices") or [{}]
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") or {}

    content: list[dict[str, Any]] = []
    text = message.get("content")
    if isinstance(text, str) and text:
        content.append({"type": "text", "text": text})
    for call in message.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        function = call.get("function") or {}
        content.append(
            {
                "type": "tool_use",
                "id": str(call.get("id") or f"toolu_{secrets.token_hex(8)}"),
                "name": str(function.get("name", "")),
                "input": _parse_arguments(function.get("arguments")),
            }
        )

    finish = choice.get("finish_reason")
    stop_reason = _STOP_REASON.get(str(finish), "end_turn")
    # A runtime that returns tool calls but forgets finish_reason is common
    # enough to be worth correcting here: the client branches on stop_reason,
    # and end_turn would end the agent loop with the calls unexecuted.
    if any(block["type"] == "tool_use" for block in content):
        stop_reason = "tool_use"

    return {
        "id": message_id or new_message_id(),
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": _usage(payload),
    }


# --------------------------------------------------------------------------- #
# Response: OpenAI -> Anthropic (streaming)
# --------------------------------------------------------------------------- #

class StreamTranslator:
    """Turn a stream of OpenAI chunks into Anthropic SSE events.

    This is where the real work of the bridge lives. The two protocols differ
    in a way that matters:

    * OpenAI streams **flat deltas** -- text and tool arguments arrive as
      fragments on one object, with no explicit begin/end.
    * Anthropic streams **framed blocks** -- every span of content is opened by
      ``content_block_start`` and closed by ``content_block_stop``, and the
      deltas in between must carry the right index.

    So the translator has to invent the framing OpenAI never sends: track which
    block is open, close it before opening another, and number them in order.
    A client that receives a ``content_block_delta`` for a block it was never
    told about will drop the content or fail outright.

    Usage::

        translator = StreamTranslator(model="qwen")
        for chunk in openai_chunks:
            for event in translator.feed(chunk):
                write(event)
        for event in translator.finish():
            write(event)

    ``finish()`` is not optional: an upstream that dies mid-answer produces no
    terminal chunk, and without it the client waits forever on a message that
    was never closed.
    """

    def __init__(self, model: str, message_id: str | None = None) -> None:
        self.model = model
        self.message_id = message_id or new_message_id()
        self._started = False
        self._finished = False
        self._index = -1
        #: "text" | "tool" | None -- what the currently open block is.
        self._open: str | None = None
        #: OpenAI tool-call index -> our block index, so fragments land right.
        self._tool_blocks: dict[int, int] = {}
        self._stop_reason: str | None = None
        self._usage = {"input_tokens": 0, "output_tokens": 0}
        self._saw_tool = False

    # -- framing helpers ---------------------------------------------------- #

    def _start_message(self) -> Iterator[bytes]:
        if self._started:
            return
        self._started = True
        yield sse(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": self.message_id,
                    "type": "message",
                    "role": "assistant",
                    "model": self.model,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": dict(self._usage),
                },
            },
        )

    def _close_block(self) -> Iterator[bytes]:
        if self._open is None:
            return
        yield sse("content_block_stop", {"type": "content_block_stop", "index": self._index})
        self._open = None

    def _open_text(self) -> Iterator[bytes]:
        yield from self._close_block()
        self._index += 1
        self._open = "text"
        yield sse(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": self._index,
                "content_block": {"type": "text", "text": ""},
            },
        )

    def _open_tool(self, call_index: int, call_id: str, name: str) -> Iterator[bytes]:
        yield from self._close_block()
        self._index += 1
        self._open = "tool"
        self._saw_tool = True
        self._tool_blocks[call_index] = self._index
        yield sse(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": self._index,
                "content_block": {
                    "type": "tool_use",
                    "id": call_id or f"toolu_{secrets.token_hex(8)}",
                    "name": name,
                    "input": {},
                },
            },
        )

    # -- the loop ----------------------------------------------------------- #

    def feed(self, chunk: dict[str, Any]) -> Iterator[bytes]:
        """Consume one OpenAI chunk, yield zero or more Anthropic events."""
        if self._finished:
            return

        usage = chunk.get("usage")
        if isinstance(usage, dict):
            # The trailing usage-only chunk carries no choices; record and move
            # on. It is emitted with message_delta at the end.
            self._usage = {
                "input_tokens": int(usage.get("prompt_tokens") or 0),
                "output_tokens": int(usage.get("completion_tokens") or 0),
            }

        choices = chunk.get("choices") or []
        if not choices:
            yield from self._start_message()
            return

        choice = choices[0] if isinstance(choices[0], dict) else {}
        delta = choice.get("delta") or {}

        yield from self._start_message()

        text = delta.get("content")
        if isinstance(text, str) and text:
            if self._open != "text":
                yield from self._open_text()
            yield sse(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": self._index,
                    "delta": {"type": "text_delta", "text": text},
                },
            )

        for call in delta.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            call_index = int(call.get("index") or 0)
            function = call.get("function") or {}
            name = function.get("name")

            # A call is "new" when we have never seen its index. Some runtimes
            # send id+name+full arguments in a single chunk; others dribble the
            # arguments across many. Both land here correctly.
            if call_index not in self._tool_blocks:
                yield from self._open_tool(call_index, str(call.get("id") or ""), str(name or ""))
            elif self._open != "tool" or self._tool_blocks[call_index] != self._index:
                # Interleaved or resumed after text: reopening would renumber
                # the block, so refuse rather than emit deltas against the
                # wrong index.
                continue

            arguments = function.get("arguments")
            if isinstance(arguments, str) and arguments:
                yield sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": self._index,
                        "delta": {"type": "input_json_delta", "partial_json": arguments},
                    },
                )

        finish = choice.get("finish_reason")
        if finish:
            self._stop_reason = _STOP_REASON.get(str(finish), "end_turn")

    def finish(self) -> Iterator[bytes]:
        """Close whatever is open and terminate the message. Idempotent."""
        if self._finished:
            return
        yield from self._start_message()
        yield from self._close_block()
        stop_reason = self._stop_reason or "end_turn"
        if self._saw_tool:
            stop_reason = "tool_use"
        self._finished = True
        yield sse(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": self._usage["output_tokens"]},
            },
        )
        yield sse("message_stop", {"type": "message_stop"})
