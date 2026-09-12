#!/usr/bin/env python3
"""Le juge hors système : un modèle local sur le Mac, appelé en dialecte OpenAI.

Implémente le contrat --judge-cmd de run_tasks_eval.py :
    stdin  : {"task": <golden>, "run": <run>, "rubric": str}
    stdout : {"pass": bool, "reason": str}, code 0
    sinon  : code 2, message sur stderr — jamais un pass: false pour une panne.

Pourquoi ce modèle est un bon juge : l'éval ne passe jamais par un agent du
système évalué. Qwen sur une machine hors ligne, qui ne partage ni code ni
prompt avec oneiros ou coachingia, est extérieur par construction.

Ce que le juge reçoit : la rubrique, l'entrée, la sortie, le statut, les outils
appelés (nom, ok). Ce qu'il ne reçoit jamais : la sortie attendue — sinon il
compare au lieu de juger — ni les sorties volumineuses des outils.

    python3 eval/run_tasks_eval.py --runs eval/fixtures/runs_tasks.jsonl \
        --judge-cmd "python3 eval/juge_local.py"

Configuration par variables d'environnement :
    HARNAIS_JUGE_URL      http://192.168.1.50:1234/v1   LM Studio, dialecte OpenAI
    HARNAIS_JUGE_MODELE   brain                          l'identifiant forcé par le routeur
    HARNAIS_JUGE_TIMEOUT  120                            secondes — le profil brain réfléchit

Le juge ne bascule jamais de profil lui-même : `harnais/mac-ia/router/profiles.py switch brain`.
"""
import json
import os
import sys
import urllib.error
import urllib.request

URL = os.environ.get("HARNAIS_JUGE_URL", "http://192.168.1.50:1234/v1")
MODELE = os.environ.get("HARNAIS_JUGE_MODELE", "brain")
TIMEOUT = float(os.environ.get("HARNAIS_JUGE_TIMEOUT", "120"))

SYSTEME = (
    "Tu es le juge d'une évaluation. On te donne une rubrique, la demande faite à un assistant, "
    "sa réponse, son statut et la liste des outils qu'il a appelés. Décide si la réponse satisfait "
    "la rubrique. Réponds uniquement par un objet JSON de la forme "
    "{\"pass\": true ou false, \"reason\": \"une raison courte et vérifiable\"}. Rien d'autre après le JSON."
)


def composer(payload):
    """Le message utilisateur. Ni `task.expected`, ni les sorties d'outils : le juge juge, il ne compare pas."""
    run = payload.get("run", {})
    outils = [{"tool": c.get("tool"), "ok": c.get("ok")} for c in run.get("tool_calls", [])]
    return "\n".join([
        "RUBRIQUE :", payload.get("rubric", "") or "(aucune rubrique : juge la pertinence et l'exactitude)",
        "", "DEMANDE :", run.get("input", {}).get("message", ""),
        "", "RÉPONSE :", run.get("output", {}).get("text", ""),
        "", "STATUT :", str(run.get("status", "")),
        "", "OUTILS APPELÉS (nom, ok) :", json.dumps(outils, ensure_ascii=False),
    ])


def extraire_json(texte):
    """Le dernier objet JSON portant `pass` — un modèle à réflexion parle avant de répondre."""
    dec = json.JSONDecoder()
    for i in range(len(texte) - 1, -1, -1):
        if texte[i] != "{":
            continue
        try:
            obj, _ = dec.raw_decode(texte[i:])
        except ValueError:
            continue
        if isinstance(obj, dict) and "pass" in obj:
            return obj
    return None


def appeler(messages):
    corps = json.dumps({"model": MODELE, "messages": messages, "temperature": 0, "stream": False}).encode("utf-8")
    req = urllib.request.Request(f"{URL.rstrip('/')}/chat/completions", data=corps,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        payload = json.load(sys.stdin)
    except ValueError as e:
        print(f"entrée illisible : {e}", file=sys.stderr)
        return 2
    messages = [{"role": "system", "content": SYSTEME}, {"role": "user", "content": composer(payload)}]
    try:
        reponse = appeler(messages)
    except urllib.error.HTTPError as e:   # le serveur répond mais refuse — distinct d'un hôte injoignable
        print(f"juge : HTTP {e.code} sur {URL} : {e.reason}", file=sys.stderr)
        return 2
    except (urllib.error.URLError, OSError, ValueError) as e:   # refus de connexion, timeout (socket.timeout est un OSError), corps non JSON
        print(f"juge injoignable ({URL}) : {e}", file=sys.stderr)
        return 2
    try:
        choix = reponse["choices"][0]
        texte = choix["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        print(f"réponse inattendue : {json.dumps(reponse)[:200]}", file=sys.stderr)
        return 2
    verdict = extraire_json(texte)
    if verdict is None:
        motif = "max_tokens atteint avant le JSON" if choix.get("finish_reason") == "length" else "aucun JSON dans la réponse"
        print(f"{motif} : {texte[-200:]!r}", file=sys.stderr)
        return 2
    raison = str(verdict.get("reason", "")).strip()
    if not raison:
        print("verdict sans raison : un verdict sans explication ne se conteste pas", file=sys.stderr)
        return 2
    if not isinstance(verdict.get("pass"), bool):
        print("verdict sans pass booléen : un pass non booléen est une panne, pas une valeur à convertir", file=sys.stderr)
        return 2
    print(json.dumps({"pass": verdict["pass"], "reason": raison}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
