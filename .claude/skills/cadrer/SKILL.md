---
name: cadrer
description: Prépare un lot (L3–L6) du découpage en plan de vagues exécutables — tâches éligibles, dépendances, branches — sans toucher au découpage lui-même ; à utiliser pour "cadre le lot L3", "prépare la prochaine vague", "par quoi on commence".
disable-model-invocation: true
argument-hint: "<lot> [contrainte en une phrase]"
---

Cadrage de $ARGUMENTS, dans la conversation principale (c'est ici que l'humain est).

Le découpage existe déjà — T01–T36, groupées en lots L0–L6. Tu ne le réécris pas : il est en deny et un hook te bloque. Tu produis le plan d'exécution qui en découle.

1. Lis les tâches du lot demandé et leurs `Dépend de`. Une tâche est éligible quand toutes ses dépendances sont faites et fusionnées.
2. Ordonne en vagues de ≤ 5 tâches sans dépendance mutuelle. Respecte l'ordre des lots, et **L3.4 avant L5 sans exception** : aucune passe automatique mutante ne tourne avant que l'annulation existe.
3. Pour chaque tâche : la ligne « Fait quand » recopiée telle quelle (c'est le contrat du testeur), le *Livrable* (c'est le périmètre du codeur et du relecteur), la branche `task/<id>`.
4. Si une ligne « Fait quand » n'est pas testable telle quelle, dis-le au lieu de l'interpréter. Corriger le découpage est une décision humaine, pas une reformulation.
5. Écris `.claude/plans/<lot>.md` : tableau id / titre / dépend de / statut / branche, puis les vagues.
6. Porte humaine 1 : affiche le plan, arrête-toi, attends un accord explicite. Pas de code avant.
