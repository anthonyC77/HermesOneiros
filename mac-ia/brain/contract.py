#!/usr/bin/env python3
"""What the search tool is allowed to return. The wall, not the preference.

**This file is the protection.** Not the network boundary, not the separate
machine: the rule about what may leave. Two machines without this rule protect
nothing -- the architecture is identical whether the tool returns forty verbatim
passages or three capped excerpts, and only one of those keeps the corpus local
(plan 4.3, step 2).

It runs **on the Mac**, inside the server process. Written in the client's
configuration it would be a preference, negotiable by asking nicely. Written
here it is a wall: the caller cannot raise a cap it never sees.

Standard library only, no import from `index` -- the MCP server is launched as
a bare subprocess by a harness that chose its own interpreter, and a module
that only loads when the stars align fails silently and intermittently.

The shape of the answer is fixed and the sizes are capped:

    chemin > section
      << ...extrait plafonne... >>

    N passages sur M documents

Never a pass-through. A caller asking for 500 results gets `MAX_RESULTATS`;
asking for a whole document gets an excerpt. Both without an error, because a
refusal would only teach the caller to ask differently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "MAX_RESULTATS",
    "MAX_CARACTERES",
    "MAX_TOTAL",
    "Passage",
    "plafonner",
    "rendre",
]

#: Results returned at most, whatever the caller asks for. Five is enough to
#: answer "where did I write about X" and too few to reconstruct a document by
#: paging through queries.
MAX_RESULTATS = 5

#: Characters of excerpt per result. Around 200 the excerpt carries the
#: sentence the term sits in -- enough to judge relevance and to quote -- and
#: not the paragraph around it.
MAX_CARACTERES = 200

#: Absolute ceiling on the whole answer. Belts and braces: it holds even if a
#: future edit raises the two caps above, or a path is pathologically long.
MAX_TOTAL = 2000

#: Collapses runs of whitespace. A passage spanning ten lines would otherwise
#: cost ten lines of context for 200 characters of content.
_ESPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class Passage:
    """One hit, before the contract is applied."""

    chemin: str
    section: str
    extrait: str


def plafonner(texte: str, limite: int = MAX_CARACTERES) -> str:
    """Collapse whitespace and cut to `limite`, on a word boundary when possible.

    Cutting mid-word produces excerpts that read as corrupted rather than
    truncated, and a reader who cannot tell the difference will report the
    wrong bug.
    """
    plat = _ESPACES.sub(" ", texte or "").strip()
    if len(plat) <= limite:
        return plat
    coupe = plat[:limite]
    espace = coupe.rfind(" ")
    # Only honour the word boundary when it is not absurdly early, otherwise a
    # single long token would shrink the excerpt to nothing.
    if espace > limite * 0.6:
        coupe = coupe[:espace]
    return coupe.rstrip() + "..."


def rendre(passages: list[Passage], documents: int, requete: str) -> str:
    """Render the fixed-shape answer, capped in every dimension.

    `documents` is the number of distinct files behind the hits -- the one
    aggregate worth returning, because it tells the caller whether a theme is
    spread across the corpus or confined to a single note, which no excerpt can
    convey.
    """
    if not passages:
        return "Aucun passage pour %r." % requete

    retenus = passages[:MAX_RESULTATS]
    lignes: list[str] = []
    for p in retenus:
        titre = "%s > %s" % (p.chemin, p.section) if p.section else p.chemin
        lignes.append(plafonner(titre, 120))
        lignes.append("  << %s >>" % plafonner(p.extrait))
        lignes.append("")

    lignes.append(
        "%d passage(s) sur %d document(s)." % (len(retenus), documents)
    )
    if len(passages) > MAX_RESULTATS:
        # Saying so matters: a caller who believes it saw everything will
        # conclude the corpus is silent on a subject it merely ranked lower.
        lignes.append(
            "Reponse plafonnee a %d resultats ; affinez la requete pour le reste."
            % MAX_RESULTATS
        )

    rendu = "\n".join(lignes)
    if len(rendu) > MAX_TOTAL:
        rendu = rendu[:MAX_TOTAL].rstrip() + "\n[reponse tronquee]"
    return rendu
