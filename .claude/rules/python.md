---
paths:
  - "oneiros/src/**/*.py"
  - "oneiros/tests/**/*.py"
  - "oneiros/plugin/**/*.py"
---
# Python — les règles qui surprennent (le reste est standard)
- Code, docstrings, commentaires et tests en **anglais**. Les trois documents sont en **français**. On ne mélange jamais les deux dans un même fichier.
- Un test ne touche jamais le vrai `~/.claude` : la fixture autouse `isolated_state` de `tests/conftest.py` redirige l'état et remet à zéro l'instantané mémoire des deux côtés du `yield`. Un test qui a besoin d'un autre état le construit sous `tmp_path`, jamais en désactivant la fixture.
- `sessions/reader.py` ne lève **jamais** sur une entrée malformée. Le format des transcripts appartient au harness et change sans préavis ; un lecteur qui jette sur une ligne fait tomber tout l'index. Les *entrées* d'outil sont indexées, les résultats non ; les entrées sidechain et meta sont ignorées.
- `memory/guard.py` privilégie la précision au rappel. Tous les motifs sont au niveau de la phrase, pour que `ignore`, `system` ou un chemin de clé privée restent du contenu ordinaire dans une note technique. On n'élargit un motif qu'avec le test qui montre le faux positif qu'il ne crée pas.
- Un dépassement de la mémoire **lève** ; rien n'est jamais évincé. `MemoryFull` porte les entrées courantes pour que l'agent consolide et réessaie dans le même tour.
- Toute mutation du store est en deux temps : `Store.plan()` valide et calcule sans toucher au disque, `Store.commit()` écrit. C'est ce qui permet à la porte d'afficher un vrai diff pour une écriture qu'elle n'a pas appliquée. Les entrées se désignent par sous-chaîne **unique** ; une correspondance ambiguë est une erreur, jamais un choix.
- `python -m oneiros`, jamais le script `oneiros` : pip ne sait pas écrire le shim exécutable sur cette machine, le script n'est pas sur le PATH alors que le paquet s'importe. À garder en tête avant de conclure qu'une commande du plugin est cassée.
- `python`, jamais `python3` : ici `python3` ne pointe que sur le stub du Windows Store.
