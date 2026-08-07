# Hermes Onirique — Mode hypersensible

**Note de conception**
Version 0.1 — 7 août 2026

---

## 1. Intention

Hermes Onirique consolide sa mémoire par un mécanisme de type *Dreaming* : un
passage nocturne qui trie les signaux court terme et promeut les plus solides en
mémoire durable. Ce mécanisme est un **filtre passe-bas**. Il est conçu pour tuer
le bruit, et il tue avec lui tout ce qui n'apparaît qu'une fois.

Le mode hypersensible est son **dual** : un passe-haut. Il ne cherche pas ce qui
revient, il cherche ce qui n'aurait pas dû arriver. Le singleton, l'anomalie, la
contradiction, le changement de registre.

Deux usages visés :

- **Interne** — enrichir Hermes d'une attention aux signaux faibles.
- **Distribué** — un mode que chacun fait tourner en IA locale chez soi, sans
  intermédiaire, comme outil d'auto-connaissance ou d'apaisement au travail.

Le second usage n'est pas qu'un débouché commercial : c'est ce qui rend le
premier défendable. Voir §7.

---

## 2. Rappel — pourquoi le rêve laisse un trou

Le scoring de consolidation (modèle OpenClaw, transposable) pondère grossièrement :

| Signal | Poids |
|---|---|
| Pertinence | 0,30 |
| Fréquence | 0,24 |
| Diversité des requêtes | 0,15 |
| Récence | 0,15 |
| Consolidation / stabilité | 0,10 |
| Richesse conceptuelle | 0,06 |

Plus des seuils durs sur le nombre de rappels. Conséquence structurelle : une
information vue **une seule fois** ne peut mathématiquement pas survivre, quelle
que soit son importance. Or c'est exactement la classe des remarques glissées en
fin de session, des contraintes mentionnées une fois parce qu'elles allaient de
soi, des agacements ponctuels.

---

## 3. Le scoring inversé

Chaque signal de la voie hypersensible est le miroir d'un signal de consolidation.

**Surprise** — l'inverse littéral de la fréquence. `-log p(obs | état mémoire)`.
Ce qui est déjà prédit n'apporte rien ; ce qui contredit le modèle vaut cher.

**Distance au manifold** — l'embedding tombe loin de tous les clusters existants.
Nouveauté topologique.

**Dissonance** — la consolidation classique résout les contradictions par
timestamp (le récent écrase l'ancien). La voie hypersensible fait l'inverse :
elle ne résout pas, elle lève la main. Une contradiction est une information.

**Marqueurs de rupture** — hésitation, retour en arrière (« non, annule »),
changement de registre, tâche abandonnée en cours de route.

**Le silence** — ce dont l'utilisateur a *arrêté* de parler. Un sujet présent
trois semaines puis plus jamais. La consolidation classique le laisse mourir par
décroissance de récence sans jamais noter que sa disparition était en soi un
événement. Détecter une absence coûte structurellement plus cher que détecter une
présence : il faut un modèle de ce qui aurait dû être là. C'est probablement là
que se cache le plus de valeur.

---

## 4. Architecture à double voie

```
                    Événements bruts
                          |
            +-------------+-------------+
            |                           |
      VOIE LENTE                   VOIE RAPIDE
   cron nocturne, passe-bas    temps réel, passe-haut
            |                           |
   Scoring fréquentiel          Scoring par surprise
     haute précision                haut rappel
            |                           |
       MEMORY.md    <--graduation--  SIGNALS.md
   durable, fait acquis         quarantaine, hypothèse
```

Points de conception :

- Un signal faible **n'entre jamais directement** en mémoire durable.
- Il vit en quarantaine avec un compteur de corroboration et une date de
  péremption.
- S'il est confirmé — par un autre événement, ou par l'utilisateur qui répond
  « ah oui, effectivement » — il gradue vers la voie normale.
- Sinon il décroît, **mais reste tracé**. Ça permet d'auditer après coup les fois
  où le système a vu juste et où l'utilisateur n'a pas écouté. C'est la seule
  source de vérité pour calibrer.

Statut du mode : **activable / désactivable** pour permettre l'A/B. À terme,
l'hypothèse à tester est qu'il devienne un canal permanent dont on règle non pas
l'existence mais le seuil de remontée — modèle biologique : on ne « passe pas en
vigilance », on l'est en permanence, c'est le seuil de conscience qui bouge.

---

## 5. Les trois façons dont ça casse

### 5.1 Apophénie

Avec assez de sensibilité, on trouve des motifs dans le bruit. Le système finit
superstitieux. **Garde-fou** : budget d'hypothèse nulle. Estimer combien de
« signaux » le système produirait sur des données aléatoires, et traiter ce
nombre comme son plancher de faux positifs.

### 5.2 Injection de prompt — le risque majeur

La consolidation classique filtre les contenus de provenance non fiable. Or la
voie hypersensible est par construction **attirée** par l'anormal. Et une charge
d'injection est statistiquement anormale : texte impératif, inattendu, en
contradiction avec le contexte.

Non corrigé, on construit un système qui **mémorise préférentiellement les
attaques qu'il subit**.

**Règle dure** : `surprise élevée + provenance non fiable = rejet immédiat`.
Jamais promotion, jamais quarantaine. La sensibilité ne s'applique qu'aux canaux
de confiance.

### 5.3 Intrusion

Un agent qui remarque un état de fatigue prolongé, c'est utile ou glaçant selon
la formulation et le destinataire.

**Règles minimales** :
- Le mode hypersensible **remonte**, il n'**agit** jamais. Aucune action
  déclenchée par un signal non gradué.
- Aucune remontée à un tiers. Jamais. L'utilisateur est le seul destinataire.

---

## 6. Le cadran : budget de faux positifs

L'interface n'est pas un booléen mais un budget. Analogie SRE : si le système
remonte quarante observations par jour, elles sont toutes ignorées en une semaine
et le mode est mort.

- `max N signaux surfacés par jour` (démarrer à 3).
- Classement forcé : le système doit choisir ses meilleures intuitions et taire
  le reste.
- Chaque remontée s'accompagne de sa confiance et de son support : « vu une fois,
  il y a trois semaines, je peux me tromper ».
- **Auto-régulation** : si le taux de rejet monte, le système baisse sa
  sensibilité tout seul. Sans ça, on construit un agent qui apprend qu'il a
  raison d'interrompre parce que l'utilisateur finit toujours par céder.

---

## 7. Détecter l'état — trois sources

### 7.1 Signaux comportementaux (recommandé, par défaut)

Les plus fiables pour un contexte de travail, et déjà disponibles sans capteur :

- Nombre de reformulations de la même demande
- `Ctrl-C` sur une tâche en cours
- Retours en arrière (« non, annule »)
- Fréquence de relance des tests
- Effondrement de la longueur des messages
- Heure locale et durée de session continue
- Délai entre lecture d'une réponse et réaction

Avantages : robustes, pas de micro, pas de capteur, **hors du champ de
l'inférence biométrique**, et ils décrivent une *situation* plutôt qu'un *état
mental*. « Tu as relancé ce test six fois en dix minutes » est un fait. « Tu es
frustré » est une inférence sur le for intérieur.

### 7.2 Prosodie vocale (optionnel)

État de l'art fin 2026 :

- **SenseVoice / FunASR** — ASR multilingue + reconnaissance d'émotion +
  détection d'événements audio, faible latence. Disponible en GGUF sur
  llama.cpp : binaire autonome CPU, VAD intégré, ~254 Mo en q8, pas de Python au
  runtime. **Le candidat évident pour un déploiement local.**
- **Hume AI** — 48+ catégories, 50+ langues, 600+ métriques, temps réel. Nommé
  « Expression Measurement » et non « emotion detection », ce qui est de la
  prudence scientifique, pas du marketing. Licence majeure signée avec Google
  DeepMind début 2026 : la capacité remonte dans les modèles généralistes.
- **Modèles audio natifs** (GPT realtime, Gemini Live) — réagissent
  implicitement à la prosodie sans exposer de label.

**Réserve de validité** : ces systèmes mesurent une *expression*, pas un état
interne. Quelqu'un qui parle vite peut être en colère, enthousiaste, ou
simplement méridional. Quelqu'un d'épuisé peut avoir une prosodie plate.
Recommandation : si prosodie il y a, ne pas consommer 48 catégories mais un
**scalaire d'activation** à trois crans (tendu / neutre / posé).

### 7.3 Variabilité de la fréquence cardiaque (le plus prometteur)

Ironie du dossier : le signal le plus fiable est aussi le moins problématique
juridiquement, parce qu'il est physiologique et non interprétatif.

- Protocole : biofeedback VFC à fréquence de résonance, ~0,1 Hz, soit 5,5 à 6
  respirations/minute. Un des protocoles les mieux étayés de l'affectif appliqué.
- Matériel : PPG de montre, ceinture cardio, ou webcam en rPPG (marche
  étonnamment bien au repos).
- **Bénéfice de conception majeur** : c'est la seule source qui fournit une
  boucle de validation objective. La mesure dit si l'intervention a marché. Sans
  ça, le mode hypersensible n'a aucun moyen de se calibrer.

---

## 8. La réponse : thermostat, pas miroir

Deux philosophies opposées, à ne pas confondre.

**Le miroir** renvoie l'état : rouge = tu es tendu. Problème : le rouge est un
signal d'alarme. L'utilisateur est déjà en hyper-activation et l'interface ajoute
un stimulus d'activation. On amplifie ce qu'on voulait apaiser. Pire, on ajoute
une couche méta : il est tendu *et* il sait que la machine le voit tendu.

**Le thermostat** compense. Désaturation, contraste plus doux, réponses plus
courtes, espacement plus large, streaming ralenti. Rien n'est annoncé, rien n'est
nommé. L'environnement devient moins stimulant. C'est de la co-régulation : on ne
dit pas à quelqu'un de se calmer, on baisse le volume de la pièce.

**Pacing then leading** : épouser brièvement le registre, puis mener ailleurs.
L'agent ne passe pas d'un coup de « voici quatre options avec tableaux
comparatifs » à une bougie parfumée. Il adopte d'abord un registre bref et
direct, puis ralentit progressivement. Avec la VFC, ce principe devient physique
et non sémantique : caler le rythme guidé sur la respiration actuelle, puis le
faire dériver vers la fréquence de résonance. L'utilisateur suit sans y penser.

---

## 9. Échelle d'intervention

Critère de tri : **le coût d'une fausse détection**.

### Étage 1 — Ambiant (coût nul si faux) — cible : 90 % du système

Couleur, densité, rythme, longueur des réponses. Si le système se trompe, on
récupère une palette un peu plus calme pendant vingt minutes. Aucune affirmation
n'a été émise, donc aucune ne peut être fausse.

### Étage 2 — Instrumental (l'apaisement qui marche vraiment)

Quand on est frustré à 23h parce qu'un build casse, ce qui détend n'est pas une
respiration carrée, c'est que le build passe. Donc :

- arrêter de proposer des refactos
- arrêter de donner trois options, en donner une
- prendre en charge la partie fastidieuse
- proposer un `git bisect`, ou « on repart de la version qui marchait »

Réduire la cause plutôt que traiter le symptôme.

### Étage 3 — Explicite (rare et risqué)

Formulation : l'agent parle de **son** côté et des **faits**, jamais de
l'intérieur de l'utilisateur.

> ❌ « Il me semble que tu es frustré. » — diagnostic déguisé en précaution.
>
> ✅ « On a relancé ce test six fois en vingt minutes et je ne suis pas sûr de
> t'aider là. Tu veux que je reprenne le problème à zéro, ou qu'on le mette de
> côté ? »

Observation factuelle + aveu d'incertitude sur sa propre utilité + question qui
rend la main. Aucune attribution mentale. L'utilisateur peut répondre « non ça
va » sans avoir à démentir un diagnostic sur sa personne.

**Sur la méditation** : proposée frontalement à quelqu'un qui débugue depuis
quatre heures, elle produit l'effet Clippy — le sentiment d'être géré. La version
qui fonctionne est propre à un agent et qu'aucune app de bien-être ne peut faire.

La vraie raison pour laquelle on ne s'arrête pas quand on est cuit n'est pas
qu'on n'y pense pas : c'est que s'arrêter coûte cher. On perd sa pile mentale,
les huit choses qu'on tenait en tête, et on sait que reprendre demain coûtera
quarante minutes. Un agent peut supprimer ce coût :

> « Je peux committer sur une branche, écrire où on en est et les trois pistes
> qu'on n'a pas testées. Tu reprends quand tu veux, je garde le fil. »

Ce n'est pas du bien-être plaqué, c'est une levée d'obstacle réelle.

---

## 10. Le pacte à froid

**L'utilisateur décide à froid de ce que l'agent a le droit de faire à chaud.**

À la configuration, calme, il signe le contrat : « si tu détectes trois heures de
session sans pause + trois échecs consécutifs, tu as le droit de m'interrompre
une fois. » Ulysse et le mât.

Parce que dans le moment, il rejettera tout — c'est la définition même d'être
crispé. Un agent qui applique une règle écrite par l'utilisateur lui-même n'est
pas paternaliste, il est **mandaté**. Ça change la nature de l'interruption.

Bénéfice secondaire : chaque interruption a une issue observable (acceptée /
rejetée / ignorée), ce qui alimente l'auto-régulation du §6.

---

## 11. Cadre juridique (UE)

> Synthèse de travail, pas un avis juridique. À faire valider si le projet sort
> d'un usage strictement personnel.

### 11.1 Le point qui compte : on n'est probablement pas dans le périmètre

Le considérant 18 de l'AI Act définit la reconnaissance d'émotion comme visant
« le bonheur, la tristesse, la colère, la surprise, le dégoût, l'embarras,
l'excitation, la honte, le mépris, la satisfaction et l'amusement », et exclut
explicitement **les états physiques, tels que la douleur ou la fatigue**.

Conséquences :

- Signaux comportementaux (§7.1) → hors définition. Ce ne sont même pas des
  données biométriques.
- VFC / activation physiologique (§7.3) → état physique, hors définition.
- **La ligne se franchit au moment où l'on traduit le signal en label
  émotionnel.** « VFC basse » = hors périmètre. « Tu es en colère » inféré depuis
  la VFC = système de reconnaissance d'émotion à partir de données biométriques.

C'est une frontière de *vocabulaire de sortie*. Ce qui est visé, c'est
l'inférence sur l'état mental, pas la mesure du corps. **Le design du §8 — ne
jamais nommer l'émotion — est donc simultanément le plus respectueux, le plus
honnête épistémiquement et le plus simple juridiquement.** Rare convergence : on
peut la traiter comme une contrainte de conception non négociable.

### 11.2 Ce qui est interdit, et où

Article 5(1)(f), en application depuis le 2 février 2025 : interdiction de
déduire les émotions d'une personne **sur son lieu de travail ou dans un
établissement d'enseignement**. Sanctions jusqu'à 35 M€ ou 7 % du CA mondial ;
en France, DGCCRF, CNIL et Arcom sont habilitées. La CNIL a annoncé qu'elle
sanctionnerait.

**Le consentement ne débloque rien.** C'est une interdiction objective, pas un
régime d'autorisation : le législateur considère que le déséquilibre de pouvoir
au travail rend tout consentement non libre par nature. Ce qui ouvre une porte,
c'est la finalité (médicale ou sécurité), pas l'information de la personne.

Depuis le 2 août 2026, les obligations de transparence de l'article 50 sont
applicables : informer que l'on interagit avec une IA, et **déclarer les systèmes
de reconnaissance d'émotions ou de catégorisation biométrique**.

### 11.3 Le piège de l'exemption médicale

L'exemption existe (considérant 44 : « systèmes destinés à un usage
thérapeutique »), mais l'emprunter fait entrer dans le règlement dispositifs
médicaux (MDR 2017/745) : marquage CE, organisme notifié, règle 11 sur les
logiciels qui pousse facilement en classe IIa, système qualité, évaluation
clinique. Et par ricochet, l'AI Act classe en **haut risque** un système d'IA
composant de sécurité d'un produit soumis à évaluation de conformité par tiers.

On quitterait la case « interdit » pour la case la plus lourde du règlement.
Rédhibitoire à cette échelle.

### 11.4 La ligne pratique : wellness, pas médical

Le critère est la **revendication**, pas la technologie. C'est là que vivent
Garmin, Oura, Apple, HeartMath.

| Formulation | Régime |
|---|---|
| « Guide une respiration à ta fréquence de résonance et affiche ta VFC » | Bien-être — libre |
| « Traite l'anxiété », « accompagne un patient » | Dispositif médical |

Le mot **patient** est celui qui coûte cher. Le remplacer par **utilisateur**
supprime le problème. Ne jamais écrire de claim thérapeutique dans la doc, le
README, la landing page ou les messages de l'agent.

### 11.5 Statut selon le mode de distribution

| Scénario | Analyse |
|---|---|
| Usage strictement personnel, local | Exemption d'activité personnelle. Hors RGPD, hors article 5 (pas d'employeur, pas de déployeur tiers). |
| Distribué en local, chacun chez soi, pour soi | L'utilisateur est son propre déployeur en usage personnel. Aucune donnée ne sort de la machine : pas de transfert, pas de sous-traitant, pas de traitement à déclarer. **C'est le modèle le plus propre.** |
| Déployé sur une équipe par un employeur | Article 5 s'applique. Zone rouge. |
| SaaS avec traitement côté serveur | RGPD article 9 (donnée de santé si VFC), consentement explicite, DPIA, minimisation. |

Attention : ce n'est pas le fait que ça tourne en local qui exonère
juridiquement, c'est l'usage personnel. Le local aide surtout parce qu'il rend le
reste défendable de fait — rien ne sort, donc rien à encadrer.

**Position recommandée pour Hermes Onirique** : distribution locale, open source,
sans revendication thérapeutique, sortie non émotionnelle, aucune télémétrie.
Cette combinaison est la seule qui soit à la fois conforme, honnête et cohérente
avec l'usage visé (auto-connaissance sans intermédiaire).

---

## 12. Ordre de prototypage

**Phase 1 — La voie double, sans détection d'état.**
`SIGNALS.md`, scoring par surprise, quarantaine, graduation, budget à 3
remontées/jour. Aucun capteur, aucune inférence sur l'utilisateur. Objectif :
valider que les signaux faibles retenus ont de la valeur. Mesure : taux
d'acceptation à la graduation.

**Phase 2 — Signaux comportementaux + étage ambiant.**
Compteurs de reformulation, `Ctrl-C`, durée de session. Sortie exclusivement
ambiante (§9 étage 1). Aucun texte, aucune interruption. Risque nul, apprentissage
maximal.

**Phase 3 — Étage instrumental + pacte à froid.**
L'agent change ses propositions. Une interruption explicite autorisée par
contrat. Journalisation des issues pour l'auto-régulation.

**Phase 4 — VFC optionnelle.**
Capteur au choix, boucle de biofeedback à fréquence de résonance. C'est
l'itération qui donne enfin une boucle de validation objective.

**Phase 5 — Prosodie, si et seulement si.**
SenseVoice en local, sortie réduite à un scalaire d'activation à trois crans.
À n'ajouter que si les phases 1-4 montrent une lacune que la prosodie comble.

---

## 13. Questions ouvertes

- Le mode doit-il rester un interrupteur, ou devenir un canal permanent à seuil
  variable ? (l'analogie biologique penche pour le second, l'ingénierie pour le
  premier)
- Comment calibrer le budget d'hypothèse nulle sans corpus de référence ?
- Le silence (§3) est le signal le plus prometteur et le seul sans
  implémentation évidente. Modèle de « ce qui aurait dû être là » à concevoir.
- Faut-il exposer `SIGNALS.md` à l'utilisateur, ou le garder interne jusqu'à
  graduation ? Argument pour : transparence, auto-connaissance. Argument contre :
  lire la liste de tout ce que la machine a remarqué sur soi est exactement le
  type d'expérience qu'on cherche à éviter.
