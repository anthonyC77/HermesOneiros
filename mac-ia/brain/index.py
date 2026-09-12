#!/usr/bin/env python3
"""Lexical index over the second brain: SQLite FTS5, no model, no GPU.

**Standard library only, and that is deliberate.** This runs on a Mac with no
default route (LIAISON_HERMES_MAC.md 4.3). A component that needs `pip install`
to be repaired is useless on exactly the day it breaks.

**Step 1 of four, and the order is the point** (plan 4.3): index, then the
return contract, then MCP, then the model -- never the reverse. This file
answers "where did I write about X" instantly, for free, and without
hallucinating. A model is only worth adding for what an index genuinely cannot
do: summarise, classify, reformulate. Many second-brain projects put a model
everywhere on day one and discover they made slow, expensive and vague
something `grep` already did well.

    python3 brain/index.py refresh
    python3 brain/index.py search "charge de travail"
    python3 brain/index.py stats

The entry sas is `raw/` -- arbitrated 6 September 2026, closing documentary
incoherence 1 of LIAISON_HERMES_MAC.md 9, which called it `Entree/` in one
place and `raw/` in another within a single file.
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# --------------------------------------------------------------------------- #
# Where the corpus lives
# --------------------------------------------------------------------------- #

#: Explicit override, checked first.
VAULT_ENV = "BRAIN_VAULT"

#: The architected location. Shared rather than per-user because the ACL
#: partitioning between the `hermes` and `opencode` accounts is only possible
#: outside a single user's home (CLOISONNEMENT.md).
VAULT_PREVU = Path("/Users/Shared/SecondBrain")

#: Where the corpus actually sits today. Kept as a fallback rather than
#: silently creating the architected path: an empty vault that resolves is
#: indistinguishable from a working one, and that is the failure this whole
#: repository keeps guarding against.
VAULT_ACTUEL = Path.home() / "Documents" / "second-brain"

#: The entry sas. Files land here; ingestion picks them up from the vault as a
#: whole, so this name matters for the LaunchDaemons, not for the search path.
SAS = "raw"

#: Extensions carrying text this index can read. Anything else is *reported*
#: as skipped rather than silently dropped -- a corpus of PDFs would otherwise
#: produce an empty index and no explanation.
EXTENSIONS = {
    ".md", ".markdown", ".txt", ".text", ".rst", ".org",
    ".json", ".yaml", ".yml", ".toml", ".csv", ".tsv",
}

#: Directories never worth indexing.
IGNORES = {".git", ".obsidian", "node_modules", "__pycache__", ".trash", ".DS_Store"}

#: Chunk target. Small enough that a hit points at a passage rather than a
#: whole document, large enough that a sentence keeps its context.
TAILLE_CHUNK = 1500


def resoudre_vault() -> Path:
    """Return the vault root, without ever creating it.

    Creating a missing vault would turn a misconfiguration into an empty index
    that looks like a working one -- the same trap as the transcript directory
    in oneiros. A missing vault must be loud.
    """
    brut = os.environ.get(VAULT_ENV, "").strip()
    if brut:
        return Path(brut).expanduser()
    for candidat in (VAULT_PREVU, VAULT_ACTUEL):
        if candidat.is_dir():
            return candidat
    return VAULT_PREVU


def chemin_base() -> Path:
    """Where the index lives: beside the state the router already keeps."""
    return Path.home() / ".mac-ia" / "brain.db"


# --------------------------------------------------------------------------- #
# Query translation -- mandatory, not optional
# --------------------------------------------------------------------------- #

# A raw user query is **not** valid FTS5. Passing one through unmodified is not
# a degraded search, it is a crash: an apostrophe, a stray `*`, an unbalanced
# quote or a bare NEAR all raise sqlite3.OperationalError rather than returning
# nothing. The approach is deliberately blunt -- extract word-like tokens,
# quote every one, AND them together. Quoting neutralises the whole operator
# grammar. Users lose the ability to write FTS5 by hand, which they were not
# doing, and gain a search that never explodes.

#: Word-like runs. Unicode-aware so accented queries survive; internal dots and
#: dashes are kept so `config.json` and `pre-commit` stay single tokens.
_TOKEN = re.compile(r"[^\W_]+(?:[.\-_][^\W_]+)*", re.UNICODE)

#: Below this length a prefix wildcard matches most of the index.
_PREFIXE_MIN = 3


def tokeniser(requete: str) -> list[str]:
    """Extract word-like tokens, discarding punctuation and operators."""
    return _TOKEN.findall(requete or "")


def build_match(requete: str, prefixe: bool = True) -> str | None:
    """Return an FTS5 MATCH expression, or None when there is nothing to search.

    None rather than an empty string: an empty MATCH is a syntax error, and
    returning it would push the failure into the caller's SQL.
    """
    tokens = tokeniser(requete)
    if not tokens:
        return None
    quotes = ['"%s"' % t for t in tokens]
    if prefixe and len(tokens[-1]) >= _PREFIXE_MIN:
        # A prefix wildcard binds outside the quotes: "depl"* is valid,
        # "depl*" would match a literal asterisk.
        quotes[-1] = quotes[-1] + "*"
    return " AND ".join(quotes)


# --------------------------------------------------------------------------- #
# Reading the corpus
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Chunk:
    texte: str
    section: str
    ordre: int


_TITRE = re.compile(r"^#{1,6}\s+(.*\S)\s*$")


def decouper(contenu: str) -> list[Chunk]:
    """Split a document into passages, carrying the nearest heading along.

    Blank-line boundaries rather than a fixed window: a hit should land on a
    paragraph the reader recognises, not on an arbitrary slice that begins
    mid-sentence.
    """
    chunks: list[Chunk] = []
    section = ""
    tampon: list[str] = []
    taille = 0
    ordre = 0

    def vider() -> None:
        nonlocal tampon, taille, ordre
        if not tampon:
            return
        texte = "\n\n".join(tampon).strip()
        if texte:
            chunks.append(Chunk(texte=texte, section=section, ordre=ordre))
            ordre += 1
        tampon = []
        taille = 0

    for para in re.split(r"\n\s*\n", contenu):
        para = para.strip()
        if not para:
            continue
        titre = _TITRE.match(para.splitlines()[0]) if para.startswith("#") else None
        if titre:
            # A heading closes the passage before it: the text that follows
            # belongs to the new section, not the old one.
            vider()
            section = titre.group(1)
        if taille + len(para) > TAILLE_CHUNK:
            vider()
        tampon.append(para)
        taille += len(para)

    vider()
    return chunks


def parcourir(racine: Path) -> tuple[list[Path], dict[str, int]]:
    """Return indexable files, plus a count of what was skipped, by extension.

    The skipped tally is not decoration. A vault of PDFs indexes to nothing,
    and without this the operator sees an empty index with no cause attached.
    """
    fichiers: list[Path] = []
    ignores: dict[str, int] = {}
    for chemin in sorted(racine.rglob("*")):
        if any(part in IGNORES for part in chemin.parts):
            continue
        if not chemin.is_file():
            continue
        suffixe = chemin.suffix.lower()
        if suffixe in EXTENSIONS:
            fichiers.append(chemin)
        else:
            ignores[suffixe or "(sans extension)"] = ignores.get(suffixe or "(sans extension)", 0) + 1
    return fichiers, ignores


def lire(chemin: Path) -> str | None:
    """Read a document as UTF-8, or return None when it is not text after all.

    An extension is a claim, not a guarantee. A file that fails to decode is
    skipped rather than indexed as mojibake, which would pollute every search
    that follows.
    """
    try:
        return chemin.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


# --------------------------------------------------------------------------- #
# The index
# --------------------------------------------------------------------------- #

class Fts5Indisponible(RuntimeError):
    """This interpreter's SQLite was built without FTS5.

    Rare but real on minimal builds. Detected at open time so the failure is
    named plainly, rather than at first search where it looks like a query bug.
    """


@dataclass(frozen=True)
class Resultat:
    chemin: str
    section: str
    texte: str
    extrait: str


@dataclass(frozen=True)
class Etat:
    fichiers: int
    passages: int
    indexe_le: float | None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS fichiers (
    chemin      TEXT PRIMARY KEY,
    taille      INTEGER NOT NULL,
    mtime       REAL    NOT NULL,
    indexe_le   REAL    NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5 (
    texte,
    chemin   UNINDEXED,
    section  UNINDEXED,
    ordre    UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


class Index:
    """Full-text index over the vault."""

    def __init__(self, racine: Path | None = None, base: Path | None = None) -> None:
        self.racine = racine or resoudre_vault()
        self.base = base or chemin_base()
        self._conn: sqlite3.Connection | None = None

    def connecter(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        self.base.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.base))
        conn.row_factory = sqlite3.Row
        try:
            conn.executescript(_SCHEMA)
        except sqlite3.OperationalError as exc:
            conn.close()
            if "fts5" in str(exc).lower():
                raise Fts5Indisponible(
                    "le SQLite de ce Python n'a pas FTS5 : la recherche ne peut "
                    "pas fonctionner."
                ) from exc
            raise
        conn.commit()
        self._conn = conn
        return conn

    def fermer(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "Index":
        self.connecter()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.fermer()

    # -- ingestion ----------------------------------------------------------

    def rafraichir(self) -> dict[str, object]:
        """Index new and changed documents.

        Incremental by (size, mtime). Hashing every file on every run is
        correct and unusably slow past a few thousand notes. Unlike the
        transcripts oneiros reads, notes are *edited* rather than appended, so
        a changed file has its rows deleted and reinserted rather than diffed
        -- correct under both assumptions.
        """
        conn = self.connecter()
        fichiers, ignores = parcourir(self.racine)

        connus = {
            row["chemin"]: (row["taille"], row["mtime"])
            for row in conn.execute("SELECT chemin, taille, mtime FROM fichiers")
        }
        vus = {str(f) for f in fichiers}

        touches = 0
        illisibles = 0
        for chemin in fichiers:
            try:
                stat = chemin.stat()
            except OSError:
                continue
            cle = str(chemin)
            if connus.get(cle) == (stat.st_size, stat.st_mtime):
                continue
            contenu = lire(chemin)
            if contenu is None:
                illisibles += 1
                continue
            self._reindexer(conn, chemin, contenu, stat.st_size, stat.st_mtime)
            touches += 1

        # A note deleted from the vault must leave the index, or a search keeps
        # returning a passage the operator can no longer open.
        partis = [cle for cle in connus if cle not in vus]
        for cle in partis:
            conn.execute("DELETE FROM passages WHERE chemin = ?", (cle,))
            conn.execute("DELETE FROM fichiers WHERE chemin = ?", (cle,))

        conn.commit()
        return {
            "vus": len(fichiers),
            "indexes": touches,
            "retires": len(partis),
            "illisibles": illisibles,
            "ignores": ignores,
        }

    def _reindexer(
        self, conn: sqlite3.Connection, chemin: Path, contenu: str,
        taille: int, mtime: float,
    ) -> None:
        cle = str(chemin)
        conn.execute("DELETE FROM passages WHERE chemin = ?", (cle,))
        lignes = [
            (c.texte, cle, c.section, c.ordre) for c in decouper(contenu)
        ]
        if lignes:
            conn.executemany(
                "INSERT INTO passages (texte, chemin, section, ordre) "
                "VALUES (?, ?, ?, ?)",
                lignes,
            )
        conn.execute(
            "INSERT INTO fichiers (chemin, taille, mtime, indexe_le) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(chemin) DO UPDATE SET "
            "taille=excluded.taille, mtime=excluded.mtime, indexe_le=excluded.indexe_le",
            (cle, taille, mtime, time.time()),
        )

    # -- recherche ----------------------------------------------------------

    def chercher(self, requete: str, limite: int = 20) -> list[Resultat]:
        """Search the index. An unusable query returns nothing, never raises."""
        match = build_match(requete)
        if match is None:
            return []
        conn = self.connecter()
        try:
            lignes = conn.execute(
                "SELECT texte, chemin, section, "
                "       snippet(passages, 0, '<<', '>>', '...', 14) AS extrait "
                "FROM passages WHERE passages MATCH ? ORDER BY rank LIMIT ?",
                (match, limite),
            ).fetchall()
        except sqlite3.OperationalError:
            # build_match should make this unreachable. If it ever is reached,
            # an empty result beats a stack trace inside a daemon.
            return []
        return [
            Resultat(
                chemin=row["chemin"],
                section=row["section"],
                texte=row["texte"],
                extrait=row["extrait"],
            )
            for row in lignes
        ]

    def etat(self) -> Etat:
        conn = self.connecter()
        f = conn.execute(
            "SELECT COUNT(*) AS n, MAX(indexe_le) AS t FROM fichiers"
        ).fetchone()
        p = conn.execute("SELECT COUNT(*) AS n FROM passages").fetchone()
        return Etat(fichiers=f["n"] or 0, passages=p["n"] or 0, indexe_le=f["t"])


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _relatif(chemin: str, racine: Path) -> str:
    try:
        return str(Path(chemin).relative_to(racine))
    except ValueError:
        return chemin


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__.strip().splitlines()[0])
        print()
        print("  refresh            ingerer le vault (incremental)")
        print("  search <requete>   chercher, sans modele")
        print("  stats              etat de l'index")
        print()
        print("Vault : %s" % resoudre_vault())
        print("Index : %s" % chemin_base())
        return 2

    commande, reste = argv[0], argv[1:]
    index = Index()

    if not index.racine.is_dir():
        print("[ KO ] vault introuvable : %s" % index.racine)
        print("       Ni %s ni %s n'existent." % (VAULT_PREVU, VAULT_ACTUEL))
        print("       Definir %s pour pointer ailleurs." % VAULT_ENV)
        return 1

    try:
        if commande == "refresh":
            print("Vault : %s" % index.racine)
            bilan = index.rafraichir()
            print("[ OK ] %d fichiers vus, %d (re)indexes, %d retires"
                  % (bilan["vus"], bilan["indexes"], bilan["retires"]))
            if bilan["illisibles"]:
                print("       %d illisibles (pas de l'UTF-8 malgre l'extension)"
                      % bilan["illisibles"])
            ignores = bilan["ignores"]
            if ignores:
                detail = ", ".join(
                    "%s x%d" % (ext, n)
                    for ext, n in sorted(ignores.items(), key=lambda kv: -kv[1])[:8]
                )
                total = sum(ignores.values())
                print("       %d fichiers ignores : %s" % (total, detail))
                print("       (l'index ne lit que du texte -- un PDF n'est pas indexe)")
            etat = index.etat()
            print("       index : %d passages sur %d fichiers"
                  % (etat.passages, etat.fichiers))

        elif commande == "search":
            requete = " ".join(reste)
            if not requete.strip():
                print("[ KO ] requete vide")
                return 2
            resultats = index.chercher(requete)
            if not resultats:
                print("aucun resultat pour %r" % requete)
                if index.etat().passages == 0:
                    print("       l'index est vide -- lancer 'refresh' d'abord")
                return 0
            for r in resultats:
                titre = " > %s" % r.section if r.section else ""
                print("%s%s" % (_relatif(r.chemin, index.racine), titre))
                print("    %s" % r.extrait.replace("\n", " "))
            print()
            print("%d passages" % len(resultats))

        elif commande == "stats":
            etat = index.etat()
            print("vault    : %s" % index.racine)
            print("index    : %s" % index.base)
            print("contenu  : %d passages sur %d fichiers"
                  % (etat.passages, etat.fichiers))
            if etat.indexe_le:
                age = (time.time() - etat.indexe_le) / 3600
                print("derniere : il y a %.1f h" % age)
            else:
                print("derniere : jamais -- lancer 'refresh'")

        else:
            print("[ KO ] commande inconnue : %s" % commande)
            return 2

    except Fts5Indisponible as exc:
        print("[ KO ] %s" % exc)
        return 1
    finally:
        index.fermer()

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
