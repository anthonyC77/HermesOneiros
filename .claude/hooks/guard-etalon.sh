#!/bin/sh
# Garde-fou global — PreToolUse sur Edit|Write|MultiEdit|NotebookEdit|Bash (settings.json).
# Principe (inchangé depuis Horus) : une action dangereuse empêchée uniquement par
# le prompt n'est pas empêchée. Seul l'objet change — ici, ce sont les deux
# étalons d'oneiros et les répertoires qu'il ne possède pas.
#
# 1. SPEC.md / TASKS.md : on ne réécrit pas la spec pour faire passer du code.
# 2. Le vrai ~/.claude : cinq préfixes seulement, ceux qu'oneiros possède ou
#    doit laisser tranquilles. Le reste (settings.json, agents/, commands/ de
#    l'utilisateur) reste éditable — un garde-fou qui bloque du travail légitime
#    entraîne à approuver en aveugle, ce qui coûte plus qu'il ne rapporte.
#    Même exigence côté Bash : l'étalon doit être la CIBLE d'une écriture, pas
#    une chaîne mentionnée au passage dans un heredoc.
# Sortie 0 = autorisé, 2 = bloqué (stderr renvoyé à l'agent).

PY=$(command -v python 2>/dev/null || command -v python3 2>/dev/null)
[ -z "$PY" ] && exit 0                      # pas d'interpréteur : on ne bloque pas à l'aveugle
PYTHONIOENCODING=utf-8; export PYTHONIOENCODING
HOOK_INPUT=$(cat); export HOOK_INPUT

"$PY" - <<'PY'
import json, os, re, sys
from pathlib import Path

try:
    data = json.loads(os.environ.get("HOOK_INPUT") or "{}")
except ValueError:
    sys.exit(0)                              # entrée illisible : on laisse passer
tool = data.get("tool_name") or ""
args = data.get("tool_input") or {}
project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or ".").resolve()
claude_home = Path.home() / ".claude"

# Ce qu'oneiros possède sous le vrai ~/.claude, ou ce qu'il ne doit pas créer.
OWNED = {
    "oneiros": "l'état d'oneiros — passe par la CLI (python -m oneiros memory add …) "
               "ou déplace-le avec ONEIROS_HOME",
    "oneiros.env": "le fichier de secrets — il ne s'édite pas depuis une session",
    "projects": "l'historique de sessions est une entrée en LECTURE SEULE et n'est "
                "JAMAIS créé : le créer fait ressembler une mauvaise configuration "
                "à un historique vide",
    "skills": "ce répertoire appartient au harness ; oneiros y écrit sélectivement, "
              "par le code, jamais à la main",
    "plugins": "édite le plugin dans le dépôt (oneiros/plugin/), pas à travers la "
               "jonction — c'est le même fichier sous deux noms",
}
ETALON = ("oneiros/SPEC.md", "oneiros/TASKS.md")
ETALON_RE = r"oneiros/(spec|tasks)[.]md"


def refuse(msg):
    sys.stderr.write("BLOQUÉ : " + msg + "\n")
    sys.exit(2)


def relative(raw):
    """Chemin relatif au projet, ou None s'il est hors du projet."""
    try:
        p = Path(raw).expanduser()
        p = p if p.is_absolute() else (project / p)
        return p.resolve().relative_to(project).as_posix()
    except (ValueError, OSError):
        return None


def owned_prefix(raw):
    """Le préfixe possédé sous le vrai ~/.claude, ou None."""
    try:
        p = Path(raw).expanduser()
        p = p if p.is_absolute() else (project / p)
        p = p.resolve()
        if p == project or project in p.parents:
            return None                      # dans le dépôt : c'est du source
        rel = p.relative_to(claude_home).parts
    except (ValueError, OSError):
        return None
    return rel[0] if rel and rel[0] in OWNED else None


if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
    raw = args.get("file_path") or args.get("path") or ""
    if not raw:
        sys.exit(0)
    if relative(raw) in ETALON:
        refuse(relative(raw) + " est l'étalon. Le code se plie à la spec, jamais "
               "l'inverse. Si la spec est fausse, dis-le et arrête-toi.")
    owned = owned_prefix(raw)
    if owned:
        refuse("~/.claude/" + owned + " : " + OWNED[owned] + ".")
    sys.exit(0)

if tool == "Bash":
    cmd = args.get("command") or ""
    low = cmd.replace(chr(92), "/").lower()
    # L'étalon doit être la cible : après une redirection, ou en argument d'une
    # commande mutante. Le mentionner dans du texte ne déclenche rien.
    redirect = re.search(r"(^|[|;&\s])>>?\s*[\"']?[.]?/?" + ETALON_RE, low)
    mutator = re.search(r"\b(sed\s+-i|tee|cp|mv|rm|truncate|dd)\b[^|;&\n]*" + ETALON_RE, low)
    inline = re.search(r"python3?\s+-c\b[^|;&\n]*" + ETALON_RE, low) and re.search(
        r"(open\(|write_text|[.]write\()", low)
    if redirect or mutator or inline:
        refuse("commande qui écrit dans un étalon : " + cmd)

    # Le .claude du dépôt est du source ; celui du HOME est l'état de l'utilisateur.
    home_norm = str(claude_home).replace(chr(92), "/").lower()
    targets_home = home_norm in low or "~/.claude" in low or "$home/.claude" in low
    creates = re.search(r"\b(mkdir|new-item)\b[^|;&\n]*[.]claude/projects", low)
    if creates:
        refuse("créer le répertoire des transcripts fait ressembler une mauvaise "
               "configuration à un historique vide. Ne le crée pas ; dis que "
               "l'historique est absent.")
    if re.search(r"\brm\s+-[a-z]*r", low) and targets_home:
        refuse("suppression récursive sous le vrai ~/.claude : " + cmd)
    # pytest doit tourner sur un état jetable ; la fixture isolated_state s'en
    # charge, mais un ONEIROS_HOME exporté vers le vrai état la court-circuite.
    # Une affectation réelle, pas une mention en prose : la valeur doit pointer
    # sur le vrai répertoire de l'utilisateur.
    assign = re.search(r"oneiros_home\s*=\s*[\"']?([^\s\"';|&]+)", low)
    if assign and (home_norm in assign.group(1) or assign.group(1).startswith("~/.claude")):
        refuse("ONEIROS_HOME pointé vers le vrai répertoire d'état : les tests "
               "écriraient dans ta mémoire réelle. Utilise un répertoire temporaire.")
sys.exit(0)
PY
