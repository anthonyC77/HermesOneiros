#!/usr/bin/env python3
"""Déplie des runs résumés en événements : pour regarder dans Ruche ce que les oracles ont jugé.

Entrée : un runs.jsonl conforme à eval/schemas/run_contract.schema.json.
Sortie : un <run_id>.events.jsonl par run, conforme à eval/schemas/run_events.schema.json.

    python3 eval/deplier_runs.py eval/fixtures/runs_tasks.jsonl --out runs/
    # puis dans Ruche : ?run=…/run-t-03-001.events.jsonl&eval=…/judge.jsonl

Ce n'est pas une trace, c'est une silhouette : un seul acteur, run.start à
t = 0, une paire tool.start / tool.end par appel séparée de latency_ms,
run.end à t = cost.wall_clock_ms. Le fichier le dit : run.start porte
ref = "deplie:<run_id>". L'invariant testé : plier(deplier(run)) rend les
champs transportés (run_id, task_id, status, outils et ok, cost, policy,
human_interventions).

Stdlib uniquement.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from jsonschema_lite import validate  # noqa: E402
from plier_evenements import charger_schema, verifier_evenements  # noqa: E402


def deplier(run):
    """(en-tête, événements) — la silhouette d'un run résumé."""
    run_id, agent = run["run_id"], run["policy"]["agent"]
    entete = {"run_id": run_id, "task_id": run["task_id"], "contract_version": 1,
              "agents": [{"id": agent, "role": agent, "depth": 0}], "policy": run["policy"]}
    evenements = []
    horloge = [0]

    def emettre(kind, **champs):
        e = {"v": 1, "seq": len(evenements), "t": horloge[0], "run": run_id, "actor": agent, "origin": "observed", "kind": kind}
        e.update(champs)
        evenements.append(e)

    emettre("run.start", ref=f"deplie:{run_id}", task=run["task_id"], title=run["input"]["message"], policy=run["policy"])
    for appel in run["tool_calls"]:
        args = json.dumps(appel["input"], ensure_ascii=False, sort_keys=True)
        emettre("tool.start", tool=appel["tool"], args=args)
        latence = int(appel.get("latency_ms", 0))
        horloge[0] += latence
        fin = {"tool": appel["tool"], "args": args, "ok": bool(appel["ok"]), "ms": latence}
        if appel["output"] is not None:
            fin["out"] = json.dumps(appel["output"], ensure_ascii=False, sort_keys=True)
        emettre("tool.end", **fin)
    cout = run["cost"]
    # t peut reculer ici si la somme des latences dépasse wall_clock_ms : la spec §5.3 impose que
    # run.end porte t = wall_clock_ms, ceci n'est qu'une silhouette, et assertWellFormed côté Ruche
    # n'exige pas que t soit monotone.
    horloge[0] = cout["wall_clock_ms"]
    emettre("run.end", status=run["status"],
            totals={"calls": cout["calls"], "tok_in": cout["tokens_in"], "tok_out": cout["tokens_out"],
                    "eur": cout["eur"], "wall_clock_ms": cout["wall_clock_ms"],
                    "human_interventions": run["human_interventions"]})
    return entete, evenements


def nom_de_fichier(run_id):
    return re.sub(r"[^A-Za-z0-9._-]", "_", run_id) + ".events.jsonl"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("runs", help="runs.jsonl au format du contrat de run")
    p.add_argument("--out", required=True, help="dossier de sortie, un .events.jsonl par run")
    a = p.parse_args(argv)
    contrat, schema = charger_schema("run_contract.schema.json"), charger_schema("run_events.schema.json")
    try:
        with open(a.runs, encoding="utf-8") as f:
            runs = [json.loads(l) for l in f if l.strip()]
        fichiers = []
        for i, run in enumerate(runs):
            erreurs = validate(run, contrat)
            if erreurs:
                raise ValueError(f"{a.runs} ligne {i + 1} : hors contrat de run : " + "; ".join(erreurs[:5]))
            entete, evenements = deplier(run)
            verifier_evenements(entete, evenements, schema, nom=run["run_id"])
            fichiers.append((nom_de_fichier(run["run_id"]), [entete] + evenements))
    except (OSError, ValueError, KeyError) as e:
        print(f"refusé — {e}", file=sys.stderr)
        return 2
    os.makedirs(a.out, exist_ok=True)
    for nom, lignes in fichiers:
        with open(os.path.join(a.out, nom), "w", encoding="utf-8") as f:
            f.write("".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lignes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
