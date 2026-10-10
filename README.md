# Oneiros

**En bref.** Un agent qui apprend de ses sessions : une mémoire triée plutôt qu'écrite en vrac, le rappel des sessions passées et, à terme, une passe de « rêve » qui consolide ce qui a été appris. Oneiros s'appuie sur Claude Code pour la boucle d'agent, les outils, les skills et les hooks, et n'écrit que ce qui manque.

Le cahier des charges reprend les capacités documentées d'[hermes-agent](https://github.com/NousResearch/hermes-agent) (Nous Research). Aucune ligne de son code n'est reprise.

Écrit avec Claude Code. Licence MIT.

## État

| Lot | Contenu | État |
|---|---|---|
| L0 | projet, chemins, configuration, commande `doctor` | fait |
| L1 | mémoire triée : bornes, filtre de sécurité des entrées, file d'approbation, instantané | fait |
| L1+ | hook `SessionStart` qui injecte l'instantané dans une session | fait |
| L2 | index des sessions (SQLite FTS5), traduction de requête, serveur MCP | fait |
| L3 | skills : registre, télémétrie, cycle de vie, retour arrière | pas commencé |
| L4 | pilotage par le Claude Agent SDK, revue après chaque tour | pas commencé |
| L5–L6 | rêve : consolidation, quarantaine, test au réveil | pas commencé |

Le filtre de sécurité existe parce qu'une entrée de mémoire est injectée dans le prompt système : tout ce qui peut écrire en mémoire peut donc écrire des instructions. Une écriture automatique part en file d'attente et attend une approbation.

## Utilisation

Dans une session Claude Code :

```
/remember je préfère pytest à unittest
/memory pending
/sessions pourquoi avons-nous abandonné le cache redis
```

En ligne de commande :

```bash
oneiros doctor
oneiros sessions index
oneiros sessions search "pool de connexions"
oneiros memory show
```

## Pour aller plus loin

- [oneiros/README.md](oneiros/README.md) : installation et configuration (en anglais)
- [oneiros/SPEC.md](oneiros/SPEC.md) : la spécification fonctionnelle
- [oneiros/TASKS.md](oneiros/TASKS.md) : le découpage en 36 tâches et 7 lots
