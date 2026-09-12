---
paths:
  - "oneiros/SPEC.md"
  - "oneiros/TASKS.md"
  - "oneiros/README.md"
---
# Les documents — français, et une seule source par affirmation
- La spec est le quoi ; le découpage porte T01–T36, groupées en lots L0–L6. Les deux sont en **français** : on garde cette langue en les éditant.
- Le code ne recopie pas la spec, il la cite par numéro (`SPEC.md E11`, `SPEC.md §5.3`, `TASKS.md T08`). Une clause recopiée dans un docstring est une clause qui divergera.
- Une tâche se lit ainsi : *Objectif* (ce qu'elle rend possible), *Livrable* (les fichiers), **Fait quand** (le test qui la clôt), *Dépend de*, *Taille*. C'est la ligne « Fait quand » qui fait foi, pas l'intention.
- **L3.4 précède L5 sans exception** : aucune passe automatique mutante ne tourne avant que l'annulation existe.
- Aucun code d'Hermès n'entre dans `oneiros/`. Hermès fournit un document d'exigences — quelles capacités existent, quels arbitrages elles imposent, quels pièges elles rencontrent. Une référence à Hermès nomme un comportement documenté, jamais un module à porter.
- Ces trois fichiers sont en deny et derrière un hook : on ne les réécrit pas pour faire passer du code. Si la spec est fausse, on le dit et on s'arrête.
