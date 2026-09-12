#!/usr/bin/env python3
"""The second brain, exposed to an agent over MCP -- behind the contract.

**Standard library only, and it imports nothing from `index.py`.** The harness
launches MCP servers as bare subprocesses and picks its own interpreter; there
is no guarantee it resolves the one this repository lives under. A server that
only works when the stars align fails silently and intermittently, which is
worse than one that does not exist. So the database is opened directly, and the
FTS5 query translation is duplicated from `index.py`. That duplication is the
price of the guarantee -- if either changes, both change in the same commit.

`contract.py` is the one exception: it sits beside this file and is loaded by
path, never by package import, for the same reason. It is not optional. Every
answer leaves through `rendre()`; nothing here writes to stdout directly with
corpus text in it.

The database is opened **read-only**. An agent that can search cannot ingest,
cannot delete, and cannot corrupt the index -- enforced by the connection URI,
not by reviewing the SQL.

Protocol: newline-delimited JSON-RPC 2.0 on stdin/stdout, hand-rolled. The
surface an MCP server needs is four methods wide.

Register it **by file path**, never with `-m`:

    {"mcpServers": {"second-brain": {
        "command": "python3",
        "args": ["/Users/anthonychassier/mac-ia/brain/mcp_server.py"]}}}
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

SERVER_NAME = "second-brain"
SERVER_VERSION = "0.1.0"
#: Fallback when the client does not state one; otherwise we echo theirs.
DEFAULT_PROTOCOL = "2025-06-18"


# --------------------------------------------------------------------------- #
# The contract, loaded by path
# --------------------------------------------------------------------------- #

def _charger_contrat():
    """Load contract.py from beside this file.

    By path rather than by import: this process has no package context and no
    guarantee about `sys.path`. Failing here is fatal on purpose -- a server
    that starts without its contract would answer without a cap, which is the
    exact failure the contract exists to prevent.
    """
    chemin = Path(__file__).resolve().parent / "contract.py"
    spec = importlib.util.spec_from_file_location("brain_contract", chemin)
    if spec is None or spec.loader is None:
        raise RuntimeError("contract.py introuvable a cote de mcp_server.py")
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: @dataclass resolves its own module through
    # sys.modules, and a module loaded by path is not there unless we put it
    # there. Without this the contract fails to load at all.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


contrat = _charger_contrat()


# --------------------------------------------------------------------------- #
# Duplicated from index.py -- keep in sync
# --------------------------------------------------------------------------- #

_TOKEN = re.compile(r"[^\W_]+(?:[.\-_][^\W_]+)*", re.UNICODE)
_PREFIXE_MIN = 3


def build_match(requete: str, prefixe: bool = True) -> str | None:
    tokens = _TOKEN.findall(requete or "")
    if not tokens:
        return None
    quotes = ['"%s"' % t for t in tokens]
    if prefixe and len(tokens[-1]) >= _PREFIXE_MIN:
        quotes[-1] = quotes[-1] + "*"
    return " AND ".join(quotes)


def chemin_base() -> Path:
    brut = os.environ.get("BRAIN_DB", "").strip()
    if brut:
        return Path(brut).expanduser()
    return Path.home() / ".mac-ia" / "brain.db"


def racine_vault() -> Path | None:
    brut = os.environ.get("BRAIN_VAULT", "").strip()
    return Path(brut).expanduser() if brut else None


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #

def _connecter() -> sqlite3.Connection | None:
    base = chemin_base()
    if not base.exists():
        return None
    try:
        # Read-only, enforced by the driver rather than by convention.
        conn = sqlite3.connect("file:%s?mode=ro" % base, uri=True)
    except sqlite3.Error:
        return None
    conn.row_factory = sqlite3.Row
    return conn


def _pas_d_index() -> str:
    return (
        "Aucun index. Le construire sur le Mac avec "
        "`python3 brain/index.py refresh`, puis rechercher a nouveau."
    )


def _relatif(chemin: str) -> str:
    """Show a path relative to the vault when possible.

    An absolute path leaks the account name and the tree layout into the
    conversation for no benefit -- the caller cannot open the file anyway.
    """
    racine = racine_vault()
    if racine is not None:
        try:
            return str(Path(chemin).relative_to(racine))
        except ValueError:
            pass
    return Path(chemin).name


def do_search(requete: str, limite: int | None = None) -> str:
    match = build_match(requete)
    if match is None:
        return "Cette requete ne contient aucun mot cherchable."

    conn = _connecter()
    if conn is None:
        return _pas_d_index()

    # The caller's limit is a request, never an instruction: it is clamped to
    # the contract before it reaches SQL. Asking for 500 yields MAX_RESULTATS.
    demande = limite if isinstance(limite, int) and limite > 0 else contrat.MAX_RESULTATS
    plafond = min(demande, contrat.MAX_RESULTATS)

    try:
        lignes = conn.execute(
            "SELECT chemin, section, "
            "       snippet(passages, 0, '', '', '...', 14) AS extrait "
            "FROM passages WHERE passages MATCH ? ORDER BY rank LIMIT ?",
            # One extra row, only to know whether the answer was capped. It is
            # counted, never rendered.
            (match, plafond + 1),
        ).fetchall()
        total_docs = conn.execute(
            "SELECT COUNT(DISTINCT chemin) AS n FROM passages WHERE passages MATCH ?",
            (match,),
        ).fetchone()["n"]
    except sqlite3.Error:
        # build_match should make this unreachable. An empty answer beats a
        # stack trace travelling back into the conversation.
        return "La recherche a echoue."
    finally:
        conn.close()

    passages = [
        contrat.Passage(
            chemin=_relatif(row["chemin"]),
            section=row["section"] or "",
            extrait=row["extrait"] or "",
        )
        for row in lignes
    ]
    return contrat.rendre(passages, total_docs or 0, requete)


def do_stats() -> str:
    """Aggregate counts only -- no path, no title, no text."""
    conn = _connecter()
    if conn is None:
        return _pas_d_index()
    try:
        f = conn.execute("SELECT COUNT(*) AS n FROM fichiers").fetchone()
        p = conn.execute("SELECT COUNT(*) AS n FROM passages").fetchone()
    except sqlite3.Error:
        return "Etat indisponible."
    finally:
        conn.close()
    return "%d passages indexes sur %d documents." % (p["n"] or 0, f["n"] or 0)


# --------------------------------------------------------------------------- #
# MCP surface
# --------------------------------------------------------------------------- #

TOOLS = [
    {
        "name": "search_brain",
        "description": (
            "Recherche plein texte dans les notes personnelles de l'utilisateur "
            "(second cerveau), sur sa machine. A utiliser quand la reponse est "
            "peut-etre deja dans ses notes : 'ai-je ecrit quelque chose sur X', "
            "'ou ai-je note Y'. Gratuit : aucun appel de modele. Renvoie des "
            "extraits courts et plafonnes, pas les documents -- pour lire un "
            "document en entier, l'utilisateur l'ouvre lui-meme."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Mots a chercher. Pas de syntaxe FTS5 : les "
                                   "operateurs sont pris au pied de la lettre.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Resultats souhaites. Plafonne a %d."
                                   % contrat.MAX_RESULTATS,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "brain_stats",
        "description": "Volume indexe : passages et documents. Aucun contenu.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _result(request_id: Any, payload: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id: Any, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _text(body: str) -> dict:
    return {"content": [{"type": "text", "text": body}]}


def handle(message: dict) -> dict | None:
    """Handle one JSON-RPC message. Returns None for notifications."""
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    # Notifications carry no id and expect no reply.
    if request_id is None:
        return None

    if method == "initialize":
        demande = params.get("protocolVersion")
        return _result(
            request_id,
            {
                "protocolVersion": demande if isinstance(demande, str) else DEFAULT_PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )

    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})

    if method == "tools/call":
        nom = params.get("name")
        args = params.get("arguments") or {}
        if nom == "search_brain":
            limite = args.get("limit")
            return _result(
                request_id,
                _text(
                    do_search(
                        str(args.get("query") or ""),
                        limite if isinstance(limite, int) else None,
                    )
                ),
            )
        if nom == "brain_stats":
            return _result(request_id, _text(do_stats()))
        return _error(request_id, -32602, "outil inconnu : %r" % nom)

    if method in ("ping", "shutdown"):
        return _result(request_id, {})

    return _error(request_id, -32601, "methode inconnue : %r" % method)


def main() -> int:
    for ligne in sys.stdin:
        ligne = ligne.strip()
        if not ligne:
            continue
        try:
            message = json.loads(ligne)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        try:
            reponse = handle(message)
        except Exception as exc:  # noqa: BLE001
            # A crashed server is a dead tool for the rest of the session, so
            # any unexpected failure becomes a JSON-RPC error and the loop
            # keeps running.
            reponse = _error(message.get("id"), -32603, str(exc))
        if reponse is not None:
            sys.stdout.write(json.dumps(reponse) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
