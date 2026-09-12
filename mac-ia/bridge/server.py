#!/usr/bin/env python3
"""An Anthropic-shaped front door onto an OpenAI-shaped local runtime.

**Standard library only.** The Mac this runs on has no default route
(LIAISON_HERMES_MAC.md 4.3), so a component with dependencies could not be
installed or repaired there without opening the machine back up. Everything the
bridge needs ships with Python.

    LM Studio          :1234   OpenAI      /v1/chat/completions
    this bridge        :1235   Anthropic   /v1/messages

Point a client at the bridge and it believes it is talking to the Claude API::

    ANTHROPIC_BASE_URL=http://192.168.1.50:1235

Two things it does not do, on purpose. It does not authenticate -- it sits on
the same trusted LAN as :1234 and inherits that posture rather than inventing a
different one. And it does not invent capabilities: ``thinking``,
``cache_control`` and ``output_config`` are dropped rather than emulated, so a
caller that depends on them sees them missing instead of seeing a plausible
fake.

Run it::

    python3 -m bridge.server
    MAC_IA_UPSTREAM=http://127.0.0.1:1234/v1 python3 bridge/server.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator

if __package__ in (None, ""):  # allow `python3 bridge/server.py`
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from translate import StreamTranslator, new_message_id, sse, to_anthropic_response, to_openai_request
else:
    from .translate import (
        StreamTranslator,
        new_message_id,
        sse,
        to_anthropic_response,
        to_openai_request,
    )

UPSTREAM = os.environ.get("MAC_IA_UPSTREAM", "http://127.0.0.1:1234/v1").rstrip("/")
HOST = os.environ.get("MAC_IA_BRIDGE_HOST", "0.0.0.0")
PORT = int(os.environ.get("MAC_IA_BRIDGE_PORT", "1235"))
#: A cold model load is ~20 s and a long generation far more; the read timeout
#: has to clear both or the bridge invents failures the runtime did not have.
UPSTREAM_TIMEOUT = float(os.environ.get("MAC_IA_TIMEOUT", "600"))
MAX_BODY = 64 * 1024 * 1024


def _error_body(message: str, kind: str = "api_error") -> dict[str, Any]:
    return {"type": "error", "error": {"type": kind, "message": message}}


def _post_upstream(path: str, payload: dict[str, Any]):
    request = urllib.request.Request(
        f"{UPSTREAM}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    return urllib.request.urlopen(request, timeout=UPSTREAM_TIMEOUT)


def _openai_chunks(response) -> Iterator[dict[str, Any]]:
    """Parse an OpenAI SSE body into chunk dicts.

    Only ``data:`` lines carry payload; comments, blank lines and any
    ``event:`` lines are noise here. A chunk that will not parse is skipped
    rather than fatal -- one malformed frame should cost one frame, not the
    whole answer.
    """
    for raw in response:
        line = raw.decode("utf-8", "replace").strip()
        if not line or not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            return
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            yield parsed


class Handler(BaseHTTPRequestHandler):
    server_version = "mac-ia-bridge/0.1"
    protocol_version = "HTTP/1.1"

    # -- plumbing ----------------------------------------------------------- #

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _open_stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        # Chunked is written by hand below. Under HTTP/1.1, a body with neither
        # Content-Length nor Transfer-Encoding leaves the client guessing where
        # the response ends, which shows up as a hang rather than an error.
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

    def _chunk(self, data: bytes) -> None:
        self.wfile.write(f"{len(data):X}\r\n".encode("ascii") + data + b"\r\n")
        self.wfile.flush()

    def _end_stream(self) -> None:
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def _read_body(self) -> dict[str, Any] | None:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    # -- routes ------------------------------------------------------------- #

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/health":
            self._json(200, {"ok": True, "upstream": UPSTREAM})
            return
        if path == "/v1/models":
            # Passed through unchanged: the two dialects agree on this shape,
            # and clients probe it to check the endpoint is alive.
            try:
                with urllib.request.urlopen(f"{UPSTREAM}/models", timeout=30) as response:
                    self._json(200, json.loads(response.read().decode("utf-8")))
            except Exception as exc:  # noqa: BLE001
                self._json(502, _error_body(f"upstream unreachable: {exc}"))
            return
        self._json(404, _error_body(f"no route for GET {path}", "not_found_error"))

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = self.path.split("?", 1)[0].rstrip("/")
        if path != "/v1/messages":
            self._json(404, _error_body(f"no route for POST {path}", "not_found_error"))
            return

        body = self._read_body()
        if body is None:
            self._json(400, _error_body("request body is not valid JSON", "invalid_request_error"))
            return

        model = str(body.get("model") or "")
        stream = bool(body.get("stream"))
        try:
            upstream_body = to_openai_request(body)
        except Exception as exc:  # noqa: BLE001
            self._json(400, _error_body(f"could not translate request: {exc}", "invalid_request_error"))
            return

        if stream:
            self._stream(upstream_body, model)
        else:
            self._once(upstream_body, model)

    # -- the two modes ------------------------------------------------------ #

    def _once(self, upstream_body: dict[str, Any], model: str) -> None:
        try:
            with _post_upstream("/chat/completions", upstream_body) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:1000]
            self._json(exc.code, _error_body(f"upstream {exc.code}: {detail}"))
            return
        except Exception as exc:  # noqa: BLE001
            self._json(502, _error_body(f"upstream failed: {exc}"))
            return
        self._json(200, to_anthropic_response(payload, model))

    def _stream(self, upstream_body: dict[str, Any], model: str) -> None:
        translator = StreamTranslator(model=model, message_id=new_message_id())
        try:
            response = _post_upstream("/chat/completions", upstream_body)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:1000]
            self._json(exc.code, _error_body(f"upstream {exc.code}: {detail}"))
            return
        except Exception as exc:  # noqa: BLE001
            self._json(502, _error_body(f"upstream failed: {exc}"))
            return

        # Headers are only sent once the upstream has accepted the request, so
        # an upstream failure can still be reported as a clean HTTP error
        # instead of an empty 200 the client has to interpret.
        self._open_stream()
        try:
            with response:
                for chunk in _openai_chunks(response):
                    for event in translator.feed(chunk):
                        self._chunk(event)
            for event in translator.finish():
                self._chunk(event)
        except (BrokenPipeError, ConnectionResetError):
            return  # client hung up; nothing to report to anyone
        except Exception as exc:  # noqa: BLE001
            # Mid-stream failure: close the message properly, then say what
            # happened. A client left waiting on an unterminated message hangs
            # instead of erroring, which is much harder to diagnose.
            try:
                for event in translator.finish():
                    self._chunk(event)
                self._chunk(sse("error", _error_body(f"stream interrupted: {exc}")))
            except Exception:  # noqa: BLE001
                pass
        finally:
            try:
                self._end_stream()
            except Exception:  # noqa: BLE001
                pass

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write(f"[bridge] {fmt % args}\n")


def main() -> int:
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    sys.stderr.write(
        f"[bridge] http://{HOST}:{PORT}/v1/messages  ->  {UPSTREAM}/chat/completions\n"
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\n[bridge] stopped\n")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
