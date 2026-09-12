#!/usr/bin/env python3
"""Plie des runs en événements en runs résumés : ce qu'on a vu devient ce qu'on peut juger.

Entrée : un ou plusieurs fichiers *.events.jsonl conformes à
eval/schemas/run_events.schema.json (une ligne d'en-tête, puis une ligne par
événement). Sortie : un runs.jsonl conforme à eval/schemas/run_contract.schema.json,
un run par fichier, que run_tasks_eval.py peut juger.

    python3 eval/plier_evenements.py runs/*.events.jsonl --out runs.jsonl
    python3 eval/run_tasks_eval.py --runs runs.jsonl --judge-cmd "python3 eval/juge_local.py"

Ce que le script refuse (code 2, nom du fichier sur stderr) : pas d'en-tête,
pas de run.start en tête, pas de run.end en queue, un trou dans seq, un genre
ou un champ hors contrat. Un run plié qui ne passe pas le contrat de run n'est
pas écrit. Un tool.start jamais revenu n'est pas une erreur de format : c'est
un tool_calls[] avec ok: false et sans latency_ms.

Stdlib uniquement. Deux règles que le JSON Schema ne sait pas exprimer
(contiguïté de seq, ordre des lignes) vivent dans verifier_evenements().
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from jsonschema_lite import validate  # noqa: E402

SCHEMAS = os.path.join(HERE, "schemas")


def charger_schema(nom):
    with open(os.path.join(SCHEMAS, nom), encoding="utf-8") as f:
        return json.load(f)


def verifier_evenements(entete, evenements, schema, nom="<événements>"):
    """Ce que le schéma ne dit pas : un en-tête d'abord, seq contigu depuis 0, run.start en tête, run.end en queue.
    Lève ValueError, message préfixé du nom du fichier."""
    def refus(message):
        raise ValueError(f"{nom} : {message}")

    if not isinstance(entete, dict) or "kind" in entete or "run_id" not in entete:
        refus("première ligne sans en-tête (run_id, task_id, agents, policy)")
    erreurs = validate(entete, schema["$defs"]["header"], "en-tête", schema)
    if erreurs:
        refus("; ".join(erreurs[:5]))
    if not evenements:
        refus("aucun événement après l'en-tête")
    genres = schema["$defs"]["kinds"]
    for i, e in enumerate(evenements):
        ligne = i + 2
        genre = e.get("kind") if isinstance(e, dict) else None
        if genre not in genres:
            refus(f"ligne {ligne} : genre inconnu {genre!r}")
        erreurs = validate(e, genres[genre], f"ligne {ligne}", schema)
        if erreurs:
            refus("; ".join(erreurs[:5]))
        if e["seq"] != i:
            refus(f"ligne {ligne} : trou dans seq, attendu {i}, reçu {e['seq']}")
        if e["run"] != entete["run_id"]:
            refus(f"ligne {ligne} : run {e['run']!r} ne correspond pas au run_id de l'en-tête")
    if sum(1 for e in evenements if e["kind"] == "run.start") != 1:
        refus("plus d'un run.start dans le fichier")
    if evenements[0]["kind"] != "run.start":
        refus("le premier événement n'est pas run.start")
    if evenements[-1]["kind"] != "run.end":
        refus("le dernier événement n'est pas run.end — fichier tronqué ?")


def charger(chemin, schema):
    """Un fichier .events.jsonl → (en-tête, événements), vérifié."""
    lignes = []
    with open(chemin, encoding="utf-8") as f:
        for n, l in enumerate(f, start=1):
            if not l.strip():
                continue
            try:
                lignes.append(json.loads(l))
            except ValueError as e:
                raise ValueError(f"{chemin} ligne {n} : JSON illisible : {e}") from e
    if not lignes:
        raise ValueError(f"{chemin} : fichier vide")
    verifier_evenements(lignes[0], lignes[1:], schema, nom=str(chemin))
    return lignes[0], lignes[1:]


def plier(entete, evenements):
    """Un run résumé (contrat 1.0) depuis un run en événements — la table de correspondance de la spec §5.2.

    Les appels d'outils sont appariés par (actor, tool, args), dans l'ordre : apparier par acteur seul
    ferait qu'un tool.start jamais revenu (refusé par un hook) vole le tool.end suivant.

    Un hook.deny sur PreToolUse porte `tool` mais pas `args` : le hook a vu l'intention avant l'appel,
    donc pas moyen de le retrouver par (actor, tool, args). On ferme alors le tool.start en attente le
    plus récent pour ce (actor, tool) — cet appel n'aura jamais de tool.end — pour qu'un nouvel essai
    identique (mêmes actor/tool/args) n'hérite pas à tort du refus du précédent en volant sa place dans
    la file FIFO."""
    debut, fin = evenements[0], evenements[-1]
    appels, en_attente = [], {}
    for e in evenements:
        if e["kind"] == "tool.start":
            appel = {"tool": e["tool"], "input": {"args": e["args"]}, "output": None, "ok": False}
            appels.append(appel)
            en_attente.setdefault((e["actor"], e["tool"], e["args"]), []).append((e["seq"], appel))
        elif e["kind"] == "tool.end":
            file = en_attente.get((e["actor"], e["tool"], e["args"]), [])
            appel = file.pop(0)[1] if file else None
            if appel is None:   # un tool.end sans tool.start : on le garde, c'est un fait
                appel = {"tool": e["tool"], "input": {"args": e["args"]}}
                appels.append(appel)
            appel.update({"output": e.get("out"), "ok": bool(e["ok"]), "latency_ms": int(e["ms"])})
        elif e["kind"] == "hook.deny" and e.get("event") == "PreToolUse" and "tool" in e:
            candidats = [(seq, cle) for cle, file in en_attente.items()
                         if cle[0] == e["actor"] and cle[1] == e["tool"] for seq, _ in file]
            if candidats:
                seq_max, cle = max(candidats, key=lambda x: x[0])
                file = en_attente[cle]
                for i, (seq, _) in enumerate(file):
                    if seq == seq_max:
                        del file[i]
                        break
    totaux = fin["totals"]
    run = {
        "contract_version": "1.0",
        "run_id": entete["run_id"],
        "task_id": entete["task_id"],
        "status": fin["status"],
        "input": {"message": debut["title"]},
        "output": {"text": ""},           # le texte final est du contenu : il voyage par ref, pas dans le journal
        "tool_calls": appels,
        "provenance": [],                  # non dérivable des événements
        "cost": {"calls": totaux["calls"], "tokens_in": totaux["tok_in"], "tokens_out": totaux["tok_out"],
                 "eur": totaux["eur"], "wall_clock_ms": totaux["wall_clock_ms"]},
        "policy": entete["policy"],
        "human_interventions": totaux["human_interventions"],
    }
    if run["status"] == "cancelled":
        run["cancelled"] = True
    return run


def plier_fichiers(chemins, schema_evenements, contrat):
    """Tous les fichiers, ou rien : un run plié qui ne passe pas le contrat n'est pas écrit."""
    runs = []
    for chemin in chemins:
        entete, evenements = charger(chemin, schema_evenements)
        run = plier(entete, evenements)
        erreurs = validate(run, contrat)
        if erreurs:
            raise ValueError(f"{chemin} : le run plié ne passe pas le contrat de run : " + "; ".join(erreurs[:5]))
        runs.append(run)
    return runs


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("fichiers", nargs="+", help="*.events.jsonl")
    p.add_argument("--out", help="runs.jsonl à écrire (défaut : stdout)")
    a = p.parse_args(argv)
    try:
        runs = plier_fichiers(a.fichiers, charger_schema("run_events.schema.json"), charger_schema("run_contract.schema.json"))
    except (OSError, ValueError, KeyError) as e:
        print(f"refusé — {e}", file=sys.stderr)
        return 2
    texte = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in runs)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(texte)
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(texte)
    return 0


if __name__ == "__main__":
    sys.exit(main())
