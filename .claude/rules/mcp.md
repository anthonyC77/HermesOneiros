---
paths:
  - "oneiros/src/oneiros/mcp_server.py"
  - "oneiros/src/oneiros/config.py"
  - "oneiros/src/oneiros/sessions/query.py"
---
# Le serveur MCP — la duplication est voulue, et elle a un prix
- `mcp_server.py` **n'importe rien de `oneiros`**. Le harness peut le lancer sous un interpréteur qui n'a jamais vu l'installation. Il duplique donc la résolution du répertoire d'état et la traduction de requête FTS5 ; des tests vérifient que les deux copies sont d'accord.
- Conséquence directe : une modification de `config.state_dir()` ou de `sessions/query.build_match()` modifie `mcp_server.py` **au même commit**. Un diff qui touche l'un sans l'autre est incomplet, même si les tests passent en local. Idem pour `plugin/hooks/_state.py`, qui duplique le même ordre de résolution mot pour mot.
- Enregistrement **par chemin de fichier**, jamais `-m`. Les deux formes se ressemblent et ne le sont pas : `-m` exige le paquet sur le chemin d'import, précisément ce dont le serveur est écrit pour ne pas dépendre. La forme `-m` marche jusqu'au jour où le harness choisit un autre interpréteur, et échoue alors sur une erreur d'import que personne ne relie à cette ligne. `doctor` la signale.
