#!/usr/bin/env python3
"""Model residency for LM Studio: one named profile at a time.

**Standard library only, and that is deliberate.** This runs on a Mac with no
default route (LIAISON_HERMES_MAC.md 4.3). A tool that needs `pip install` to be
repaired is useless on exactly the day it breaks.

Why this file exists at all
---------------------------
Switching models by hand is three commands, and getting them wrong is silent.
`lms load` does **not** reuse an instance that is already resident: it stacks a
second one, and the second gets the `…:2` suffix while the *first* keeps the
TTL. An hour later the TTL fires, the named instance disappears, and
`model.default` stops matching anything -- with nothing having been touched
(LIAISON_HERMES_MAC.md 4.5).

The published fix is to run `lms unload --all` first and then check `lms ps`.
This module does that, and adds one thing the documented procedure does not:
it passes an explicit ``--identifier``. The identifier stops being whatever the
catalogue happened to produce and becomes a name *we* choose, per profile. So
a config that says ``model.default: code`` keeps working across a re-download,
a re-quantisation, or a rename upstream.

Detection is kept anyway. Forcing the identifier makes the collision loud
instead of preventing it outright: if something is already holding the name,
LM Studio hands back ``code:2`` and :func:`switch` fails instead of returning a
success that decays an hour later.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

CONFIG_ENV = "MAC_IA_CONFIG"
#: `lms load` on a 17 GB model is ~6 s warm and ~20 s cold; 300 s is slack, not
#: an expectation. A load that actually takes 300 s has failed some other way.
LOAD_TIMEOUT = 300
QUICK_TIMEOUT = 30
#: LM Studio appends `:2`, `:3`… when an identifier is already taken.
_SUFFIXED = re.compile(r":\d+$")


class RouterError(RuntimeError):
    """Anything an operator needs to read, rather than a traceback."""


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

def config_path() -> Path:
    raw = os.environ.get(CONFIG_ENV, "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(__file__).resolve().parent / "profiles.json"


def load_config(path: Path | None = None) -> dict[str, Any]:
    target = path or config_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RouterError(f"config unreadable at {target}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RouterError(f"config is not valid JSON ({target}): {exc}") from exc
    if not isinstance(raw, dict) or not raw.get("profiles"):
        raise RouterError(f"config has no 'profiles' section ({target})")
    return raw


def _expand(cfg: dict[str, Any], key: str, default: str) -> Path:
    return Path(str(cfg.get(key) or default)).expanduser()


# --------------------------------------------------------------------------- #
# The `lms` CLI
# --------------------------------------------------------------------------- #

def find_lms(cfg: dict[str, Any]) -> str:
    """Locate the `lms` binary.

    Checked before anything else because the failure is otherwise reported as a
    load failure, which sends you looking at models instead of at PATH.
    """
    configured = str(cfg.get("lms_binary") or "lms")
    found = shutil.which(configured)
    if found:
        return found
    # LM Studio installs here but does not always put it on PATH.
    for candidate in (
        Path.home() / ".lmstudio" / "bin" / "lms",
        Path.home() / ".lmstudio" / "bin" / "lms.exe",
    ):
        if candidate.exists():
            return str(candidate)
    raise RouterError(
        f"`{configured}` not found on PATH nor under ~/.lmstudio/bin. "
        "Open LM Studio once, or set 'lms_binary' in profiles.json."
    )


def _run(lms: str, args: list[str], timeout: int) -> tuple[int, str, str]:
    try:
        # encoding is pinned rather than inherited: `lms` writes UTF-8 progress
        # bars, and on a Windows console the default (cp1252) raises inside the
        # reader thread. That failure does not propagate -- the call still looks
        # like it worked -- so it has to be prevented, not caught.
        proc = subprocess.run(
            [lms, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RouterError(f"`lms {' '.join(args)}` timed out after {timeout}s") from exc
    except OSError as exc:
        raise RouterError(f"could not run `{lms}`: {exc}") from exc
    return proc.returncode, proc.stdout, proc.stderr


def loaded(lms: str) -> list[dict[str, Any]]:
    """Resident instances, as `lms ps --json` reports them.

    Returns ``[]`` on unparseable output rather than raising: an empty list and
    a broken parse both mean "nothing usable is loaded", and :func:`switch`
    verifies the *post* state anyway.
    """
    code, out, err = _run(lms, ["ps", "--json"], QUICK_TIMEOUT)
    if code != 0:
        raise RouterError(f"`lms ps` failed: {(err or out).strip()}")
    try:
        parsed = json.loads(out or "[]")
    except json.JSONDecodeError:
        return []
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def instance_name(item: dict[str, Any]) -> str:
    """The name an API caller would put in `model`."""
    for key in ("identifier", "modelKey", "path"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return "<unknown>"


def unload_all(lms: str) -> None:
    code, out, err = _run(lms, ["unload", "--all"], QUICK_TIMEOUT)
    # Unloading when nothing is loaded is a no-op, and some builds report it as
    # a failure. Only a still-resident model is a real problem, and the caller
    # checks that.
    if code != 0 and "no models" not in (out + err).lower():
        raise RouterError(f"`lms unload --all` failed: {(err or out).strip()}")


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #

def read_state(cfg: dict[str, Any]) -> dict[str, Any]:
    path = _expand(cfg, "state_file", "~/.mac-ia/state.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_state(cfg: dict[str, Any], payload: dict[str, Any]) -> None:
    """Persist atomically. A half-written state file reads as no state, which
    is recoverable; a truncated one that parses is not."""
    path = _expand(cfg, "state_file", "~/.mac-ia/state.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def hermes_holds(cfg: dict[str, Any]) -> bool:
    """Whether something has claimed the `code` profile.

    Nothing creates this file yet -- it is the hook for when `hermes.cmd` is
    updated to touch it on start and remove it on exit. Until then this always
    returns False, and the guard is inert by construction rather than by
    accident.
    """
    return _expand(cfg, "hold_file", "~/.mac-ia/hermes.hold").exists()


# --------------------------------------------------------------------------- #
# Operations
# --------------------------------------------------------------------------- #

def status(cfg: dict[str, Any]) -> dict[str, Any]:
    lms = find_lms(cfg)
    instances = loaded(lms)
    names = [instance_name(item) for item in instances]
    recorded = read_state(cfg).get("profile")
    # The state file records intent; `lms ps` records reality. When they
    # disagree, reality wins and we say so rather than papering over it.
    active = None
    if recorded and recorded in cfg["profiles"]:
        expected = cfg["profiles"][recorded].get("identifier", recorded)
        if expected in names:
            active = recorded
    return {
        "profile": active,
        "recorded": recorded,
        "loaded": names,
        "instances": len(instances),
        "hermes_hold": hermes_holds(cfg),
        "stale": bool(recorded) and active is None,
    }


def switch(cfg: dict[str, Any], name: str, force: bool = False) -> dict[str, Any]:
    """Make `name` the only resident profile.

    Raises :class:`RouterError` on anything that would leave residency in a
    state the caller did not ask for -- including a successful-looking load
    that produced a suffixed identifier.
    """
    profiles = cfg["profiles"]
    if name not in profiles:
        raise RouterError(
            f"unknown profile {name!r}. Known: {', '.join(sorted(profiles))}"
        )

    current = status(cfg)
    if current["profile"] == "code" and name != "code" and hermes_holds(cfg) and not force:
        raise RouterError(
            "the `code` profile is held (Hermes is using it). Switching would "
            "return `model not found` to Hermes, not a network error. "
            "Release the hold file, or pass force."
        )

    spec = profiles[name]
    model_key = spec.get("model_key")
    if not model_key:
        raise RouterError(f"profile {name!r} has no 'model_key'")
    identifier = str(spec.get("identifier") or name)

    lms = find_lms(cfg)

    # Order matters and is the whole point: unload first, always. `lms load` on
    # top of a resident instance stacks rather than reuses (4.5).
    unload_all(lms)

    args = ["load", str(model_key), "-y", "--identifier", identifier]
    if spec.get("context_length"):
        args += ["--context-length", str(spec["context_length"])]
    if spec.get("ttl"):
        args += ["--ttl", str(spec["ttl"])]

    code, out, err = _run(lms, args, LOAD_TIMEOUT)
    if code != 0:
        raise RouterError(
            f"loading {model_key!r} failed: {(err or out).strip()}\n"
            "If the key is unknown, list the real ones with `lms ls --json` and "
            "fix 'model_key' in profiles.json."
        )

    names = [instance_name(item) for item in loaded(lms)]

    suffixed = [n for n in names if _SUFFIXED.search(n)]
    if suffixed:
        raise RouterError(
            f"a suffixed instance is resident: {suffixed}. Something else already "
            f"holds {identifier!r}. This is the double-instance trap (4.5) -- the "
            "suffixed copy has no TTL protection and the load has NOT succeeded."
        )
    if identifier not in names:
        raise RouterError(
            f"loaded, but {identifier!r} is not resident (found: {names or 'nothing'})."
        )
    if len(names) != 1:
        raise RouterError(f"expected exactly one instance, found {len(names)}: {names}")

    write_state(cfg, {"profile": name, "identifier": identifier, "model_key": model_key})
    return {"profile": name, "identifier": identifier, "loaded": names}


# --------------------------------------------------------------------------- #
# HTTP surface
# --------------------------------------------------------------------------- #

class Handler(BaseHTTPRequestHandler):
    """GET /health, GET /profile, POST /profile/<name>[?force=1]."""

    server_version = "mac-ia-router/0.1"
    config: dict[str, Any] = {}

    def _send(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/health":
            self._send(200, {"ok": True})
            return
        if path == "/profile":
            try:
                self._send(200, status(self.config))
            except RouterError as exc:
                self._send(503, {"error": str(exc)})
            return
        self._send(404, {"error": f"no route for GET {path}"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        raw_path, _, query = self.path.partition("?")
        path = raw_path.rstrip("/")
        if not path.startswith("/profile/"):
            self._send(404, {"error": f"no route for POST {path}"})
            return
        name = path[len("/profile/"):]
        force = "force=1" in query or "force=true" in query
        try:
            self._send(200, switch(self.config, name, force=force))
        except RouterError as exc:
            # 409 is the interesting one: the request was well formed and was
            # refused on purpose, which a client should not retry blindly.
            held = "held" in str(exc)
            self._send(409 if held else 400, {"error": str(exc)})

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write(f"[router] {self.address_string()} {fmt % args}\n")


def serve(cfg: dict[str, Any]) -> int:
    server_cfg = cfg.get("server") or {}
    host = str(server_cfg.get("host", "127.0.0.1"))
    port = int(server_cfg.get("port", 8080))
    Handler.config = cfg
    httpd = ThreadingHTTPServer((host, port), Handler)
    if host not in ("127.0.0.1", "localhost", "::1"):
        # Said out loud rather than left in a README: :1234 carries only tokens,
        # this port loads arbitrary models. It is a real, if small, escalation.
        sys.stderr.write(
            f"[router] WARNING bound to {host} -- this port can load any model in "
            "the catalogue. Prefer 127.0.0.1 reached over SSH.\n"
        )
    sys.stderr.write(f"[router] listening on http://{host}:{port}\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\n[router] stopped\n")
    finally:
        httpd.server_close()
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

USAGE = """usage: profiles.py <command>

  status              what is resident right now
  switch <profile>    make <profile> the only resident one
  serve               run the HTTP surface

Profiles come from profiles.json (override with MAC_IA_CONFIG).
"""


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args or args[0] in ("-h", "--help"):
        sys.stdout.write(USAGE)
        return 0

    try:
        cfg = load_config()
        command = args[0]
        if command == "status":
            state = status(cfg)
            print(json.dumps(state, indent=2, sort_keys=True))
            if state["stale"]:
                print(
                    "\nNote: the recorded profile is not resident. Something "
                    "unloaded it (a TTL, or LM Studio restarting).",
                    file=sys.stderr,
                )
            return 0
        if command == "switch":
            if len(args) < 2:
                raise RouterError("switch needs a profile name")
            result = switch(cfg, args[1], force="--force" in args)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if command == "serve":
            return serve(cfg)
        raise RouterError(f"unknown command {command!r}")
    except RouterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
