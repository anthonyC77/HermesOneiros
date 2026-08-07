# Oneiros — découpage d'implémentation

Découpage de [SPEC.md](SPEC.md) en tâches. Chaque tâche a une frontière nette et
une condition de fin **testable**. Rien n'est repris d'un dépôt existant (R0).

**Lecture d'une tâche :** *Objectif* — ce qu'elle rend possible. *Livrable* — les
fichiers qu'elle crée. *Fait quand* — le test qui la clôt. *Dépend de* — ce qui
doit exister avant. *Taille* — S (< ½ j), M (1–2 j), L (3 j+).

---

## Ordre des lots

```
L0 socle ──▶ L1 mémoire ──▶ L2 rappel ──┐
                  │                      ├──▶ L4 pilotage ──▶ L5 NREM ──▶ L6 REM
                  └──▶ L3 skills ────────┘                       ▲
                              │                                  │
                              └──▶ L3.4 snapshots/rollback ───────┘
```

**L3.4 précède L5 sans exception.** Aucune passe automatique mutante ne tourne
avant que l'annulation existe.

---

# L0 — Socle

### T01 — Squelette de projet
**Objectif.** Un paquet installable, des tests qui tournent, une commande qui répond.
**Livrable.** `pyproject.toml`, `src/oneiros/__init__.py`, `src/oneiros/cli.py`,
`tests/`, `README.md`.
**Fait quand.** `pip install -e ".[dev]"` puis `oneiros --version` affiche une
version, et `pytest` collecte 0 test sans erreur.
**Dépend de.** —
**Taille.** S

### T02 — Résolution de chemins et configuration
**Objectif.** Un seul endroit où se résolvent tous les chemins et réglages, pour
qu'un déplacement du répertoire d'état déplace tout d'un coup.
**Livrable.** `src/oneiros/config.py` : résolution du répertoire d'état
(surcharge explicite → donnée de plugin fournie par le harness → défaut sous
`~/.claude/`), accesseurs dérivés (`memory/`, `dreams/`, `pending/`,
`archive/`, `backups/`), dataclass `Config` chargée depuis `config.json`.
**Points d'attention.** Les secrets vont dans un fichier d'environnement séparé,
chargés sans écraser une variable déjà exportée. Seuils, timeouts et préférences
d'affichage vont dans `config.json`, **jamais** dans le fichier de secrets.
**Fait quand.** Test : surcharger la variable d'environnement d'état redirige
les six chemins dérivés ; une variable exportée survit au chargement du fichier
de secrets ; un `config.json` corrompu retourne les défauts sans lever.
**Dépend de.** T01
**Taille.** S

### T03 — Squelette du plugin Claude Code
**Objectif.** Le harness voit le plugin : commandes listées, hooks déclarés,
subagents disponibles.
**Livrable.** `plugin/` avec son manifeste, `plugin/commands/`, `plugin/agents/`,
`plugin/hooks/hooks.json` (vide de handlers pour l'instant), et un script
d'installation par lien symbolique documenté pour Windows et POSIX.
**Fait quand.** Après installation, une session Claude Code liste les commandes
du plugin, et `claude` démarre sans erreur de hook.
**Dépend de.** T01
**Taille.** S

### T04 — `doctor`
**Objectif.** Une commande qui dit ce qui est câblé et ce qui manque. C'est
l'outil de diagnostic de tout le reste, il vient tôt.
**Livrable.** `oneiros doctor` : plugin installé ? hooks déclarés ? répertoire
d'état accessible en écriture ? index présent et à jour ? serveur MCP
enregistré ? SDK importable ?
**Fait quand.** Sur une machine sans rien d'installé, `doctor` sort non-zéro et
liste chaque manque avec la commande qui le corrige.
**Dépend de.** T02, T03
**Taille.** S

---

# L1 — Mémoire (E1–E5)

### T05 — Store mémoire : format et bornes
**Objectif.** Lire, écrire et mesurer les deux fichiers de mémoire.
**Livrable.** `src/oneiros/memory/store.py` : parse/sérialise le format à
séparateur `§` (entrées multi-lignes), calcule le remplissage, rend l'en-tête
`67% — 1474/2200`.
**Fait quand.** Aller-retour parse → sérialise sur un fichier de 12 entrées dont
3 multi-lignes : identité octet à octet. Le compteur de caractères ignore les
séparateurs.
**Dépend de.** T02
**Taille.** S

### T06 — Opérations d'écriture (E2, E3)
**Objectif.** `add` / `replace` / `remove`, avec la sémantique de saturation.
**Livrable.** Dans `store.py` : les trois opérations ; `replace`/`remove` par
sous-chaîne **unique** ; doublon exact → succès sans effet ; dépassement →
exception portant la liste des entrées courantes et le taux de remplissage.
**Points d'attention.** `replace` est aussi borné : échanger une entrée contre
une plus longue peut déborder. Jamais d'éviction ni de troncature automatique.
**Fait quand.** Cinq tests : sous-chaîne ambiguë → erreur nommant les candidats ;
doublon → no-op ; `add` qui déborde → erreur listant les entrées ; `replace` qui
déborde → erreur ; suite consolider-puis-réessayer → succès.
**Dépend de.** T05
**Taille.** M

### T07 — Scan de sécurité des entrées (E4)
**Objectif.** Une entrée mémoire entre dans le prompt système ; elle a le niveau
de confiance d'une consigne opérateur.
**Livrable.** `src/oneiros/memory/guard.py` : détection de motifs d'injection de
prompt, de tentatives d'exfiltration de secrets, et de caractères Unicode
invisibles. Refus explicite, motif nommé.
**Fait quand.** Un corpus de cas positifs (≥ 15 motifs) est refusé ; un corpus de
faux amis (texte technique légitime contenant « ignore », « system », des chemins
`~/.ssh`) passe. Le taux de faux positifs sur le second corpus est zéro.
**Dépend de.** T05
**Taille.** M

### T08 — Gate d'approbation et file d'attente (E5)
**Objectif.** Trois états — `off`, `staged`, `always` — et un endroit où les
écritures attendent.
**Livrable.** `src/oneiros/memory/gate.py` + `pending/memory/` : mise en attente
d'une écriture avec son origine, sa date et son diff ; application ; rejet.
**Points d'attention.** Défaut `off` pour les tours au premier plan, `staged`
pour **toute** écriture issue d'une passe automatique. Le défaut ne dépend pas de
la configuration, il dépend de l'origine.
**Fait quand.** Une écriture d'origine automatique est mise en attente même quand
le gate global vaut `off`. Approuver applique exactement le diff montré.
**Dépend de.** T06
**Taille.** M

### T09 — Injection dans le prompt système (E1, I1)
**Objectif.** Rendre le bloc mémoire ajouté au preset du harness.
**Livrable.** `src/oneiros/memory/render.py` : produit le bloc à passer en
*append* du preset `claude_code`.
**Points d'attention.** **Append, jamais replace** — remplacer le preset fait
perdre les consignes d'outillage du harness et l'agent se met à mal utiliser les
outils d'édition d'une manière difficile à tracer. Le bloc est capturé une seule
fois par session.
**Fait quand.** Test : deux appels successifs dans la même session rendent le
même bloc, même si le fichier a changé entre les deux.
**Dépend de.** T05
**Taille.** S

### T10 — Interface mémoire
**Objectif.** L'agent et l'utilisateur peuvent écrire et arbitrer.
**Livrable.** `plugin/commands/remember.md`, `plugin/commands/memory.md`
(`pending` / `approve` / `reject` / `gate`), et `oneiros memory` en CLI.
**Fait quand.** Depuis une session réelle : `/remember` ajoute une entrée
visible à la session suivante ; `/memory pending` liste une écriture mise en
attente par T08.
**Dépend de.** T08, T09
**Taille.** S

---

# L2 — Rappel inter-sessions (E6)

### T11 — Lecteur de transcripts
**Objectif.** Transformer les fichiers de session du harness en enregistrements
indexables.
**Livrable.** `src/oneiros/sessions/reader.py` : itère les transcripts, ignore
les entrées sidechain et meta, extrait rôle / texte / **entrées** d'outils
(jamais les résultats, qui sont volumineux et rarement recherchés).
**Fait quand.** Sur un jeu de transcripts réels, le lecteur ne lève sur aucun
fichier, y compris tronqué en cours de ligne, et le compte d'enregistrements est
stable entre deux passes.
**Dépend de.** T02
**Taille.** M

### T12 — Index FTS5 incrémental
**Objectif.** Une base interrogeable, réindexée en secondes et non en minutes.
**Livrable.** `src/oneiros/sessions/index.py` : schéma SQLite FTS5, indexation
incrémentale sur (taille, mtime), table de suivi des fichiers vus.
**Fait quand.** Deuxième passe sur un corpus inchangé : zéro écriture, temps
sous la seconde. Ajout d'un transcript : seul celui-ci est relu.
**Dépend de.** T11
**Taille.** M

### T13 — Traduction de requête
**Objectif.** Une requête utilisateur brute n'est **pas** de la syntaxe FTS5
valide. C'est une exigence, pas une commodité.
**Livrable.** `src/oneiros/sessions/query.py` : échappe, tokenise, construit
l'expression `MATCH`.
**Fait quand.** Corpus de requêtes hostiles — guillemets déséquilibrés, `NEAR`,
`*`, `AND`/`OR` en minuscules, apostrophes, accents, chaîne vide — : aucune ne
lève, chacune retourne un résultat plausible ou rien.
**Dépend de.** T12
**Taille.** M

### T14 — Serveur MCP
**Objectif.** Exposer la recherche à l'agent, y compris quand le harness le lance
sous un interpréteur qui n'a pas le paquet installé.
**Livrable.** `src/oneiros/mcp_server.py` : JSON-RPC sur stdio, **stdlib
uniquement**, aucun import du paquet applicatif — il ouvre la base directement.
**Fait quand.** Lancé avec un `PYTHONPATH` vide et un interpréteur nu, le serveur
répond à `initialize`, `tools/list`, `tools/call`.
**Dépend de.** T13
**Taille.** M

### T15 — Interface de rappel
**Livrable.** `oneiros sessions index|search|stats|recent` et
`plugin/commands/sessions.md`.
**Fait quand.** `/sessions <requête>` depuis une session réelle retourne des
extraits datés et navigables.
**Dépend de.** T14
**Taille.** S

---

# L3 — Skills (E8–E12)

### T16 — Registre et provenance (E10)
**Objectif.** Savoir, pour chaque skill, ce qu'on a le droit d'en faire.
**Livrable.** `src/oneiros/skills/registry.py` : lecture du frontmatter, champ
`origin` (`user` | `experienced` | `dreamed`), état de cycle de vie, épinglage.
**Points d'attention.** La provenance est **déclarée**, jamais inférée. Pas
d'heuristique « ça ressemble à du généré ». Une commande d'adoption transfère
explicitement la juridiction.
**Fait quand.** Un skill sans `origin` est traité comme `user` et exclu de toute
transition automatique. L'adoption écrit le champ et n'aligne pas l'horodatage
d'activité (adopter une bibliothèque déjà abandonnée ne lui achète pas 90 jours).
**Dépend de.** T02
**Taille.** M

### T17 — Télémétrie d'usage (E9)
**Objectif.** Sans compteurs, impossible de distinguer un skill discrètement
porteur d'un skill mort.
**Livrable.** `plugin/hooks/skill_usage.py` (stdlib seule, écriture atomique) +
déclaration `PostToolUse` sur les invocations de skill ;
`skill-usage.json` : `use_count`, `view_count`, `patch_count`, horodatages.
**Points d'attention.** Le hook est un sous-processus sous interpréteur inconnu.
Aucun import applicatif. Sortie silencieuse en cas d'erreur : un hook qui plante
ne doit pas casser une session.
**Fait quand.** Utiliser un skill dans une vraie session incrémente son compteur.
Deux hooks concurrents ne corrompent pas le fichier (test : 50 écritures
parallèles, JSON valide en fin).
**Dépend de.** T16, T03
**Taille.** M

### T18 — Transitions de cycle de vie (E8)
**Objectif.** L'élagage déterministe, sans LLM et sans coût.
**Livrable.** `src/oneiros/skills/lifecycle.py` : `active` → (30 j) `stale` →
(90 j) `archived`, vers `archive/skills/`.
**Points d'attention.** Épinglés exemptés. **Plancher de grâce** : un skill à
zéro usage n'est pas archivé avant d'avoir atteint l'âge de `stale` — zéro usage
est une absence de preuve, pas une preuve de futilité. Jamais de suppression.
**Fait quand.** Trois tests d'horloge simulée : un skill utilisé hier ne bouge
pas ; un skill à zéro usage créé il y a 100 jours passe `stale` puis `archived` ;
le même épinglé ne bouge jamais. Restauration depuis l'archive rend le skill
identique.
**Dépend de.** T17
**Taille.** M

### T19 — Snapshots et rollback (E11) — **bloquant pour L5**
**Objectif.** Rendre toute passe automatique annulable en une commande.
**Livrable.** `src/oneiros/skills/backup.py` : archive compressée de l'arbre de
skills avant chaque passe mutante, avec un manifeste (date, motif, empreinte) ;
`oneiros skills rollback [--list] [--id]`.
**Points d'attention.** Le rollback prend lui-même un snapshot avant d'écraser,
étiqueté `pre-rollback` : un rollback erroné doit être annulable. Rétention
bornée.
**Fait quand.** Snapshot → passe destructive → rollback → l'arbre est identique
octet à octet à l'original. Puis rollback du rollback → retour à l'état
post-passe.
**Dépend de.** T18
**Taille.** M

### T20 — Rapports de passe (E12)
**Livrable.** Un répertoire horodaté par passe : rapport machine (JSON complet)
et rapport humain (Markdown). Toute passe, quelle qu'elle soit, en produit un.
**Fait quand.** Une passe sans candidat produit quand même un rapport, qui dit
explicitement qu'il n'y avait rien à faire — pas un fichier vide, pas d'absence
de fichier.
**Dépend de.** T18
**Taille.** S

---

# L4 — Pilotage (§6)

### T21 — Reconnaissance de la surface du SDK
**Objectif.** Ne pas coder contre une API supposée.
**Livrable.** `docs/sdk-surface.md` : signatures effectivement vérifiées pour
la fonction de requête, l'objet d'options (répertoire de travail, modèle, mode
de permission, sources de réglages, reprise de session, prompt système en
*preset + append*), les types de messages, et surtout **le mécanisme
d'autorisation d'outil** et **la déclaration de hooks côté SDK** — dont dépendent
T27 et T30.
**Points d'attention.** Le Claude Agent SDK est un produit distinct du *tool
runner* de l'API Claude ; ne pas confondre les deux surfaces. Vérifier contre la
documentation du SDK, pas contre la mémoire.
**Fait quand.** Un script de bout en bout fait un tour réel et affiche
l'identifiant de session retourné. Chaque option listée est marquée « vérifiée »
ou « absente », avec sa source.
**Dépend de.** T01
**Taille.** M

### T22 — Runner de base
**Objectif.** Une seule façon de parler au SDK ; tout le reste en dérive.
**Livrable.** `src/oneiros/runner/base.py` : construction des options, boucle de
consommation des messages, agrégation en un résultat de tour (texte, outils
utilisés, identifiant de session, coût), gestion des erreurs et de l'annulation.
**Points d'attention.** Charger les **sources de réglages utilisateur et projet**
— c'est ce qui fait du harness Claude Code plutôt qu'une boucle nue, et donc ce
qui fait exister skills, subagents, commandes et fichiers de contexte. Le
retirer désactive silencieusement toute la boucle d'apprentissage : le mettre
sous test.
**Fait quand.** Test d'intégration : un tour qui invoque un skill du plugin
prouve que les sources de réglages sont bien chargées.
**Dépend de.** T21
**Taille.** M

### T23 — Runner de conversation
**Objectif.** Associer une clé de conversation à une session et la **reprendre**
par tour, plutôt que tenir un client ouvert.
**Livrable.** `src/oneiros/runner/conversation.py` + table de correspondance
persistée.
**Points d'attention.** Un client vivant par conversation donne un processus dont
la mémoire croît avec le nombre de gens qui ont un jour écrit. Un verrou par
conversation : les tours restent ordonnés dans un fil et concurrents entre fils.
**Fait quand.** Deux tours consécutifs sur la même clé partagent le contexte.
Redémarrage du processus entre les deux : le contexte survit.
**Dépend de.** T22
**Taille.** M

### T24 — Runner de revue (E7)
**Objectif.** L'apprentissage en ligne, dans un fork froid (I1).
**Livrable.** `src/oneiros/runner/review.py` : rejoue la conversation, propose
des entrées mémoire et des skills `origin: experienced`, écrit via le gate en
`staged`.
**Points d'attention.** Sur un modèle différent du principal, rejouer un
**digest** (tours récents verbatim + résumé des anciens) — le cache du modèle
principal n'est de toute façon pas réutilisable, autant ne pas payer l'écriture
d'un cache complet sur le second.
**Fait quand.** Une conversation contenant deux fois la même correction produit
une proposition d'entrée mémoire ; une conversation sans leçon durable n'en
produit aucune (test du silence : le faux positif est le mode de défaillance
coûteux ici).
**Dépend de.** T22, T08, T16
**Taille.** L

### T25 — Déclenchement de la revue
**Livrable.** `plugin/hooks/turn_counter.py` sur `Stop` : compte les tours, ne
déclenche pas avant un seuil bas, déclenche ensuite tous les N tours.
**Fait quand.** Une session de 3 tours ne déclenche rien ; une session de 30 en
déclenche le nombre attendu, et aucune revue ne tourne pendant un tour actif.
**Dépend de.** T24, T17
**Taille.** S

---

# L5 — Dream NREM (§5.2, §5.3)

### T26 — Déclencheur d'inactivité
**Objectif.** Le point le plus délicat du projet : la session engendrée déclenche
à son tour l'ouverture de session.
**Livrable.** `plugin/hooks/dream_trigger.py` (stdlib seule) : les cinq gardes de
§5.2 — variable de garde, détection de subagent, seuil d'inactivité, intervalle
depuis la dernière passe, verrou exclusif — puis spawn détaché.
**Points d'attention.** Chaque garde couvre un cas que les autres ne couvrent
pas : la variable arrête la récursion directe, la détection de subagent arrête un
fan-out de dix, le verrou arrête deux sessions ouvertes dans le même instant. Le
verrou n'est pas relâché sur le chemin nominal — c'est l'horodatage qui supprime
le re-spawn, et le verrou expire seul. Il **est** relâché si le spawn échoue.
**Fait quand.** Quatre tests : dix déclenchements simultanés → une seule passe ;
une passe engendrée ne s'engendre pas elle-même ; un déclenchement depuis un
subagent ne fait rien ; un spawn qui échoue libère le verrou immédiatement.
**Dépend de.** T03, T20
**Taille.** L

### T27 — Runner de rêve, socle commun
**Objectif.** Le troisième runner, avec ses restrictions.
**Livrable.** `src/oneiros/runner/dream.py` : fork froid, modèle auxiliaire,
variable de garde positionnée, et **refus structurel d'écrire en mémoire**.
**Points d'attention.** E14 n'est pas une consigne de prompt, c'est une propriété
du code : le runner de rêve n'a aucun chemin qui atteint le store mémoire ni la
file d'attente mémoire.
**Fait quand.** Test dédié au critère 5 de la spec : parcourir les appels
accessibles depuis le runner de rêve, prouver qu'aucun n'atteint le store
mémoire. Ce test échoue si quelqu'un ajoute l'import plus tard.
**Dépend de.** T22
**Taille.** M

### T28 — Passe NREM
**Livrable.** `src/oneiros/dream/nrem.py` : REPLAY (via l'index) → CONSOLIDATE
(fusion des redondances, contradiction tranchée par récence, retour sous plafond)
→ PRUNE (T18) → JOURNAL (T20).
**Points d'attention.** Les propositions mémoire passent par le gate `staged` du
runner de **revue**, pas par celui du rêve : c'est la revue qui écrit, le rêve
qui recommande.
**Fait quand.** Deux entrées mémoire contradictoires en entrée → une seule en
sortie, la plus récente, l'ancienne présente dans le journal. Une mémoire à 95 %
de remplissage repasse sous 80 % sans perte d'information non redondante.
**Dépend de.** T27, T19, T12
**Taille.** L

---

# L6 — Dream REM (§5.4, §5.5)

### T29 — Sandbox (E15)
**Objectif.** Une répétition ne touche jamais l'arbre de travail de l'utilisateur.
**Livrable.** `src/oneiros/dream/sandbox.py` : création d'un worktree git dédié,
repli sur une copie si le projet n'est pas versionné, destruction garantie en
sortie (y compris sur exception et sur interruption).
**Fait quand.** Une répétition qui écrit, commit et casse des fichiers laisse
l'arbre de l'utilisateur strictement inchangé — vérifié par empreinte avant/après.
Un plantage en cours de répétition ne laisse aucun worktree orphelin.
**Dépend de.** T27
**Taille.** M

### T30 — Confinement (E16)
**Objectif.** Interdire par le code ce qu'une consigne de prompt ne peut que
suggérer.
**Livrable.** Callback d'autorisation d'outil branché sur le runner de rêve :
refus de toute écriture hors sandbox, de tout envoi de message, de tout appel
réseau mutant, de tout push.
**Points d'attention.** Une consigne se contourne, un callback non. Le refus est
journalisé, pas silencieux — savoir ce que le rêve a *essayé* de faire est une
information.
**Fait quand.** Un prompt de test qui demande explicitement d'écrire hors sandbox
et d'envoyer un message se voit refuser les deux, et les deux refus apparaissent
au journal.
**Dépend de.** T29, T21
**Taille.** M

### T31 — Budget (E17)
**Livrable.** `src/oneiros/dream/budget.py` : trois plafonds — tokens, nombre de
tâches imaginées, temps mur. Dépassement de l'un → arrêt propre, journalisé,
artefacts partiels conservés en quarantaine.
**Fait quand.** Une passe lancée à 20 000 tokens s'arrête avant, et le journal
nomme lequel des trois plafonds a mordu.
**Dépend de.** T27
**Taille.** M

### T32 — SEED et IMAGINE
**Objectif.** Extraire de la matière du vécu, puis en dériver des tâches.
**Livrable.** `src/oneiros/dream/seed.py` : depuis l'index, fichiers récemment
touchés, échecs récurrents, outils qui ont raté, sujets abordés sans conclusion.
`src/oneiros/dream/imagine.py` : génère N tâches plausibles *adjacentes* au vécu.
**Points d'attention.** « Adjacent » est la contrainte : une tâche sans ancrage
dans une session réelle est du bruit coûteux. Chaque tâche imaginée porte les
identifiants de session qui l'ont semée — c'est ce qui alimentera `seeded_from`.
**Fait quand.** Sur un corpus réel, chaque tâche générée cite au moins une
session existante, et deux passes sur le même corpus ne produisent pas les mêmes
tâches (sinon le rêve ne rêve pas).
**Dépend de.** T31, T12
**Taille.** L

### T33 — REHEARSE et HARVEST
**Livrable.** `src/oneiros/dream/rehearse.py` : résout chaque tâche en sandbox et
ne retient que ce qui a produit une procédure **vérifiable** — c'est-à-dire
accompagnée d'une commande de vérification exécutable.
**Fait quand.** Une répétition réussie mais sans commande de vérification produit
un artefact marqué non promouvable, pas un rejet silencieux ni une promotion.
**Dépend de.** T32, T30
**Taille.** L

### T34 — Quarantaine et provenance (E18, E19)
**Livrable.** `dreams/pending/<dream_id>/` — un répertoire que le harness ne
charge pas — et le frontmatter obligatoire de §5.5.
**Points d'attention.** Un artefact promu **conserve** `origin: dreamed` et gagne
son `wake_test`. On n'efface pas l'histoire d'un artefact, on y ajoute une preuve.
**Fait quand.** Critère 6 de la spec : lister les skills visibles depuis une
vraie session ne fait apparaître aucun artefact en quarantaine. Test exécuté
contre une session réelle, pas simulé.
**Dépend de.** T33, T16
**Taille.** M

### T35 — Wake test (E20)
**Objectif.** La barrière entre le rêvé et le réel.
**Livrable.** `src/oneiros/dream/wake.py` : rejoue la commande de vérification
contre le dépôt **réel**, hors sandbox, et promeut si et seulement si le code de
sortie est 0.
**Points d'attention.** **Jamais de juge LLM.** « Ça a l'air correct » est
exactement le jugement que la confabulation trompe. Sans commande exécutable,
l'artefact reste en quarantaine indéfiniment, promouvable à la main uniquement.
**Fait quand.** Critère 7 : un artefact dont le test sort 1 n'est pas promu ; un
artefact sans test n'est jamais promu automatiquement, quel que soit le contenu ;
la promotion écrit `wake_test` avec la commande, le code et la date.
**Dépend de.** T34, T19
**Taille.** M

### T36 — Réveil et arbitrage (E21)
**Livrable.** Une ligne au démarrage suivant (`🌙 3 skills rêvés en attente —
/dreams`), `plugin/commands/dreams.md`, et
`oneiros dreams list|show|promote|purge`.
**Points d'attention.** Une ligne, pas un rapport : le détail va au journal, pas
dans le prompt de l'utilisateur.
**Dépend de.** T35
**Taille.** S

---

## Récapitulatif

| Lot | Tâches | Charge | Clôt |
|---|---|---|---|
| L0 socle | T01–T04 | ~2 j | `doctor` répond juste |
| L1 mémoire | T05–T10 | ~5 j | E1–E5, critères 1 et 2 |
| L2 rappel | T11–T15 | ~5 j | E6 |
| L3 skills | T16–T20 | ~6 j | E8–E12, critère 3 |
| L4 pilotage | T21–T25 | ~7 j | E7, critère 10 |
| L5 NREM | T26–T28 | ~6 j | E13, critères 8 et 9 |
| L6 REM | T29–T36 | ~10 j | E14–E21, critères 4 à 7 |

**Livrable intermédiaire utile.** À la fin de L4, le système apprend déjà : il a
une mémoire curée, un rappel inter-sessions, des skills entretenus et une revue
post-tour. L5 et L6 ajoutent le rêve. Si le rapport coût/récolte du rêve déçoit
(§8 de la spec), s'arrêter à L4 laisse un produit cohérent, pas un chantier.

**Trois tâches à ne pas sous-estimer.** T26 (les cinq gardes, où chaque erreur
est une bombe à fork), T33 (la répétition, seul endroit où le rêve produit
vraiment quelque chose), T35 (la barrière rêvé/réel, dont dépend le fait que la
fonctionnalité soit nette positive).
