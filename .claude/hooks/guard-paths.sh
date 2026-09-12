#!/bin/sh
# Garde-fou de périmètre — PreToolUse (Read/Edit/Write) dans le frontmatter d'un agent.
# Usage : guard-paths.sh tests-only  -> testeur : écrit dans oneiros/tests/ ; lit la
#                                       tâche, la spec, les tests, la surface publique.
#                                       Pas oneiros/src/ : l'oracle s'écrit depuis la
#                                       spec, jamais depuis l'implémentation.
#         guard-paths.sh no-tests    -> codeur  : tout sauf oneiros/tests/ et les deux
#                                       documents étalons.
# Sortie 0 = autorisé, 2 = bloqué (stderr renvoyé à l'agent).
# Limite connue : ne couvre pas les écritures via Bash (sed -i, tee) — c'est
# guard-etalon.sh qui ferme cette porte pour SPEC.md et TASKS.md.

PY=$(command -v python 2>/dev/null || command -v python3 2>/dev/null)
[ -z "$PY" ] && exit 0
PYTHONIOENCODING=utf-8; export PYTHONIOENCODING
MODE="$1"; export MODE
HOOK_INPUT=$(cat); export HOOK_INPUT

"$PY" - <<'PY'
import json, os, sys
from pathlib import Path

try:
    data = json.loads(os.environ.get("HOOK_INPUT") or "{}")
except ValueError:
    sys.exit(0)
mode = os.environ.get("MODE") or ""
tool = data.get("tool_name") or ""
args = data.get("tool_input") or {}
project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or ".").resolve()

raw = args.get("file_path") or args.get("path") or ""
if not raw:
    sys.exit(0)
try:
    p = Path(raw).expanduser()
    p = p if p.is_absolute() else (project / p)
    rel = p.resolve().relative_to(project).as_posix()
except (ValueError, OSError):
    sys.exit(0)                              # hors projet : guard-etalon.sh s'en occupe


def under(*prefixes):
    return any(rel == q or rel.startswith(q + "/") for q in prefixes)


is_test = under("oneiros/tests")
is_impl = under("oneiros/src")
# Surface publique lisible par le testeur : ce qu'un appelant voit sans ouvrir
# l'implémentation. En Python il n'y a pas de répertoire Contracts/ — ce sont les
# __init__.py, la CLI déclarée et le manifeste du plugin.
is_public = rel.endswith("/__init__.py") or under("oneiros/plugin", "oneiros/pyproject.toml")
is_spec = under("oneiros/SPEC.md", "oneiros/TASKS.md", "oneiros/README.md", "docs")
is_write = tool in ("Edit", "Write", "MultiEdit", "NotebookEdit")


def refuse(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(2)


if mode == "tests-only":
    if is_write and not is_test:
        refuse(f"BLOQUÉ (testeur) : écriture hors oneiros/tests/ interdite : {rel}")
    if not is_write and is_impl and not is_public:
        refuse(f"BLOQUÉ (testeur) : lecture de l'implémentation interdite : {rel}. "
               "Écris l'oracle depuis la ligne « Fait quand » de la tâche et les "
               "clauses de SPEC.md, pas depuis le code.")
elif mode == "no-tests":
    if is_write and (is_test or is_spec):
        refuse(f"BLOQUÉ (codeur) : {rel} est hors périmètre. Si un test te semble "
               "faux, termine avec 'TEST_CONTESTÉ: <nom> — <raison>'.")
sys.exit(0)
PY
