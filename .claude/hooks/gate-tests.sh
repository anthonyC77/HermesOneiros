#!/bin/sh
# Porte de sortie du codeur — SubagentStop (settings.json, matcher codeur).
# Refuse la fin de tâche tant que les tests sont rouges. 1 exécution par passage.
# Sortie 0 = peut s'arrêter, 2 = continue (stderr renvoyé à l'agent).
# [hypothèse à tester — LIVRABLE.md, test n°1] : le code 2 sur SubagentStop bloque
# l'arrêt. Si le test échoue : déplacer ce hook dans le frontmatter de codeur.md
# sous `hooks.Stop`.

PY=$(command -v python 2>/dev/null || command -v python3 2>/dev/null)
[ -z "$PY" ] && exit 0
PYTHONIOENCODING=utf-8; export PYTHONIOENCODING
HOOK_INPUT=$(cat); export HOOK_INPUT

ACTIVE=$("$PY" -c "import json,os;print(json.loads(os.environ.get('HOOK_INPUT') or '{}').get('stop_hook_active') or False)")
[ "$ACTIVE" = "True" ] && exit 0            # anti-boucle : on ne re-bloque pas un second arrêt
AGENT=$("$PY" -c "import json,os;d=json.loads(os.environ.get('HOOK_INPUT') or '{}');print(d.get('agent_type') or d.get('agent_name') or '')")
[ -n "$AGENT" ] && [ "$AGENT" != "codeur" ] && exit 0

cd "$CLAUDE_PROJECT_DIR" || exit 0
CHANGED=$( { git diff --name-only HEAD 2>/dev/null; git ls-files --others --exclude-standard 2>/dev/null; } | grep '^oneiros/.*\.py$' )
[ -z "$CHANGED" ] && exit 0

LOG=$(mktemp)
if ! (cd oneiros && "$PY" -m pytest -q >"$LOG" 2>&1); then
  echo "TESTS ROUGES. Extrait :" >&2
  grep -E '^(FAILED|ERROR)|assert|Error' "$LOG" | head -20 >&2
  tail -3 "$LOG" >&2
  rm -f "$LOG"; exit 2
fi
rm -f "$LOG"
exit 0
