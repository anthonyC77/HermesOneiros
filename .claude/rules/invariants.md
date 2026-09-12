---
paths:
  - "oneiros/src/oneiros/memory/**"
  - "oneiros/src/oneiros/sessions/**"
  - "oneiros/plugin/hooks/**"
---
# Les deux invariants — ils ne se négocient pas dans un diff
- **Le cache de prompt est sacré.** Rien ne mute le contexte passé ni le prompt système en cours de conversation. `memory/render.py` capture la mémoire **une fois** par session et rend ensuite toujours le même instantané figé ; `capture(force=True)` existe pour les tests et les frontières de session, pas comme bouton de rafraîchissement. Le coût accepté : une écriture arrive sur le disque tout de suite mais n'est visible dans le prompt qu'à la session *n+1*. Le bloc mémoire est **ajouté** au préréglage du harness, jamais substitué.
- **Un fait ne se rêve pas.** La passe de rêve n'a aucun chemin d'écriture vers la mémoire — à faire respecter par un test qui parcourt le graphe d'appel, pas par une consigne de prompt. Une procédure peut être rêvée parce qu'elle peut être testée ; un fait rêvé est indiscernable d'une affabulation et serait rejoué dans toutes les sessions suivantes. `Origin` dans `memory/gate.py` a `NREM` et délibérément aucun membre REM : ajouter ce membre casse l'invariant, quel que soit le reste du diff.
- **La porte range par origine, pas par réglage.** C'est `Origin.is_automatic` qui décide ; une écriture automatique est mise en attente quoi que dise `memory_gate`. Le réglage existe pour qu'un utilisateur *durcisse* les écritures de premier plan, jamais pour qu'une passe non surveillée se relâche elle-même. L'approbation **replanifie contre le store courant** au lieu de rejouer le résultat enregistré : la mémoire a pu bouger depuis la mise en attente.
- Deux répertoires ne sont pas à nous. Celui des skills appartient au harness et n'est écrit que sélectivement ; celui des transcripts est une entrée en lecture seule qui n'est **jamais créée** — la créer ferait ressembler une mauvaise configuration à un historique vide.
