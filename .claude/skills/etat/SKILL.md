---
name: etat
description: Dit où en est oneiros — ce qui est câblé, ce qui manque, quel lot est en cours — et la plus petite action qui fait avancer ; à utiliser pour "on en est où", "qu'est-ce qui bloque", "peut-on passer au lot suivant".
disable-model-invocation: true
argument-hint: "[lot]"
---

1. `cd oneiros && python -m oneiros doctor` : ce qui est câblé et ce qui manque, chaque manque avec la commande qui le corrige. Code non-zéro = il manque quelque chose ; rapporte-le, ne le contourne pas.
2. `cd oneiros && python -m pytest -q` pour la suite, `python .claude/hooks/test_hooks.py` pour les garde-fous. Les deux sortent 0 ou tu commences par là.
3. Le tableau des lots du README dit ce qui est fait. Règle du tronc : on ne commence pas le lot suivant avant que le courant soit fait, et **L3.4 avant L5 sans exception**.
4. Si le lot courant n'est pas fait, la seule proposition valable est la plus petite action qui fait passer une ligne de `doctor` au vert ou une tâche à l'état fait. Un lot non franchi rétrécit, il ne rallonge pas.
5. Une décision par cycle : propose-en une, pas trois.
6. Arrêt : le lot courant, les manques avec la commande qui les vérifie, la décision proposée. Rien d'autre.
