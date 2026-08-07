# Oneiros — spécification fonctionnelle

Un agent qui apprend de ses sessions, entretient une mémoire persistante, et rêve.

- **Harness** : Claude Code (skills, hooks, mémoire fichier, subagents).
- **Pilotage** : Claude Agent SDK (`claude-agent-sdk`).
- **Cahier des charges** : les capacités de [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent),
  telles que décrites dans sa documentation utilisateur.

## R0 — Règle de projet

**Aucun code d'Hermès n'entre ici.** Hermès fournit un cahier des charges
fonctionnel : quelles capacités existent, quels arbitrages elles imposent, quels
pièges elles ont rencontrés. L'implémentation est écrite de zéro, pour ce
harness-ci. Toute référence à Hermès dans ce document désigne un comportement
observable documenté, jamais un module à porter.

---

## 1. Périmètre

Le harness fournit déjà la boucle d'agent, le tool-calling, la compaction, les
providers, les outils cœur, et le mécanisme des skills / hooks / subagents.
Rien de tout cela n'est réécrit.

Ce qui reste à construire est la **boucle d'apprentissage** :

1. une mémoire **curée** plutôt qu'écrite ;
2. des skills **entretenus** après création ;
3. un **rappel** inter-sessions ;
4. un **mode rêve** génératif.

---

## 2. Exigences dérivées d'Hermès

| Capacité Hermès (documentée) | Exigence |
|---|---|
| `MEMORY.md` / `USER.md`, bornés en caractères, injectés en snapshot gelé | **E1** mémoire bornée, deux cibles, snapshot gelé |
| Outil mémoire : add / replace / remove, matching par sous-chaîne, refus des doublons | **E2** l'agent écrit sa propre mémoire |
| Saturation → erreur explicite listant les entrées, jamais de compactage silencieux | **E3** saturation visible, consolidation dans le même tour |
| Scan anti-injection avant acceptation d'une entrée | **E4** la mémoire est du prompt système, traitée comme telle |
| Gate `write_approval` sur les écritures | **E5** validation configurable, stricte sur l'automatique |
| Recherche plein-texte SQLite FTS5 sur toutes les sessions | **E6** rappel inter-sessions sans coût LLM |
| Revue de fond post-tour qui écrit mémoire et skills | **E7** apprentissage en ligne |
| Cycle de vie `active → stale → archived`, jamais de suppression | **E8** entretien des skills, archivage réversible |
| Compteurs d'usage / vue / patch par skill | **E9** télémétrie, sinon on ne distingue pas porteur de mort |
| Provenance **déclarée**, jamais inférée | **E10** l'origine est une politique, pas une déduction |
| Snapshot avant chaque passe mutante, rollback réversible | **E11** toute passe automatique est annulable |
| Rapport machine + rapport humain par passe | **E12** journal auditable |
| Déclenchement à l'inactivité, jamais en cours de tour | **E13** passes hors session vivante |
| — (sans équivalent Hermès) | **E14–E21** mode rêve, §5 |

### Invariants

- **I1 — le cache de prompt par conversation est sacré.** Aucune mutation du
  contexte passé, aucun changement d'outillage ou de prompt système en cours de
  conversation. Toute passe d'apprentissage tourne dans un fork froid.
  Corollaire assumé : ce qui est appris en session *n* n'apparaît qu'en session
  *n+1*.
- **I2 — le cœur est une taille de guêpe.** Ordre de préférence : étendre
  l'existant → commande + skill → subagent → hook → serveur MCP → nouvel outil.

---

## 3. Mémoire

**E1.** Deux fichiers, deux plafonds. Entrées séparées par `§`, multi-lignes
autorisées. En-tête indiquant le remplissage (`67% — 1474/2200`) pour que l'agent
sache quand consolider.

| Fichier | Contenu | Plafond initial |
|---|---|---|
| `memory/MEMORY.md` | Environnement, conventions, leçons | 2 200 car. |
| `memory/USER.md` | Profil, préférences, style | 1 375 car. |

Plafonds à recalibrer (§8) : les valeurs d'Hermès sont taillées pour *son* prompt
système.

**Injection.** Bloc ajouté au preset `claude_code`, jamais en remplacement —
remplacer le preset fait perdre les consignes d'outillage du harness. Snapshot
capturé une seule fois au démarrage de session (I1).

**E2 / E3.** `add`, `replace`, `remove` ; les deux dernières par sous-chaîne
unique (erreur si la sous-chaîne matche plusieurs entrées). Doublon exact →
succès sans effet. Dépassement → **erreur** listant les entrées courantes ;
l'agent consolide puis réessaie dans le même tour. Jamais d'éviction silencieuse.

**E4.** Toute entrée est scannée avant acceptation : motifs d'injection de
prompt, exfiltration de secrets, Unicode invisible.

**E5.** Gate à trois états : `off` (tours au premier plan), `staged` (défaut pour
toute écriture automatique), `always`. Revue via `/memory pending`.

---

## 4. Rappel et skills

**E6 — index.** Base SQLite FTS5 sur les transcripts du harness. Incrémental
(taille + mtime), ignore les entrées sidechain et meta, indexe les *entrées*
d'outils mais pas leurs résultats. Une requête utilisateur brute n'est pas de la
syntaxe FTS5 valide : la traduction est obligatoire, pas optionnelle.

Frontière avec la mémoire : la mémoire porte les faits qui doivent **toujours**
être en contexte (~1 300 tokens, coût dans chaque prompt) ; l'index répond à
« on avait parlé de X quand ? » (illimité, zéro LLM, à la demande).

**E7 — apprentissage en ligne.** Après un tour, un fork froid rejoue la
conversation et décide s'il y a matière à persister : une correction répétée
devient une entrée mémoire, une procédure durable devient un skill. Sur un modèle
différent du principal, rejouer un **digest** (tours récents verbatim + résumé
des anciens) — le cache du modèle principal n'est de toute façon pas réutilisable.

**E8 / E9.** Télémétrie par skill : `use_count` (chargé dans un prompt),
`view_count` (consulté), `patch_count`, horodatages. Transitions **déterministes,
sans LLM** : `active` → (30 j sans usage) `stale` → (90 j) `archived`. Épinglés
exemptés. Un skill jamais utilisé bénéficie d'un plancher de grâce : zéro usage
est une absence de preuve, pas une preuve de futilité.

**E10 — provenance déclarée.** Un skill avec mille patchs prouve que l'agent le
*maintient*, pas qu'il l'a *écrit*. Une heuristique « ça ressemble à du généré »
finirait par archiver quelque chose d'écrit à la main. Champ `origin` explicite,
commande d'adoption pour transférer la juridiction.

**E11 / E12.** Archivage, jamais suppression. Snapshot avant chaque passe
mutante, rollback en une commande, rollback lui-même réversible. Un répertoire
horodaté par passe : rapport machine + rapport humain.

---

## 5. Dream mode

Le curator d'Hermès *consolide*. Ici le rêve **génère** : il rejoue le vécu,
s'invente des tâches qu'on ne lui a pas demandées, les résout, garde ce qui tient.
C'est la partie sans précédent — d'où la densité de garde-fous.

### 5.1 Le risque, et la ligne qui le contient

Un rêve produit du texte de la même forme qu'une expérience. Rien, dans un
`SKILL.md`, ne distingue une procédure éprouvée d'une procédure imaginée. Non
marqué, un artefact rêvé sera appliqué au réel avec la confiance qu'on accorde au
vécu. C'est le seul mode de défaillance qui rend la fonctionnalité nette négative.

> **E14 — Un fait ne se rêve pas. Seule une procédure se rêve.**
>
> Le mode rêve n'a **aucun droit d'écriture sur la mémoire**, ni direct, ni via
> proposition en attente. Une procédure peut être rêvée parce qu'elle est
> *testable*. Un fait rêvé — « l'utilisateur préfère X », « staging écoute sur
> 2222 » — est indiscernable d'une confabulation, et une fois en mémoire il est
> rejoué dans chaque session suivante.

La consolidation mémoire reste en phase **NREM**, qui ne génère rien : elle
fusionne, déduplique et élague des entrées issues du vécu.

### 5.2 Déclenchement (E13)

```
SessionStart ──▶ due ?
                 ├─ variable de garde définie ?     → abandon (récursion)
                 ├─ dans un subagent ?              → abandon (fan-out ×N)
                 ├─ idle < seuil ?                  → abandon
                 ├─ dernière passe < intervalle ?   → abandon
                 ├─ verrou exclusif non acquis ?    → abandon
                 └─ sinon → spawn détaché
```

Chaque garde couvre un cas que les autres ne couvrent pas. Le verrou n'est pas
relâché sur le chemin nominal : c'est l'horodatage de dernière passe qui
supprime le re-spawn pendant l'intervalle ; le verrou expire seul.

Le hook est un sous-processus lancé sous un interpréteur inconnu : **stdlib
uniquement**, aucun import du paquet applicatif, écritures atomiques, sortie
silencieuse en cas d'erreur.

### 5.3 NREM — consolidation

Tourne toujours. Ne génère rien.

1. **REPLAY** — sessions depuis le dernier rêve, via l'index.
2. **CONSOLIDATE** — fusion des redondances, résolution des contradictions
   (la plus récente gagne, l'ancienne est journalisée), retour sous plafond.
3. **PRUNE** — transitions de cycle de vie des skills (E8).
4. **JOURNAL**.

Écritures mémoire en `staged` : proposées, pas appliquées.

### 5.4 REM — exploration générative

Opt-in, bornée, sandboxée.

```
SEED      extrait de l'index : fichiers récemment touchés, échecs récurrents,
          outils qui ont raté, sujets abordés sans conclusion
IMAGINE   génère N tâches plausibles adjacentes au vécu
REHEARSE  résout chaque tâche en sandbox isolé
HARVEST   ne retient que ce qui produit une procédure vérifiable
WAKE TEST rejoue la procédure contre le dépôt réel (§5.5)
JOURNAL
```

- **E15 — sandbox.** Chaque répétition tourne dans un `git worktree` dédié (ou
  une copie si le projet n'est pas versionné), jamais dans l'arbre de travail de
  l'utilisateur. Le worktree est détruit en fin de passe, quel que soit le
  résultat.
- **E16 — confinement.** Pendant REM : pas d'écriture hors sandbox, pas d'envoi
  de message, pas d'appel réseau mutant, pas de push. Appliqué par un callback
  d'autorisation d'outil, **pas** par une consigne de prompt — une consigne se
  contourne.
- **E17 — budget.** Plafond de tokens, plafond de tâches, plafond de temps mur.
  Dépassement d'un seul → arrêt propre, journalisé, artefacts partiels en
  quarantaine. Les valeurs appartiennent à l'utilisateur.

### 5.5 Quarantaine et épreuve du réel

- **E18 — quarantaine.** Un artefact rêvé n'atterrit jamais dans le répertoire de
  skills du harness. Il va dans `dreams/pending/<dream_id>/`, que le harness ne
  charge pas. Tant qu'il y est, il est inerte.
- **E19 — provenance.** Frontmatter obligatoire :

  ```yaml
  origin: dreamed          # dreamed | experienced | user
  dream_id: 20260807-0312
  seeded_from: [session:ab12cd, session:ef34gh]
  wake_test: null          # null | {command, exit_code, ran_at}
  ```

  Un artefact promu **conserve** `origin: dreamed` et gagne son `wake_test`. On
  n'efface pas l'histoire d'un artefact ; on y ajoute une preuve.

- **E20 — wake test.** Sortie de quarantaine si et seulement si : l'artefact
  porte une commande de vérification exécutable, **et** elle a été rejouée contre
  le dépôt réel (hors sandbox), **et** elle est sortie avec le code 0.

  Un juge LLM ne suffit pas : « ça a l'air correct » est précisément le jugement
  que la confabulation trompe. Sans test exécutable, l'artefact reste en
  quarantaine indéfiniment — promouvable **à la main uniquement**.

- **E21 — réveil.** Une ligne au démarrage suivant, pas un rapport :
  `🌙 3 skills rêvés en attente — /dreams`. Le détail est dans le journal.

### 5.6 Hors périmètre du rêve

Explicitement interdit : écrire en mémoire (E14) ; modifier un skill existant
(il ne peut qu'en proposer un nouveau) ; toucher un skill épinglé ou installé
depuis une source tierce ; tourner pendant qu'une session utilisateur est
active ; se déclencher depuis un subagent.

---

## 6. Pilotage

Un seul mécanisme — une requête au SDK avec des options — décliné en trois
runners qui diffèrent par leur répertoire de travail, leur modèle, et surtout
**par ce qu'ils ont le droit d'écrire**.

| | Conversation | Revue (E7) | Rêve (§5) |
|---|---|---|---|
| Session | reprise par clé | fork froid | fork froid |
| Répertoire | workspace | workspace | **worktree jetable** |
| Sources de réglages | utilisateur + projet | idem | idem |
| Modèle | principal | auxiliaire | auxiliaire |
| Écrit la mémoire | oui (`off`) | oui (`staged`) | **non** (E14) |
| Écrit des skills | à la demande | `origin: experienced` | quarantaine seule |
| Hooks actifs | oui | non (garde) | non (garde) |
| Autorisation d'outil | défaut | défaut | **confinée** (E16) |

Le chargement des **sources de réglages utilisateur et projet** est ce qui
distingue « le harness Claude Code » d'« une boucle d'agent nue » : c'est par là
que les skills, les subagents, les commandes et les fichiers de contexte
atteignent la session. Le retirer désactive silencieusement toute la boucle.

**Reprise plutôt que client ouvert.** Une passerelle sert beaucoup de
conversations inactives ; un client vivant par conversation donne un processus
dont la mémoire croît avec le nombre de gens qui ont un jour écrit. On associe
une clé de conversation à un identifiant de session, on reprend, on relâche. La
table est persistée : un redémarrage ne doit amnésier personne.

**Modèles.** Aucun défaut dégradé : le modèle principal est `claude-opus-5`, les
passes auxiliaires valent `auto` (= le modèle principal). Router une passe vers
un modèle moins cher est un arbitrage coût/qualité qui appartient à
l'utilisateur.

---

## 7. Critères d'acceptation du système

1. Une écriture mémoire qui dépasse le plafond renvoie une erreur listant les
   entrées ; aucune entrée n'est perdue.
2. Une entrée contenant un motif d'injection connu est refusée.
3. Après une passe, le rollback restaure l'arbre de skills à l'octet près, et le
   rollback est lui-même annulable.
4. Une passe REM lancée avec un budget de 20 000 tokens ne le dépasse pas et
   journalise son arrêt.
5. **Aucun chemin de code ne permet à une passe REM d'écrire dans la mémoire ni
   dans les propositions mémoire.** Vérifié par test, pas par revue.
6. Un skill rêvé sans wake test réussi n'est jamais chargé par le harness —
   vérifié en listant les skills visibles depuis une vraie session.
7. Un wake test est un code de sortie de processus, jamais un verdict de modèle.
8. Dix sessions démarrées simultanément déclenchent **une** passe, pas dix.
9. Une passe engendrée ne s'auto-engendre pas.
10. Un redémarrage de la passerelle ne perd aucune correspondance
    conversation → session.

---

## 8. Questions ouvertes

- **Calibrage des plafonds mémoire.** À mesurer contre le preset `claude_code`
  avant de figer 2 200 / 1 375.
- **Fréquence REM.** Commencer manuel ; passer à l'automatique une fois le
  rapport coût/récolte mesuré sur une dizaine de passes.
- **Artefact rêvé qui échoue son wake test.** Le purger perd l'information
  « cette piste ne marche pas » ; le garder gonfle la quarantaine. Piste :
  journaliser l'échec, purger l'artefact.
- **Le rêve peut-il lire les transcripts d'autres projets ?** Plus de matière à
  graine, mais fuite de contexte entre projets. Par défaut : non.
