#!/bin/bash
# Runbook for putting the 'brain' profile (Qwen3.8-27B MLX 4-bit) into service.
#
# Standard library and system tools only -- no jq, no pip. This runs on a Mac
# with no default route (LIAISON_HERMES_MAC.md 4.3); a script that needs to be
# installed is useless on exactly the day it is needed.
#
# The script never opens the network, never closes it, and never updates the
# runtime. Those stay deliberate manual acts. What it does is say, at each
# step, whether you may go on -- and stop at the first layer that fails.
#
#   ./verifier-brain.sh avant       # phase 0, hors ligne : point de repere
#   ./verifier-brain.sh recuperer   # phase 1, fenetre OUVERTE : moteur puis poids
#   ./verifier-brain.sh tester      # les 5 blocs -- le test qui tranche
#   ./verifier-brain.sh apres       # phase 2 : refermeture verifiee, puis tester

set -u

ICI="$(cd "$(dirname "$0")" && pwd)"
PROFILES="$ICI/router/profiles.json"
ROUTEUR="$ICI/router/profiles.py"
ENDPOINT="http://127.0.0.1:1234/v1"
PROFIL="brain"

# --------------------------------------------------------------------------- #
# Affichage
# --------------------------------------------------------------------------- #

titre() { printf '\n=== %s ===\n' "$1"; }
ok()    { printf '[ OK ] %s\n' "$1"; }
ko()    { printf '[ KO ] %s\n' "$1"; }
info()  { printf '       %s\n' "$1"; }

fatal() {
  printf '\n[ KO ] %s\n' "$1"
  shift
  for ligne in "$@"; do printf '       %s\n' "$ligne"; done
  exit 1
}

# --------------------------------------------------------------------------- #
# Outils
# --------------------------------------------------------------------------- #

# `lms` is not on PATH in a GUI-launched shell. profiles.py looks in the same
# places; the two must not disagree about which binary is in charge.
trouver_lms() {
  if command -v lms >/dev/null 2>&1; then command -v lms; return 0; fi
  for candidat in "$HOME/.lmstudio/bin/lms" "$HOME/.cache/lm-studio/bin/lms"; do
    if [ -x "$candidat" ]; then echo "$candidat"; return 0; fi
  done
  return 1
}

trouver_python() {
  for candidat in python3 /usr/bin/python3; do
    if command -v "$candidat" >/dev/null 2>&1; then echo "$candidat"; return 0; fi
  done
  return 1
}

# Reads one field of the profile out of profiles.json. The config is the single
# source of truth for the model key -- this script must not carry a second one.
lire_profil() {
  "$PY" -c '
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    cfg = json.load(fh)
print(cfg["profiles"][sys.argv[2]].get(sys.argv[3], ""))
' "$PROFILES" "$PROFIL" "$1"
}

preflight() {
  PY="$(trouver_python)" || {
    printf '[ KO ] python3 introuvable. Installer : xcode-select --install\n'
    exit 1
  }
  LMS="$(trouver_lms)" || {
    printf '[ KO ] binaire lms introuvable.\n'
    printf '       Ouvrir LM Studio une fois, puis : ~/.lmstudio/bin/lms bootstrap\n'
    exit 1
  }
  [ -f "$PROFILES" ] || fatal "profiles.json introuvable : $PROFILES"
  [ -f "$ROUTEUR" ] || fatal "router/profiles.py introuvable : $ROUTEUR"
  CLE="$(lire_profil model_key)"
  CTX="$(lire_profil context_length)"
  [ -n "$CLE" ] || fatal "le profil '$PROFIL' n'a pas de 'model_key' dans profiles.json"
}

# --------------------------------------------------------------------------- #
# Requetes
# --------------------------------------------------------------------------- #

# Body on stdin, HTTP status appended as the last line. A plain curl would
# swallow a 4xx body, and that body is precisely what carries the diagnosis.
appeler() {
  curl -sS --max-time 600 -w '\n%{http_code}' \
    -H 'Content-Type: application/json' \
    -d @- "$ENDPOINT/chat/completions" 2>&1
}

# Extracts one field from an OpenAI response read on stdin. `python3 -c` is
# required here, not `python3 -`: the latter would eat the response as its own
# source and leave sys.stdin empty.
extraire() {
  "$PY" -c '
import json, sys
champ = sys.argv[1]
try:
    rep = json.loads(sys.stdin.read())
except (json.JSONDecodeError, ValueError):
    sys.exit(0)
msg = (rep.get("choices") or [{}])[0].get("message") or {}
if champ == "texte":
    print((msg.get("content") or "").strip()[:200])
elif champ == "raison":
    print((msg.get("reasoning_content") or "").strip()[:200])
elif champ == "outil":
    for appel in msg.get("tool_calls") or []:
        print((appel.get("function") or {}).get("name", ""))
elif champ == "erreur":
    err = rep.get("error")
    if isinstance(err, dict):
        err = err.get("message")
    print(str(err or "").strip()[:400])
' "$1"
}

# The failure this whole runbook exists for: an engine that does not know the
# architecture. The wording moves between builds, so match several fragments.
architecture_refusee() {
  printf '%s' "$1" | grep -qiE 'unknown (model )?architecture|unsupported model|qwen3_5|not supported|unrecognized'
}

serveur_debout() {
  curl -sS --max-time 5 "$ENDPOINT/models" >/dev/null 2>&1
}

en_ligne() {
  route -n get default >/dev/null 2>&1
}

# --------------------------------------------------------------------------- #
# Phase 0 -- hors ligne, avant toute fenetre
# --------------------------------------------------------------------------- #

phase_avant() {
  titre "Phase 0 -- point de repere (hors ligne)"
  info "But : pouvoir dire, plus tard, ce qui a change."

  printf '\n       lms     : %s\n' "$("$LMS" version 2>&1 | head -1)"
  printf '       profil  : %s -> %s\n' "$PROFIL" "$CLE"
  printf '       contexte: %s\n' "$CTX"

  titre "Route par defaut"
  if en_ligne; then
    ko "une route par defaut existe -- le Mac est EN LIGNE."
    info "Hors fenetre, l'attendu est : aucune route. Verifier avant de continuer."
  else
    ok "aucune route par defaut (posture normale)."
  fi

  titre "Instances residentes"
  "$LMS" ps 2>&1 | sed 's/^/       /'

  titre "Etat du routeur"
  "$PY" "$ROUTEUR" status 2>&1 | sed 's/^/       /'

  titre "Moteur MLX installe"
  if ! "$LMS" runtime ls 2>/dev/null | sed 's/^/       /'; then
    info "('lms runtime ls' absent de cette version du CLI)"
  fi
  info "Relever la version a la main : LM Studio -> Cmd+Shift+R -> onglet MLX"

  titre "A retenir avant d'ouvrir le reseau"
  info "1. NE PAS supprimer qwen3-coder-30b-a3b : c'est le retour arriere,"
  info "   et il ne coute que du disque."
  info "2. Le garde-fou ~/.mac-ia/hermes.hold est inerte : rien ne le cree."
  info "   Basculer sur '$PROFIL' dechargera 'code' sans prevenir, et Hermes"
  info "   repondra 'model not found' -- pas une erreur reseau."
  info "   Arreter Hermes, ou : touch ~/.mac-ia/hermes.hold"
}

# --------------------------------------------------------------------------- #
# Phase 1 -- fenetre ouverte
# --------------------------------------------------------------------------- #

phase_recuperer() {
  titre "Phase 1 -- recuperation (fenetre reseau OUVERTE)"

  if ! en_ligne; then
    fatal "aucune route par defaut : le reseau n'est pas ouvert." \
      "C'est la seule phase qui exige le reseau. Ouvrir la fenetre (4.5)," \
      "puis relancer."
  fi
  ok "route par defaut presente."

  titre "Ordre imperatif : le moteur AVANT les poids"
  info "Si la mise a jour du moteur echoue, vous l'apprenez maintenant -- et non"
  info "apres 16 Go telecharges."
  info ""
  info "  1. LM Studio -> mise a jour de l'application"
  info "  2. Cmd+Shift+R -> runtime MLX -> Update"
  info ""
  printf '       Moteur MLX mis a jour ? [oui/non] '
  read -r reponse
  case "$reponse" in
    oui | OUI | o | O | y | Y) ok "poursuite." ;;
    *) fatal "arret demande." "Mettre a jour le moteur, puis relancer cette phase." ;;
  esac

  titre "Telechargement des poids"
  info "Cle demandee : $CLE"
  if ! "$LMS" get "$CLE" 2>&1 | sed 's/^/       /'; then
    fatal "'lms get' a echoue." \
      "Verifier que la fenetre a bien restaure la resolution DNS, et que la" \
      "cle existe : $CLE"
  fi
  ok "poids presents."

  titre "Cle reelle du catalogue"
  info "Celle que 'lms ls' renvoie fait foi, pas celle du depot Hugging Face."
  "$LMS" ls --json 2>/dev/null | "$PY" -c '
import json, sys
try:
    items = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if isinstance(items, dict):
    items = items.get("models") or items.get("data") or []
for item in items:
    if not isinstance(item, dict):
        continue
    cle = str(item.get("modelKey") or item.get("path") or item.get("id") or "")
    if "3.8" in cle or "27b" in cle.lower():
        print("       " + cle)
'
  info ""
  info "Si cette ligne differe de la cle du profil, corriger 'model_key' dans"
  info "router/profiles.json AVANT de lancer 'tester'."

  titre "Suite"
  info "Fenetre encore ouverte :  ./verifier-brain.sh tester"
  info "Puis refermer, et :       ./verifier-brain.sh apres"
}

# --------------------------------------------------------------------------- #
# Le test qui tranche
# --------------------------------------------------------------------------- #

# Each block validates one layer and says where to stop looking. A failure in
# 4/5 with 1/5 to 3/5 green is never a network problem.

bloc_serveur() {
  titre "1/5 -- serveur"
  if ! serveur_debout; then
    info "serveur absent, demarrage..."
    "$LMS" server start --bind 0.0.0.0 >/dev/null 2>&1
    sleep 2
    serveur_debout || fatal "le serveur LM Studio ne repond pas sur $ENDPOINT" \
      "  lsof -nP -iTCP:1234 -sTCP:LISTEN"
  fi
  ok "endpoint joignable."
}

bloc_residence() {
  titre "2/5 -- residence"
  info "Decharge tout, puis charge '$PROFIL' avec un identifiant force."
  sortie="$("$PY" "$ROUTEUR" switch "$PROFIL" 2>&1)"
  code=$?
  printf '%s\n' "$sortie" | sed 's/^/       /'
  if [ $code -ne 0 ]; then
    if architecture_refusee "$sortie"; then
      fatal "LE MOTEUR NE CONNAIT PAS L'ARCHITECTURE." \
        "C'est le symptome que tout ce runbook vise : moteur MLX trop ancien" \
        "pour Qwen3_5ForConditionalGeneration." \
        "" \
        "Reparation : rouvrir la fenetre reseau, Cmd+Shift+R -> MLX -> Update," \
        "puis relancer 'tester' AVANT de refermer." \
        "" \
        "Le profil 'code' est intact : python3 router/profiles.py switch code"
    fi
    fatal "la bascule a echoue (voir ci-dessus)." \
      "Un identifiant sorti en '$PROFIL:2' est la double instance (4.5) :" \
      "  lms unload --all   puis relancer."
  fi
  ok "'$PROFIL' resident, sans suffixe."
}

bloc_generation() {
  titre "3/5 -- generation"
  charge="$("$PY" -c '
import json, sys
print(json.dumps({
    "model": sys.argv[1],
    "messages": [{"role": "user", "content": "Reponds exactement : PRET"}],
    "max_tokens": 512,
    "temperature": 0,
}))
' "$PROFIL")"
  reponse="$(printf '%s' "$charge" | appeler)"
  statut="$(printf '%s' "$reponse" | tail -1)"
  corps="$(printf '%s' "$reponse" | sed '$d')"

  if [ "$statut" != "200" ]; then
    if architecture_refusee "$corps"; then
      fatal "LE MOTEUR NE CONNAIT PAS L'ARCHITECTURE (au premier prompt)." \
        "Meme reparation qu'en 2/5 : mettre a jour le runtime MLX."
    fi
    erreur="$(printf '%s' "$corps" | extraire erreur)"
    fatal "HTTP $statut sur la completion." "${erreur:-$corps}"
  fi

  texte="$(printf '%s' "$corps" | extraire texte)"
  raison="$(printf '%s' "$corps" | extraire raison)"
  # content empty + reasoning present is a thinking model, not a broken
  # template. Measured 2026-09-06: 42 reasoning tokens for a 5-token answer,
  # and the reasoning cannot be turned off -- neither
  # chat_template_kwargs.enable_thinking nor the /no_think suffix has any
  # effect through LM Studio. Diagnosing this as a template fault sends the
  # operator to fix something that is not broken.
  if [ -z "$texte" ] && [ -n "$raison" ]; then
    fatal "tout le budget est parti en raisonnement, rien dans 'content'." \
      "Ce modele reflechit, et la reflexion NE SE COUPE PAS : ni" \
      "chat_template_kwargs.enable_thinking, ni le suffixe /no_think." \
      "Ce n'est donc pas une panne -- augmenter max_tokens (>= 512)." \
      "Raisonnement recu : $raison"
  fi
  if [ -z "$texte" ]; then
    fatal "reponse 200, ni contenu ni raisonnement." \
      "La, c'est bien le template : passer en Template (Jinja) (5.1)."
  fi
  if [ -n "$raison" ]; then
    info "raisonnement emis avant la reponse (modele a reflexion) -- normal."
  fi
  ok "genere : $texte"
}

bloc_outils() {
  titre "4/5 -- tool calling"
  info "Le vrai critere d'exploitabilite : un modele qui repond joliment mais"
  info "rend ses appels d'outils en texte est inutilisable pour l'agent."
  charge="$("$PY" -c '
import json, sys
print(json.dumps({
    "model": sys.argv[1],
    "messages": [{"role": "user", "content": "Quel temps fait-il a Lyon ? Appelle la fonction meteo."}],
    "tools": [{
        "type": "function",
        "function": {
            "name": "meteo",
            "description": "Meteo actuelle d une ville",
            "parameters": {
                "type": "object",
                "properties": {"ville": {"type": "string"}},
                "required": ["ville"],
            },
        },
    }],
    "tool_choice": "auto",
    "max_tokens": 128,
    "temperature": 0,
}))
' "$PROFIL")"
  reponse="$(printf '%s' "$charge" | appeler)"
  statut="$(printf '%s' "$reponse" | tail -1)"
  corps="$(printf '%s' "$reponse" | sed '$d')"

  if [ "$statut" != "200" ]; then
    erreur="$(printf '%s' "$corps" | extraire erreur)"
    fatal "HTTP $statut sur le tool calling." "${erreur:-$corps}"
  fi

  outil="$(printf '%s' "$corps" | extraire outil)"
  if [ -z "$outil" ]; then
    ko "aucun tool_call -- le modele a repondu en texte."
    info "Reponse : $(printf '%s' "$corps" | extraire texte)"
    info ""
    info "Ordre de depannage (5.1). On ne change PAS de modele en premier :"
    info "  1. Context Length >= 32768 ET KV Cache Quantization DESACTIVEE"
    info "  2. Template (Jinja), pas un template generique"
    info "  3. Basculer MLX <-> GGUF"
    info "  4. Alors seulement, changer de modele"
    exit 1
  fi
  ok "tool_call recu : $outil"
}

bloc_contexte() {
  titre "5/5 -- contexte long et prefill"
  info "Contexte annonce : $CTX tokens. On envoie ~9600 tokens, et on chronometre."
  charge="$("$PY" -c '
import json, sys
phrase = "La liaison entre la machine et le modele passe par le reseau. "
texte = phrase * 1200
question = "\n\nCombien de fois cette phrase se repete-t-elle, approximativement ?"
print(json.dumps({
    "model": sys.argv[1],
    "messages": [{"role": "user", "content": texte + question}],
    "max_tokens": 32,
    "temperature": 0,
}))
' "$PROFIL")"
  debut=$(date +%s)
  reponse="$(printf '%s' "$charge" | appeler)"
  fin=$(date +%s)
  statut="$(printf '%s' "$reponse" | tail -1)"
  corps="$(printf '%s' "$reponse" | sed '$d')"

  if [ "$statut" != "200" ]; then
    erreur="$(printf '%s' "$corps" | extraire erreur)"
    fatal "HTTP $statut sur le prompt long." \
      "${erreur:-$corps}" \
      "" \
      "Contexte trop court cote LM Studio, ou KV Cache Quantization active --" \
      "elle annule le Context Length sans le dire (5.2)."
  fi
  ok "prompt long accepte en $((fin - debut)) s, prefill a froid inclus."
}

phase_tester() {
  bloc_serveur
  bloc_residence
  bloc_generation
  bloc_outils
  bloc_contexte

  titre "Verdict"
  ok "les cinq blocs passent : le profil '$PROFIL' est exploitable."
  if en_ligne; then
    info ""
    info "MAIS le reseau est encore ouvert, donc ce resultat ne prouve rien"
    info "sur la posture hors ligne. Refermer (4.5), puis :"
    info "  ./verifier-brain.sh apres"
  fi
}

# --------------------------------------------------------------------------- #
# Phase 2 -- apres refermeture
# --------------------------------------------------------------------------- #

phase_apres() {
  titre "Phase 2 -- validation hors ligne"
  info "Certains runtimes vont chercher un tokenizer au premier chargement."
  info "Cela marche fenetre ouverte et casse ensuite. D'ou cette phase."

  if en_ligne; then
    fatal "une route par defaut existe encore : le reseau n'est pas referme." \
      "Refermer selon 4.5, verifier, puis relancer."
  fi
  ok "aucune route par defaut : reseau referme."

  info "Dechargement complet, pour forcer un vrai rechargement..."
  "$LMS" unload --all >/dev/null 2>&1
  phase_tester

  titre "Montage valide -- la suite"
  info "Cote oneiros (~/.claude/oneiros/config.json) :"
  info '  "local_base_url": "http://192.168.1.50:1235",'
  info '  "dream_model": "brain"'
  info ""
  info "Sur le Mac :        python3 bridge/server.py"
  info "Depuis Windows :    python3 tests/test_bridge.py --live"
}

# --------------------------------------------------------------------------- #

preflight

case "${1:-}" in
  avant) phase_avant ;;
  recuperer) phase_recuperer ;;
  tester) phase_tester ;;
  apres) phase_apres ;;
  *)
    printf 'Usage : %s {avant|recuperer|tester|apres}\n\n' "$0"
    printf '  avant      phase 0, hors ligne : point de repere avant toute fenetre\n'
    printf '  recuperer  phase 1, fenetre OUVERTE : le moteur, puis les poids\n'
    printf '  tester     les 5 blocs -- le test qui tranche\n'
    printf '  apres      phase 2 : refermeture verifiee, puis tester a nouveau\n\n'
    printf 'Profil : %s -> %s (contexte %s)\n' "$PROFIL" "$CLE" "$CTX"
    exit 2
    ;;
esac
