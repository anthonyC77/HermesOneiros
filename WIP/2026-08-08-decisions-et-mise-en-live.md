# Oneiros — décisions du 8 août 2026 et mise en live

**Statut** : note de travail, rien n'est encore codé.
**Entrée précédente** : [hermes-onirique-mode-hypersensible.md](hermes-onirique-mode-hypersensible.md) (v0.1, 7 août).
**À faire de ce document** : les parties 1 à 3 alimentent une v0.2 de la note et
des amendements à [SPEC.md](../oneiros/SPEC.md) / [TASKS.md](../oneiros/TASKS.md).
La partie 4 est opérationnelle et exécutable dès demain.

---

# Partie 1 — La voie vigile (ex « mode hypersensible »)

## 1.1 Verdict

Intégrable, à hauteur d'environ un tiers de la note, et à une condition qui
change sa nature.

## 1.2 La reformulation qui débloque tout

> **La voie vigile n'écrit rien en mémoire. Elle a le droit de poser une
> question à une frontière de tour. C'est tout.**
>
> Si l'utilisateur répond, sa réponse est une écriture premier plan ordinaire,
> écrite avec ses mots à lui.

Dans la note v0.1, le signal faible gradue : il traverse une quarantaine et
devient une entrée mémoire. Il faut alors juger de la fiabilité d'une inférence
sur une personne, arbitrer un double passage par le gate, et défendre pourquoi
E14 interdit à REM d'écrire un fait mais autoriserait la vigie à écrire une
inférence.

Avec la reformulation, le problème disparaît : **le détecteur n'est jamais
l'auteur de l'entrée**. Il ne produit pas une hypothèse à valider, il produit une
question à poser.

Conséquences :

- Le test qui parcourt le graphe d'appel pour E14 s'étend tel quel : aucun
  chemin de `vigil/` vers `Store.commit`.
- Disparaissent : le compteur de corroboration, la date de péremption sur des
  faits, la règle de graduation à calibrer.
- Une question mal posée coûte une question. Un fait faux en mémoire coûte
  toutes les sessions suivantes.

## 1.3 Ce qui entre, se transforme, ou sort

| Section de la note | Décision |
|---|---|
| §3 dissonance | **Entre.** Lecture du journal de contradictions d'E12, gratuit une fois L5 posé. |
| §3 silence | **Entre.** Sur l'index FTS5 de L2, lexical, sans LLM. |
| §3 surprise / distance au manifold | **Transformé.** Ni `-log p`, ni embedding — voir 1.5. |
| §3 marqueurs de rupture, §7.1 signaux comportementaux | **Entre**, en second temps. Compteurs déterministes sur hooks. |
| §4 quarantaine + graduation | **Transformé.** File de questions sous budget, pas file de faits en attente. |
| §5.1 apophénie | **Entre**, avec méthode de calcul — voir 1.7. |
| §5.2 injection | **Entre, durci.** Provenance de canal, pas filtrage de contenu — voir 1.6. |
| §5.3 intrusion | **Entre.** « Remonte, n'agit jamais » est déjà la posture du gate. |
| §6 budget | **Entre.** Démarrer à **1/jour**, pas 3. |
| §9 étage 2 instrumental | **Reporté** en phase 3, même canal technique. |
| §10 pacte à froid | **Entre en phase 3**, sous forme de fichier de config. |
| §7.2 prosodie, §7.3 VFC, §8 thermostat, §9 étage 1 ambiant | **Sortent.** Pas de surface d'affichage, pas de capteur, invariant I2. |
| §11 juridique | **Devient un test**, pas un chapitre — voir 1.9. |

## 1.4 Correction au §2 de la note

Le diagnostic est juste, la cause est fausse. Le scoring pondéré du §2
(pertinence 0,30, fréquence 0,24, seuils durs) appartient à OpenClaw. Oneiros
n'en a pas : `SPEC.md §5.3` décrit CONSOLIDATE comme « fusion des redondances,
résolution des contradictions, retour sous plafond », et E3 fait remonter la
saturation à l'agent sous forme d'erreur listant les entrées.

Donc : **le trou existe, mais pour une autre raison.** Un LLM à qui on demande de
repasser sous 2 200 caractères coupera la remarque vue une fois — elle a l'air
anecdotique. Il n'y a pas de scoring à inverser. Reformuler en termes de ce qui
existe : *la passe de consolidation garde ce qui se répète, la voie vigile garde
ce qui est singulier.* Sinon on devra d'abord **ajouter** un scoring fréquentiel
à NREM juste pour pouvoir l'inverser — augmentation de périmètre non voulue.

## 1.5 Où ça vit, et avec quels détecteurs

Pas un quatrième runner. `SPEC.md §6` en a trois parce qu'ils diffèrent par ce
qu'ils ont le droit d'écrire ; la vigie n'écrit rien et n'appelle aucun modèle.
L'ordre de préférence d'I2 la place à `hook + extension de l'existant`.

```
src/oneiros/vigil/
  detect.py    détecteurs déterministes, aucun LLM
  queue.py     file de questions : sujet, support, confiance, péremption
  budget.py    plafond quotidien, plancher d'hypothèse nulle, auto-régulation
plugin/hooks/  UserPromptSubmit : compteurs en entrée, remontée en sortie
```

Trois sources, une sortie :

- **l'index FTS5** (L2, fait) → silence, sujets abandonnés ;
- **le journal de consolidation** (E12, à venir) → dissonance ;
- **les événements de hook** (plomberie livrée par T26) → reformulations,
  `Ctrl-C`, durée, effondrement de longueur des messages.

La sortie est un **ajout** au tour suivant via `UserPromptSubmit`, jamais une
réécriture. Même geste que l'injection du bloc mémoire : on ajoute au preset, on
ne substitue pas, on n'invalide pas le préfixe du cache. **I1 tient.**

**Scoring** : pas de score continu unique. Des détecteurs nommés, chacun avec sa
condition de déclenchement, son support et son taux de faux positifs mesurable
séparément. Un score agrégé est indébogable et c'est le chemin direct vers la
superstition du §5.1. Le classement forcé du §6 s'opère entre détecteurs, par un
ordre de priorité fixe.

**v0 = silence + dissonance seulement.** Les deux ont un substrat déjà construit
et aucun paramètre libre. Les compteurs comportementaux viennent après, parce
qu'ils ont chacun un seuil à calibrer et qu'on n'a rien pour les calibrer tant
que la boucle question/réponse ne tourne pas.

## 1.6 La règle à écrire en premier — provenance de canal

C'est le point le plus important de la note et celui qui n'a aucun équivalent
dans le code actuel.

> La vigie ne lit que des tours rédigés par l'utilisateur. Jamais une sortie
> d'outil, un contenu de fichier, une page récupérée, un retour de subagent,
> **ni un retour du second cerveau** (voir partie 3).

On élimine la classe entière au lieu de la filtrer. `guard.py` existe (E4) mais
screene du *contenu*, et privilégie volontairement la précision sur le rappel.
Ici il faut autre chose : le principe d'E10 (« provenance déclarée, jamais
inférée ») étendu des skills aux signaux.

`sessions/reader.py` sait déjà distinguer sidechain et meta, et n'indexe pas les
résultats d'outils — mais il indexe les *entrées* d'outils, qui ne sont pas de
l'utilisateur. Il faut donc que **le type de canal soit exposé**, pas seulement
utilisé pour filtrer à l'indexation. Petite modification de T11/T12, triviale à
prévoir maintenant, très pénible à rétro-ajouter.

## 1.7 Plancher d'hypothèse nulle — calculable

Réponse à la question ouverte du §13 (« comment calibrer sans corpus de
référence ») : **permuter l'histoire des sessions.** Mêmes termes, mêmes volumes,
tranches temporelles rebattues. Le nombre de « silences » que les détecteurs
trouvent sur cette version mélangée est le plancher de faux positifs, mesuré sur
les données de l'utilisateur lui-même.

Un détecteur qui produit autant de signaux sur l'histoire permutée que sur la
vraie est un générateur de bruit et ne sort pas.

Déterministe, hors ligne, sur l'index existant. C'est un critère d'acceptation
exécutable, pas un principe.

## 1.8 Budget et auto-régulation

Départ à **une question par jour**, pas trois. Les détecteurs de v0 sont
lexicaux et se tromperont ; trois erreurs par jour tuent le mode en une semaine,
ce que la note dit elle-même au §6. Le plafond monte quand le taux d'acceptation
le justifie, jamais l'inverse par défaut.

Trois issues observables — **acceptée / rejetée / ignorée** — et la distinction
compte : ignorée n'est pas rejetée, c'est un signal sur le moment plus que sur le
contenu.

**Ne pas construire un second registre.** La file du gate a déjà cette forme
(`submit` / `approve` / `reject` / `pending` dans `memory/gate.py`). L'élargir
plutôt que la dupliquer. Ça donne gratuitement le « reste tracé » du §4, seule
base honnête de calibrage. Ça répond aussi à la dernière question ouverte du
§13 : `SIGNALS.md` n'a pas à être un fichier exposé — c'est une file consultable
à la demande via une commande, jamais poussée.

## 1.9 Le vocabulaire comme test

Le §11.1 conclut que la frontière juridique est une frontière de vocabulaire de
sortie. Autant l'exécuter : un test qui assert qu'aucun gabarit de remontée ne
contient de label affectif, et que toute question posée est de la forme *fait
observable + incertitude sur sa propre utilité + main rendue* (§9 étage 3).

- « On a relancé ce test six fois en vingt minutes » → passe.
- « Tu sembles bloqué » → échoue.

**À garder même en usage strictement personnel.** Le §11.1 revendiquait une
convergence à trois pattes (respect, honnêteté épistémique, simplicité
juridique). En usage personnel on en retire une, il en reste deux, dont la seule
qui comptait vraiment : « tu es en colère » déduit d'une vitesse de frappe est
surtout **faux**. On ne le dit pas à cause d'un régulateur, on ne le dit pas
parce que ce n'est pas vrai.

## 1.10 Renommage

Abandonner « mode hypersensible » au profit de **`vigil` / voie vigile**.

La raison est de conception, pas juridique — l'argument juridique s'affaiblit
nettement en usage strictement personnel, et c'était le plus faible des deux.

Le nom « hypersensible » décrit un mécanisme que le projet n'a pas : il dit
*sensible à l'état de l'utilisateur*, alors que la chose *remarque ce qui n'est
arrivé qu'une fois et pose une question*. Le coût d'un nom qui décrit mal est
structurel et se paie à chaque décision suivante : il rend la prosodie
légitime alors qu'elle est en phase 5, il fait paraître le §7.1 central alors
qu'il est en phase 2, et il rend la graduation vers `MEMORY.md` naturelle alors
que c'est précisément ce qu'on a coupé.

## 1.11 Trois décisions qui appartiennent à l'auteur du projet

1. **La reformulation de 1.2.** C'est un changement de nature par rapport à la
   note. Si la graduation vers `MEMORY.md` est maintenue, tout le reste change,
   et il faut trancher explicitement pourquoi E14 s'applique à REM et pas ici.
2. **Silence + dissonance seulement en v0**, ou d'emblée les compteurs
   comportementaux du §7.1. Recommandation forte : les deux premiers, ils n'ont
   pas de seuil libre à deviner.
3. **La scission du document en deux produits** (phases 1–2 ici, phases 3–5
   ailleurs). Décision de portée, pas technique ; elle décide de ce que devient
   le §12.

---

# Partie 2 — Local vs frontière

## 2.1 Deux axes que « IA locale » confond

| Axe | Ce que ça change |
|---|---|
| **Où tourne le modèle** (local vs API frontière) | Rien ne sort de la machine : côté RGPD, décisif. Côté AI Act article 5, **aucun effet** — l'interdiction ne porte pas sur le lieu d'inférence. |
| **Qui l'utilise** (soi seul vs diffusé) | Décisif. En usage strictement personnel, exemption d'activité personnelle. Diffusé — même local, même open source — on devient fournisseur. |

Le §11.5 de la note le dit à sa dernière ligne : *« ce n'est pas le fait que ça
tourne en local qui exonère juridiquement, c'est l'usage personnel »*.

## 2.2 Pourquoi « local seulement » casserait oneiros

Claude Code est conçu pour parler à Claude. Interdire tout modèle frontière
revient à ne plus pouvoir utiliser Claude Code — donc à perdre la boucle
d'agent, le tool-calling, la compaction, le mécanisme des skills. Tout ce que
`SPEC.md §1` disait ne pas avoir à écrire.

Le projet passerait de « quatre choses à construire » à « quatre choses plus
toute l'infrastructure en dessous ». Ce n'est plus une évolution d'oneiros, c'est
un autre projet qui reprendrait sa spécification de mémoire.

*Nuance* : ce n'est pas techniquement impossible (des passerelles imitent l'API
de Claude et redirigent vers un modèle local), mais le vrai obstacle n'est pas la
plomberie — c'est qu'un modèle local de 8 B échoue régulièrement sur les
enchaînements d'outils que le harness enchaîne toute la journée.

## 2.3 Position intermédiaire tenable

| Runner | Quand | Qui attend | Modèle |
|---|---|---|---|
| Conversation | on lui parle | vous, en direct | **frontière** |
| Revue (E7) | après un échange | personne | local envisageable |
| Rêve (§5) | machine inactive | personne | local envisageable |

Les deux passes de fond n'ont pas d'urgence et **tout ce qu'elles produisent est
mis en attente de validation** avant de compter. Une erreur y coûte une
proposition rejetée. C'est le profil d'usage où un modèle local est acceptable —
et c'est là que passe l'essentiel de ce qui vous concerne personnellement.

`SPEC.md §6` avait entrouvert la porte sans penser au local : *« router une passe
vers un modèle moins cher est un arbitrage qui appartient à l'utilisateur »*. Un
endpoint local est ce même arbitrage poussé jusqu'au bout.

**Ce qui existe déjà** (relevé dans
[LIAISON_HERMES_MAC.md](../oneiros/LIAISON_HERMES_MAC.md), 8 août) et qui change
l'estimation :

| Fait mesuré | Conséquence pour oneiros |
|---|---|
| Endpoint OpenAI-compatible sur `192.168.1.50:1234`, opérationnel | La question « existe-t-il un endpoint local » est tranchée. Oui. |
| `Qwen3-Coder-30B-A3B-Instruct` MLX 4-bit, résident | 30 B, MoE à 3 B actifs. |
| **Tool calling vérifié** (`test_endpoint.py` bloc 3/4 : nom, JSON, schéma) | Lève mon objection principale du §2.2 — c'est *le* point où les modèles locaux échouent. |
| Génération 58–61 tok/s | Confortable. |
| **Prefill ~570 tok/s** | Le poste dominant, et le chiffre qui tranche. |

**Le prefill décide de la répartition, avec des nombres :**

- Passe de revue (E7) sur un digest de 20 K → **~35 s** de prefill. En arrière-plan, personne n'attend. Acceptable.
- Passe NREM rejouant 100 K de matériel de session → **~3 min**. Nocturne. Acceptable.
- Le même modèle en conversation → inutilisable dès que le contexte grossit.

Autrement dit, la mesure **confirme la répartition du tableau ci-dessus au lieu
de la contredire**. Ce n'est plus un pari.

**Coût réel restant** : plus « vérifier ce que le SDK accepte », mais un point
précis. LM Studio parle **OpenAI**, le SDK Claude parle **Anthropic Messages**.
Il manque un adaptateur entre les deux — c'est la seule pièce manquante, et elle
est maintenant pointée sur un endpoint déjà prouvé bon. Reste ensuite (2)
adapter le travail demandé : instructions plus courtes, tâches plus découpées,
plus de vérifications derrière.

*Réserve mineure* : c'est un modèle **Coder**, et la consolidation mémoire est un
travail de prose. Charger un second modèle pour ces passes est possible mais
coûteux en exploitation — voir le piège de la double instance et du TTL
(`LIAISON_HERMES_MAC.md` §4.5). Commencer avec celui qui est là.

**Et la voie vigile échappe entièrement au débat** : ses détecteurs v0 sont du
calcul ordinaire sur des fichiers. Aucun modèle, ni local ni distant.

---

# Partie 3 — Le second cerveau sur le Mac Studio

## 3.1 Le principe : séparer qui décide de qui lit

- **Claude Code orchestre** — décide quoi faire, dans quel ordre, quoi en
  conclure.
- **Le LLM local lit** — lui seul voit le contenu brut des notes.

```
     Vous
       │
  Claude Code  ◄── ne voit que : votre question + le résultat
       │
   ┌───┴──────────────────────┐
   │  outil « second cerveau »  │   ← la frontière
   └───┬──────────────────────┘
       │
   LLM local  ◄── voit le contenu brut
       │
  Mac Studio : notes, journaux, PDF
```

La frontière est un **serveur MCP** ou une simple commande. Oneiros en a déjà un
du même patron : `mcp_server.py` cherche dans les anciennes sessions et ne
renvoie que les correspondances.

## 3.2 L'ingest est le cas facile

Claude Code n'a rien à y faire au-delà de lancer la commande :

```
brain ingest ~/notes
→ « 1 247 fichiers traités, 18 ignorés, 6 min »
```

Il envoie l'ordre, il reçoit trois chiffres. Aucun fichier ne transite par lui.
Ça marche déjà aujourd'hui avec l'outil Bash.

## 3.3 La règle qui décide de tout : le contrat de retour

**L'architecture ne protège rien par elle-même. C'est le contrat de retour qui
protège.**

| Ce que renvoie l'outil | Effet |
|---|---|
| 40 extraits verbatim | Le corpus est dans le contexte. Frontière inutile. |
| « 3 notes, mars–mai 2026, thème récurrent : charge de travail » | Le corpus reste local. |
| Des identifiants + un décompte | Mieux encore — Claude sait qu'il y a matière sans savoir laquelle. |

Donc : **écrire le contrat de retour avant d'écrire l'outil.** Champs fixes,
longueur plafonnée, jamais de passe-plat.

**Et l'écrire côté Mac, pas côté client.** `LIAISON_HERMES_MAC.md` §1 pose
l'asymétrie fondatrice du montage : *« le plan de données fait sortir de
l'information du Mac, le plan de contrôle en fait entrer »*, et §10 conclut que
*« le port 1234 ne transporte que des tokens »*. C'est vrai — mais des tokens
peuvent être le corpus recopié mot pour mot. **Le plan de données est le chemin
de fuite du second cerveau**, et c'est justement celui qui n'a aucune
authentification parce qu'on le croyait inoffensif.

Un contrat de retour appliqué dans la configuration du client MCP est une
recommandation. Appliqué dans le serveur qui tourne sur le Mac, c'est une
frontière. La différence compte le jour où un tour d'agent demande « colle-moi le
texte intégral ».

## 3.4 L'index avant le modèle

La recherche plein texte — FTS5, celle qu'oneiros utilise déjà sur les sessions —
répond gratuitement, instantanément et de façon déterministe à « où ai-je parlé
de X », « quelles notes de mars mentionnent Y », « ce sujet apparaît-il encore ».
Zéro modèle, zéro GPU, zéro hallucination.

Le LLM local sert pour ce que la recherche ne sait pas faire : résumer, classer,
extraire, reformuler. Couche **au-dessus** d'un index, pas à la place.

Ordre : (1) index lexical sur le corpus ; (2) mesurer ce qui manque réellement ;
(3) ajouter le LLM local sur ces manques précis. Beaucoup de projets de second
cerveau mettent un modèle partout dès le départ et découvrent qu'ils ont rendu
lent, coûteux et flou ce que `grep` faisait bien.

## 3.5 Deux avertissements

**L'injection voyage dans les résumés.** Les notes contiennent du contenu copié
du web, des PDF, des mails — non fiable. Si le modèle local le lit et le résume,
une instruction malveillante peut traverser le résumé et arriver chez Claude,
qui a accès aux fichiers et au terminal. Le modèle local est un filtre **plus
faible**, pas plus fort. D'où : retours structurés (champs, identifiants,
décomptes) plutôt que texte libre partout où c'est possible. Et voir la règle
1.6 : ce qui revient du second cerveau est un canal non fiable, la vigie ne s'en
nourrit jamais.

**Ce n'est pas « Claude ne voit rien ».** Il voit vos questions, les noms
d'outils, les résultats renvoyés, souvent les chemins de fichiers. Or les
questions qu'on pose à son journal sont en elles-mêmes révélatrices. La frontière
protège le **corpus**, pas l'**usage**.

## 3.6 Où ça vit — pas dans oneiros

```
Claude Code
  ├── oneiros-sessions    (ce que l'agent a vécu)
  └── brain               (ce que vous avez écrit)
```

Deux serveurs MCP distincts sur le même harness. Oneiros garde sa taille de
guêpe, et le second cerveau reste utilisable même si oneiros est abandonné — ou
l'inverse.

**Un seul point de contact, et la règle la plus stricte : le second cerveau
n'écrit jamais dans la mémoire d'oneiros.** Il reste une ressource qu'on
interroge, comme l'index de sessions. Si un fait des notes mérite d'entrer en
mémoire, c'est vous qui le dites, en session, avec vos mots. Même règle que pour
le rêve et pour la vigie — un fait ne s'importe pas plus qu'il ne se rêve.

---

# Partie 4 — Mise en live d'oneiros

## 4.0 État vérifié au 8 août 2026

Sortie de `python -m oneiros doctor` :

```
[ok  ] state directory        C:\Users\antho\.claude\oneiros
[warn] config.json            absent — using defaults
[warn] memory/MEMORY.md       not written yet
[warn] memory/USER.md         not written yet
[ok  ] pending memory writes  none
[ok  ] harness transcripts    C:\Users\antho\.claude\projects
[warn] session index          empty — run: oneiros sessions index
[warn] plugin linked          not linked
[warn] MCP server             not registered
[ok  ] claude CLI             C:\Users\antho\.local\bin\claude.EXE
[warn] agent SDK              absent
```

Autres faits constatés :

- Le paquet **s'importe** correctement (`D:\HermesAnt\oneiros\src\oneiros`).
- **295 transcripts** attendent dans `~/.claude/projects`, index vide.
- La commande `oneiros` **n'est pas sur le PATH** (le shim n'a pas pu être
  écrit). Seul `python -m oneiros` fonctionne.
- `plugin/hooks/hooks.json` déclare `"hooks": {}` — normal, les handlers
  arrivent avec L3/L4/L5.

## 4.1 Le trou principal : la mémoire n'atteint pas le modèle — **comblé le 8 août**

> **Fait.** `plugin/hooks/session_start_memory.py` + `plugin/hooks/_state.py`,
> déclarés sur `SessionStart` (`startup|clear|compact`, jamais `resume`).
> 29 tests, suite complète à 236. Vérifié de bout en bout sur l'install réelle :
> une entrée écrite par `memory add` ressort dans `additionalContext`, et le gel
> par session tient — même `session_id` après une écriture ⇒ mêmes octets ;
> `session_id` différent ⇒ mémoire à jour.
>
> Le texte ci-dessous décrit le problème tel qu'il était, et reste la
> justification du dessin retenu.

`memory/render.py:capture()` n'est appelé que depuis `cli.py` (commande
`memory show`). **Rien n'injecte le snapshot mémoire dans une session vivante.**
L'injection était prévue via les runners du SDK (L4, non commencé).

Conséquence : en l'état, oneiros *stocke et cure* la mémoire, mais l'agent ne la
*voit* pas. La boucle est ouverte.

**Chemin le moins cher** : un hook `SessionStart` qui lit le snapshot et le
renvoie en contexte additionnel. C'est petit, et c'est exactement ce pour quoi
`render.py` est conçu — capture unique, ajout au démarrage, jamais de mutation
en cours de session. I1 est respecté par construction.

Contrainte à respecter : comme le hook du déclencheur de rêve (`SPEC.md §5.2`),
il tourne sous un interpréteur inconnu → **stdlib uniquement**, aucun import du
paquet, écritures atomiques, échec silencieux.

C'est la plus grosse valeur pour le plus petit effort de toute cette liste.

## 4.2 Étapes A — **faites le 8 août**

État de `doctor` après coup : tout au vert sauf `config.json` (absent, défauts),
et le SDK Agent (absent, il appartient à L4).

| Étape | État |
|---|---|
| A1 index de sessions | **fait** — 8 647 messages, 79 sessions, 14 projets |
| A2 plugin lié | **fait** — jonction `mklink /J`, sans élévation |
| A3 MCP enregistré | **fait** — par chemin de fichier, `settings.json` sauvegardé en `.bak-oneiros` |
| A4 commandes du plugin | **fait** — `python -m oneiros` dans le corps *et* le frontmatter |
| A5 hook mémoire | **fait** — voir 4.1 |
| A6 `config.json` | non fait, facultatif |

Un point resté ouvert : lors d'une première vérification du gel, une lecture a
montré une écriture de milieu de session visible après un `compact`. Non
reproduite en trois tentatives dont une verbatim, aucun code modifié
entre-temps. À re-tester en usage réel avant de considérer l'invariant comme
prouvé sur le terrain — les tests, eux, le couvrent.

Le détail des étapes, pour mémoire :

**A1. Construire l'index de sessions** (le plus rentable, aucun prérequis)

```
python -m oneiros sessions index
python -m oneiros sessions stats
python -m oneiros sessions search "second cerveau"
```

295 transcripts à traiter. Compter quelques minutes la première fois.

**A2. Lier le plugin**

```
mklink /D "%USERPROFILE%\.claude\plugins\oneiros" "D:\HermesAnt\oneiros\plugin"
```

Invite de commandes **élevée**, ou mode développeur Windows activé. À relancer
`doctor` après pour confirmer.

**A3. Enregistrer le serveur MCP — par chemin de fichier**

Dans `~/.claude/settings.json` :

```json
{
  "mcpServers": {
    "oneiros-sessions": {
      "command": "python",
      "args": ["D:\\HermesAnt\\oneiros\\src\\oneiros\\mcp_server.py"]
    }
  }
}
```

**Jamais `python -m oneiros.mcp_server`.** Le serveur est écrit pour ne rien
importer du paquet, précisément pour survivre à un interpréteur qui n'a jamais vu
l'install. `doctor` signale la forme `-m` si elle est utilisée.

**A4. Corriger les commandes du plugin** — *bug réel sur cette machine*

`plugin/commands/memory.md`, `remember.md`, `sessions.md` appellent `oneiros …`
en nu, y compris dans le frontmatter `allowed-tools: Bash(oneiros memory:*)`.
Comme le shim n'existe pas, **ces trois commandes échoueront**. Remplacer par
`python -m oneiros …` (corps **et** frontmatter).

**A5. Écrire le hook `SessionStart`** — voir 4.1. C'est ce qui ferme la boucle.

**A6. Optionnel** — `~/.claude/oneiros/config.json` si un défaut ne convient
pas ; tout a une valeur de travail, le fichier est facultatif.

Ordre recommandé : **A1 → A4 → A2 → A3 → A5.** A1 donne un résultat utile
immédiatement ; A4 avant A2 évite de lier un plugin dont les commandes échouent.

## 4.3 Ce qui existe réellement côté Mac

Source : [LIAISON_HERMES_MAC.md](../oneiros/LIAISON_HERMES_MAC.md), relevé du
8 août. **Trois machines, pas deux**, et **deux plans de liaison dont un seul
est posé.**

```
  PC Windows 10                    Mac M1 Ultra 64 Go — 192.168.1.50
  ├── Claude Code + oneiros ──────────▶ :1234  LM Studio (plan de données)
  │                          LAN        Qwen3-Coder-30B-A3B MLX 4-bit
  │                                     hors ligne, aucune route sortante
  └── VM Ubuntu (VMware, NAT)
      └── Hermes Agent ──────────────▶ :1234   idem
                                 ✗ ─── :22     plan de contrôle — NON POSÉ
```

| Plan | Port | Transporte | État |
|---|---|---|---|
| **Données** | 1234, HTTP OpenAI-compatible, sans authentification | des tokens | **opérationnel et mesuré** |
| **Contrôle** | 22, SSH, clés ed25519 + commande forcée | des commandes et des fichiers | **conçu, non posé** |

**Correction à ma recommandation d'hier.** Je proposais de « réutiliser la
liaison qui fonctionne déjà » pour brancher un serveur MCP en stdio par-dessus
SSH. **Cette liaison n'existe pas.** Ce qui fonctionne, c'est l'inférence HTTP.
Le SSH vers le Mac — comptes `hermes` / `opencode`, clés `mac_job` / `mac_sftp`,
trappe `hermes-job` — est intégralement en « conçu, non posé » (§9 du document).

Deux bonnes nouvelles quand même :

1. **Le PC atteint le Mac directement.** L'endpoint a été validé depuis Windows
   avant même que la VM existe (§6), et la table de diagnostic distingue
   explicitement « timeout depuis la VM, OK depuis Windows » (§8). Donc
   **oneiros n'a pas besoin de la VM** : PC → Mac sur le LAN, éprouvé.
2. **Le plan de contrôle conçu est meilleur que ce que je proposais.** Ma
   suggestion générique était `ssh hôte python3 serveur.py`. Leur montage prévoit
   une **commande forcée** dans `authorized_keys` — une clé qui ne peut lancer
   qu'un binaire précis, jamais un shell. Or MCP en stdio ne demande rien de
   plus qu'un processus qui parle JSON-RPC sur stdin/stdout : une commande forcée
   pointant sur le serveur du second cerveau est exactement ça, en strictement
   plus fermé. **La trappe `/Users/hermes/bin/hermes-job` est l'emplacement
   naturel du point d'entrée**, et le lieu où appliquer le contrat de retour
   de 3.3.

## 4.4 Étapes B — corrigées

**B0. Où tourne oneiros : sur le PC, tranché.** Claude Code est installé sur
Windows (`C:\Users\antho\.local\bin\claude.EXE`), son état vit dans
`~/.claude/oneiros`, ses transcripts dans `~/.claude/projects` — tous par
machine. Hermes-agent dans la VM est un **autre agent**, pas la même boucle ;
oneiros n'a rien à y faire. Ne pas dupliquer oneiros sur le Mac : deux
historiques et deux mémoires, sans mécanisme de fusion (une base FTS5 supporte
mal la synchro naïve par fichier).

**B1. Adaptateur Anthropic ↔ OpenAI** — la seule pièce manquante du plan de
données pour oneiros. L'endpoint est prouvé, le tool calling est prouvé ; il
manque la traduction de protocole. À faire **avant** tout le reste de la voie
locale, parce que tout en dépend et que c'est le seul point d'incertitude
technique restant.

**B2. Router les passes auxiliaires vers cet endpoint** (revue E7, puis NREM),
en gardant la conversation sur le modèle frontière. Voir les chiffres de prefill
en 2.3 — ils justifient la coupure au lieu de la subir.

**B3. Le second cerveau — bloqué en amont, pas par la liaison.** Trois choses
manquent avant de pouvoir indexer quoi que ce soit :

- le vault `/Users/Shared/SecondBrain` n'est pas créé ;
- le nom du sas d'entrée n'est pas tranché — `raw/` à un endroit, `Entree/` à
  l'autre, dans le même fichier (incohérence n° 1 du §9) ;
- *Session à distance* n'est pas activée sur le Mac, donc pas de port 22.

Tant que ces trois points tiennent, ni B4 ni B5 ne peuvent commencer. **C'est le
vrai chemin critique du second cerveau, et il n'a rien à voir avec la
technologie de liaison.**

**B4. Index lexical du corpus, sur le Mac.** Même patron que `sessions/index.py`.
Sans modèle. C'est le livrable qui rend mesurable ce qui manque ensuite.

**B5. Exposer en MCP, derrière la commande forcée**, avec le contrat de retour
de 3.3 **écrit avant les outils** et appliqué côté Mac.

**B6. Le LLM local sur le corpus en dernier**, seulement pour ce que l'index ne
sait pas faire.

## 4.5 Un point de sécurité qui nous concerne directement

Le §9 de `LIAISON_HERMES_MAC.md` signale que
`C:\Users\antho\.ssh\hermes_vm` est **sans passphrase**, et que tout agent
disposant d'un shell sur Windows ouvre donc la VM.

**Claude Code est un agent disposant d'un shell sur Windows.** Ce n'est pas une
remarque abstraite : c'est le chemin praticable aujourd'hui, depuis cette session
même. Et l'exposition s'aggrave dès que la VM portera une clé vers le Mac.

```powershell
ssh-keygen -p -f C:\Users\antho\.ssh\hermes_vm
```

Trente secondes, aucune dépendance, à faire avant B1.

---

# Partie 5 — À écrire dans SPEC.md / TASKS.md

1. **E22–E26 dans `SPEC.md`** : origine vigile sans droit d'écriture mémoire ;
   lecture restreinte aux canaux utilisateur ; remontée en ajout à une frontière
   de tour uniquement ; budget avec plancher d'hypothèse nulle ; interdiction du
   vocabulaire émotionnel.
2. **Un lot L7 dans `TASKS.md`**, placé **après L5** — la dissonance dépend du
   journal de consolidation, la plomberie de hooks vient de T26, et le registre
   d'issues est une extension du gate.
3. **Deux amendements à des tâches non écrites**, pénibles à rétro-ajouter :
   - T11/T12 → exposer le type de canal, pas seulement filtrer à l'indexation ;
   - T20 → prévoir que le journal des contradictions aura un second lecteur.
4. **v0.2 de la note** : corriger le §2 (1.4), acter la reformulation (1.2),
   renommer (1.10), scinder les phases 3–5 vers un autre produit.

---

# Reprendre demain

**D'abord, trente secondes** — la passphrase sur `hermes_vm` (4.5). Rien n'en
dépend, et c'est la seule ligne de cette note qui referme une porte ouverte.

Ensuite :

1. **A1** — `python -m oneiros sessions index`. Aucun prérequis, 295 transcripts
   deviennent interrogeables, résultat visible tout de suite.
2. **Trancher 1.11 décision n°1** (la vigie pose une question / ne gradue pas).
   Tout le reste de la partie 1 en dépend.
3. **A4 puis A2/A3** — corriger les trois commandes, lier le plugin, enregistrer
   le MCP. Ensuite seulement A5, le hook qui ferme la boucle mémoire.

Deux chantiers séparés ensuite, sans dépendance entre eux :

- **Voie locale** : B1, l'adaptateur Anthropic ↔ OpenAI. Seul point
  d'incertitude technique restant ; l'endpoint et le tool calling sont prouvés.
- **Second cerveau** : B3, débloquer le vault, le nom du sas et le port 22 sur
  le Mac. Chemin critique réel, indépendant de la technologie de liaison.

La partie 5 (SPEC/TASKS) puis L7 n'ont pas de raison de commencer avant que L5
existe.
