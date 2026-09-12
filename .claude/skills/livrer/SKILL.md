---
name: livrer
description: Orchestre l'exécution d'un plan de vagues validé (testeur, codeur, relecteur) avec arrêt aux portes humaines ; à utiliser pour "livre le plan", "lance la vague", "exécute les tâches", "déroule le lot".
disable-model-invocation: true
argument-hint: "[.claude/plans/<lot>.md]"
---

Livraison de $ARGUMENTS. Tu es l'orchestrateur ; tu n'écris ni test ni code toi-même. Parallélise à l'intérieur d'une vague, avance d'une vague à la fois.

1. Lis le plan. Une tâche est éligible quand toutes ses dépendances sont `done` et fusionnées. Plafond 5 par vague ; au-delà, coupe par ordre d'id.
2. Pour chaque tâche de la vague, en parallèle : `status: in_progress` dans le plan, branche `task/<id>` depuis l'intégration, puis `testeur` avec l'id de la tâche et la branche.
3. Porte humaine A (relecture inversée) : affiche `id → clause → nom du test` pour toute la vague, une seule fois. Arrête-toi. Attends une réponse explicite — c'est la seule chose que l'humain relit à la place du code.
4. Pour chaque tâche validée, en parallèle : `codeur` sur la branche, puis `relecteur`. `TEST_CONTESTÉ` / `BLOQUÉ` / `SPEC_INCOMPLÈTE` : `status: blocked`, sans arrêter les autres.
5. Fin de vague : pour chaque `MERGEABLE`, merge sur l'intégration puis `cd oneiros && python -m pytest` sur l'intégration. Un merge qui casse repasse la tâche en `blocked` avec diagnostic ; les autres passent `done`.
6. Si la vague a touché aux hooks ou aux garde-fous, `python .claude/hooks/test_hooks.py` doit sortir 0. Si elle a touché au câblage (chemins, plugin, MCP), `python -m oneiros doctor` doit rester vert. Une régression est bloquante.
7. Porte humaine B : `git diff --stat` de l'intégration, verdicts, résultat de la suite, liste des `blocked`. Arrête-toi. Ne commite rien sur la branche principale.
8. Vague suivante seulement après accord explicite. Une seule modification du harnais par cycle, jamais au milieu d'une vague.
