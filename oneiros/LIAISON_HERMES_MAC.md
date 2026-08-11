# Brancher Hermes sur le Mac — anatomie de la liaison

Document technique transversal. État relevé le **8 août 2026**.

## Pourquoi ce document existe

Les autres fichiers du dossier disent **quoi faire**. Celui-ci dit **ce qui a
réellement été fait**, dans quel ordre, contre quoi on a buté, et pourquoi
chaque obstacle a été franchi de cette façon plutôt qu'une autre.

Il existe parce qu'une procédure réussie ne se relit pas comme elle s'est
vécue. `MODELE_MAC.md` présente sept réglages sur une même page ; en réalité
six d'entre eux ont été posés à l'aveugle et un seul expliquait la panne. Ce
document rétablit la hiérarchie : quelle couche portait quel échec, et quelle
commande a tranché.

Il sert deux usages : reconstruire la liaison si elle casse, et comprendre
avant de la modifier.

---

## 1. Deux liaisons, pas une

« Brancher Hermes sur le Mac » recouvre deux choses distinctes, qui n'ont ni le
même niveau de maturité, ni les mêmes propriétés de sécurité, ni le même mode
de panne. Les confondre est la première source de confusion dans ce projet.

| | **Plan de données** | **Plan de contrôle** |
|---|---|---|
| Ce qui transite | tokens : prompts et complétions | commandes : `ingest`, `queue`, `status`, dépôts de fichiers |
| Port | **1234** (HTTP, OpenAI-compatible) | **22** (SSH) |
| Côté Mac | LM Studio, sous le compte principal | compte `hermes`, Standard, sans privilèges |
| Authentification | aucune (LAN de confiance) | clés ed25519, commande forcée |
| Direction de la donnée | Mac → VM (les réponses **sortent** du Mac) | VM → Mac (les fichiers **entrent**) |
| Sans lui, Hermes… | ne pense pas | pense, mais ne touche pas au second cerveau |
| **État** | **opérationnel et mesuré** | **conçu, non posé** — voir §9 |

Le plan de données est ce qui a été « réussi ». Il est validé, chronométré, et
c'est lui qui fait tourner l'agent aujourd'hui. Le plan de contrôle est décrit
en détail dans `HERMES_MAC.md` et `CLOISONNEMENT.md`, mais
[config.yaml:40](config.yaml) porte toujours `terminal.backend: local` : Hermes
ne parle pas encore au Mac par SSH.

Ce document traite donc principalement du plan de données, et situe le plan de
contrôle dans l'architecture pour que la suite du travail ait un cadre.

Une asymétrie mérite d'être notée tout de suite, parce qu'elle explique
l'ensemble du montage : **le plan de données fait sortir de l'information du
Mac, le plan de contrôle en fait entrer.** C'est pour cette raison que le
premier peut se permettre de n'avoir aucune authentification, et que le second
est bordé par des commandes forcées et des ACL. Ce qui sort d'une machine
hors-ligne est ce qu'on surveille ; ce qui y entre est la direction sûre.

---

## 2. La chaîne complète

### 2.1 Le trajet d'un tour d'agent

```
  ┌─ PC Windows 10 ───────────────────────────────────┐
  │                                                    │
  │   hermes.cmd ──ssh──▶ ┌─ VM Ubuntu 24.04 ───────┐  │
  │   (clé hermes_vm)     │                          │  │
  │                       │   Hermes Agent           │  │
  │                       │   ~/.hermes/config.yaml  │  │
  │                       │        │                 │  │
  │                       └────────┼─────────────────┘  │
  │                                │ HTTP                │
  │                        NAT VMware (VMnet8)          │
  │                                │                     │
  └────────────────────────────────┼─────────────────────┘
                                   │  LAN 192.168.1.0/24
                                   ▼
                    ┌─ Mac M1 Ultra 64 Go ─────────────┐
                    │  0.0.0.0:1234                     │
                    │  LM Studio ─ runtime MLX          │
                    │  Qwen3-Coder-30B-A3B-Instruct 4b  │
                    │  hors ligne (aucune route sortante)│
                    └───────────────────────────────────┘
```

Le PC n'exécute que l'hyperviseur et un client SSH. Le Mac n'exécute qu'un
serveur d'inférence. Toute la logique d'agent vit dans la VM, qui est la seule
des trois machines à être à la fois exposée à Internet et jetable.

### 2.2 Les sauts, et ce qui casse à chacun

Un `POST /v1/chat/completions` traverse sept frontières. Chacune a son mode de
panne propre, et chacune donne une erreur différente — c'est ce qui permet de
localiser un incident sans tout reprendre.

| # | Saut | Panne typique | Symptôme observé |
|---|---|---|---|
| 1 | Hermes → sa config | `base_url` faux, `/chat/completions` ajouté à la main | 404 |
| 2 | Pile réseau de la VM | pas de route, DNS absent | `Network unreachable` |
| 3 | VMnet8 → NAT VMware | service VMware NAT arrêté | timeout |
| 4 | Hôte Windows → LAN | pare-feu sortant Windows | timeout |
| 5 | LAN → Mac | Mac à une autre IP, mauvais `/24` | timeout |
| 6 | Pare-feu macOS | LM Studio non autorisé | **timeout**, jamais un refus |
| 7 | Bind de LM Studio | serveur sur `127.0.0.1` | **connection refused** |

La ligne 6 et la ligne 7 sont à retenir ensemble, parce qu'elles se
distinguent par un détail qui fait gagner une heure :

> **Le pare-feu macOS `DROP` en silence, il ne `REJECT` pas.** Un timeout
> désigne donc le réseau ou le pare-feu ; un *connection refused* désigne LM
> Studio. Dans le second cas la machine a répondu — le réseau est bon, ne le
> cherche pas.

Ce raisonnement est câblé dans [test_endpoint.py:63-96](test_endpoint.py), qui
branche sur `timed out` ou `refused` pour n'afficher que la liste de pistes
pertinente. C'est le seul endroit du projet où un script fait du diagnostic
plutôt que du test.

---

## 3. La décision structurante : le modèle reste sur le Mac

Tout le reste découle de ce choix, y compris l'existence du réseau entre les
deux machines. Il aurait été plus simple de tout mettre dans la VM.

**Ce n'est pas possible.** Un hyperviseur de type 2 n'expose pas Metal au
système invité. Un modèle chargé dans la VM Ubuntu retomberait sur l'inférence
CPU : sur ce gabarit, un ordre de grandeur de perte, et un agent inutilisable.
La mémoire unifiée d'Apple Silicon n'a pas d'équivalent virtualisable — c'est
elle qui fait tenir 17 Go de poids sans transfert PCIe.

La conséquence est acceptée franchement : **l'inférence traverse le réseau, et
le réseau devient une dépendance de premier ordre.** D'où le soin porté à
l'adressage (§4.3), et d'où le fait qu'un Mac endormi se traduise par un Hermes
qui timeout, pas par un Hermes lent.

Le second choix, imbriqué dans le premier, est celui de l'architecture du
modèle. Le tableau de `MODELE_MAC.md` §3 le montre par les chiffres, mais la
raison tient en une phrase :

> Le M1 Ultra a beaucoup de bande passante mémoire (800 Go/s) et peu de compute
> par cœur. Un MoE à 3 B de paramètres actifs exploite la première sans buter
> sur la seconde.

Vérification par ordre de grandeur : un dense de 30 B en 4-bit lit ~17 Go de
poids par token généré, soit un plafond théorique autour de 47 tok/s avant
toute inefficacité — ce qui cadre avec les 15–22 tok/s constatés en pratique
sur cette ligne du tableau. Un MoE à 3 B actifs lit environ dix fois moins :
la bande passante cesse d'être le facteur limitant, et les **58–61 tok/s
mesurés** sont bornés par autre chose (surcoût par token, attention sur le
KV cache), pas par la mémoire.

Même empreinte disque, trois fois le débit. C'est ce qui a fait retenir
`Qwen3-Coder-30B-A3B-Instruct` en MLX 4-bit, et non un dense plus fin.

---

## 4. Les cinq verrous qu'il a fallu lever

Chacun a produit une panne réelle. Ils sont classés dans l'ordre où ils se
manifestent quand on remonte la chaîne depuis Hermes.

### 4.1 Le bind — le serveur tourne et reste invisible

**Symptôme.** LM Studio répond parfaitement sur le Mac. Depuis la VM :
*connection refused*.

**Cause.** Par défaut, le serveur local n'écoute que sur `127.0.0.1`. Le mot
« local » de *Local Model API* désigne la machine, pas le réseau local. Le
serveur est démarré, le modèle est chargé, et rien ne sort de la boucle.

**Correctif.** Le CLI, parce qu'il ne dépend d'aucune version d'interface :

```bash
lms server stop
lms server start --bind 0.0.0.0
lms server status
```

**La commande qui tranche**, sur le Mac :

```bash
lsof -nP -iTCP:1234 -sTCP:LISTEN
```

`127.0.0.1:1234` = toujours en loopback. `*:1234` ou `0.0.0.0:1234` = exposé.
Aucune autre vérification n'est nécessaire à ce niveau, et aucune autre ne
suffit : un `curl http://localhost:1234` réussit dans les deux cas.

**Le piège de second ordre**, et il a coûté du temps : le réglage graphique
équivalent (*Serve on Local Network*) **n'apparaît pas** tant que LM Studio est
en mode *User*. L'écran *Local Model API* doit exposer neuf réglages ; s'il en
montre trois, ce n'est pas que la version est trop ancienne ou qu'il manque un
compte — c'est le sélecteur **User / Power User / Developer** en bas de la
fenêtre principale. LM Studio ne demande aucun sign-in pour servir un modèle.

### 4.2 Le pare-feu macOS — il raisonne par application

**Symptôme.** Le bind est bon, `lsof` montre `0.0.0.0:1234`, et la VM
timeout quand même.

**Cause.** Le pare-feu macOS ne connaît pas les numéros de port. Il autorise ou
refuse des **applications**. « Ouvrir le port 1234 » n'a donc littéralement pas
de traduction dans cette interface : la formulation correcte est « autoriser LM
Studio ».

**Correctif.** Réglages → Réseau → Pare-feu → Options… :

- **« Bloquer toutes les connexions entrantes » décoché.** Cette case fait
  exactement l'inverse de ce qu'on veut et coupe le port. Le pare-feu lui-même
  peut rester activé.
- **LM Studio** en *Autoriser les connexions entrantes*. S'il n'est pas dans la
  liste, démarrer le serveur une fois : macOS affiche la popup d'autorisation
  et l'entrée apparaît.

**Le détail qui rend ce verrou coûteux** est qu'il tombe en silence. Un pare-feu
qui refuserait proprement se diagnostiquerait en une seconde ; celui-ci laisse
les paquets mourir, et le symptôme est indiscernable d'un mauvais adressage.
C'est la raison d'être de la distinction timeout / refused du §2.2.

### 4.3 L'adressage — deux piles, une seule coupée

Trois problèmes distincts se sont superposés ici.

**a. Le bail DHCP.** Si l'adresse du Mac change, `base_url` pointe dans le
vide. Le routeur Starlink **ne sait pas faire de réservation DHCP** — ni l'app,
ni l'interface web sur `192.168.1.1` n'exposent de table de baux. L'adresse est
donc fixée côté Mac, en manuel : `192.168.1.50/24`.

En Wi-Fi, il faut aussi passer **Adresse Wi-Fi privée** sur *Désactivée*, sans
quoi macOS change d'adresse matérielle sur ce réseau.

**b. La double pile.** C'est le piège le plus coûteux du dossier. Le Mac doit
être hors ligne tout en restant sur le LAN, ce qui se fait en vidant le champ
*Routeur* : plus de route IPv4 par défaut, mais le `192.168.1.0/24` reste
joignable.

Sauf que **le réseau Starlink est en double pile**. Il annonce par RA un
préfixe IPv6 public (`2a0d:…`), sa passerelle et son DNS. Vider le champ
IPv4 ne coupe rien du tout : le Mac continue de sortir par l'autre pile. Les
deux verrous se posent ensemble :

| Verrou | Emplacement | Hors ligne |
|---|---|---|
| Route IPv4 | TCP/IP → Routeur | vide |
| Route IPv6 | TCP/IP → Configurer IPv6 | Désactivé |
| Résolution de noms | onglet DNS | aucune entrée |

```bash
sudo networksetup -setv6off "Wi-Fi"
sudo networksetup -setdnsservers "Wi-Fi" empty
```

**c. Le faux positif de diagnostic.** `netstat -rn | grep default` remonte les
routes des interfaces `utun4` à `utun7`, tunnels créés par le relais privé
iCloud et Continuité. Leur passerelle est en `fe80::`, donc lien-local : elles
ne mènent nulle part. Les voir listées est normal et ne prouve rien.

**La commande qui tranche** :

```bash
route -n get default      # doit repondre "not in table"
```

Et il faut traiter **chaque interface active**, pas seulement le Wi-Fi : un Mac
Studio a un port Ethernet qui, s'il est branché, porte sa propre route par
défaut et annule tout le reste. `networksetup -listallnetworkservices` donne la
liste.

**Ce que ce verrou ne fait pas.** Il empêche le Mac d'*initier* des connexions
sortantes. Il n'empêche personne d'entrer : le port 1234 écoute sur `0.0.0.0`
sans authentification, et dès l'activation de *Session à distance*, le port 22
s'ouvre au même LAN. **L'isolation est dirigée vers l'extérieur, pas vers
l'intérieur** — c'est précisément le trou que `CLOISONNEMENT.md` vient combler,
et la raison pour laquelle ce fichier existe.

### 4.4 Le réseau de la VM — le bridged a échoué, on a documenté le repli

**Ce qui était prévu.** Mode *bridged* : la VM obtient une adresse du LAN
(`192.168.1.60`), le Mac la voit comme une machine distincte du PC, et la
restriction `from="192.168.1.60"` dans `authorized_keys` devient opérante.

**Ce qui s'est passé.** Le pontage a échoué sur cet hôte : VMnet0 en pontage
*automatique* ne délivre pas de DHCP. Le suspect principal est identifié —
l'adaptateur **VirtualBox Host-Only Network**, resté actif en `192.168.56.1`
sans route vers le LAN, parmi lequel le choix automatique de VMware pioche
([NETTOYAGE.md:84](NETTOYAGE.md)).

**La décision.** Rester en NAT, et le documenter comme un repli diagnostiqué
plutôt que comme une dérive. Le `.vmx` porte le commentaire, le snapshot
s'appelle `01-hermes-fonctionnel-nat`, et `CLOISONNEMENT.md` classe le retour
au bridged en **étape 0, optionnelle**.

C'est un arbitrage qui mérite d'être explicite, parce qu'il se reproduira :

> Le NAT retire **une couche, pas la structure.** Restent intactes et
> indifférentes au mode réseau : la clé privée qui ne vit que dans la VM,
> `PasswordAuthentication no`, les commandes forcées, les comptes Standard, les
> ACL du vault. Ce sont elles qui portent le poids.

Ce que le NAT coûte réellement : vu du Mac, la VM et le PC partagent la même
adresse source. Le préfixe `from=` refuserait alors tout le monde — **il doit
être omis tant que l'étape 0 n'a pas abouti.** Et l'analyse honnête est que
`from=` protégeait d'un scénario (vol de la clé puis usage direct depuis le PC)
moins probable que le pivot `PC → VM → Mac`, que `from=` ne bloque de toute
façon pas puisque la connexion vient alors réellement de la VM.

**Pour le plan de données, le NAT est sans conséquence** : une connexion
sortante de la VM vers `192.168.1.50:1234` traverse le NAT sans rien demander.
C'est uniquement le plan de contrôle qui perd une couche.

Si le pontage est retenté : désinstaller VirtualBox d'abord, puis lier `VMnet0`
explicitement à l'adaptateur **Wi-Fi** dans le *Virtual Network Editor*, VM
éteinte — jamais *Automatique*, c'est le choix automatique qui se trompait de
carte. Et de préférence en Ethernet, puisque c'est le pontage Wi-Fi qui a
échoué.

### 4.5 La résidence du modèle — TTL, et la double instance

Deux comportements de LM Studio se combinent pour produire une panne
déroutante.

**a. Le TTL invisible.** Les modèles chargés en *just-in-time* portent un TTL
de 60 minutes, réinitialisé à chaque requête. En usage soutenu il n'expire
jamais ; après une heure d'inactivité, le modèle est libéré et l'appel suivant
paie ~20 s de rechargement. Gênant, pas bloquant — mais suffisant pour faire
croire à une latence réseau erratique.

**b. La double instance, plus sérieuse.** `lms load` **ne reprend pas** une
instance déjà chargée : il en empile une seconde. Si un appel API a déjà
déclenché un chargement JIT, on se retrouve avec deux exemplaires en mémoire —
32 Go au lieu de 16 — et le second porte l'identifiant `…-mlx:2`. Pire :
**c'est l'instance au nom propre qui garde le TTL**, donc celle qui disparaîtra.

Le symptôme est un `model.default` qui cesse de correspondre à quoi que ce soit,
une heure après le démarrage, sans que rien n'ait été touché.

**Le geste correct**, systématiquement :

```bash
lms unload --all
lms load qwen3-coder-30b-a3b-instruct-mlx
lms ps                     # doit lister UNE instance, sans suffixe
```

**Sans** `--ttl`, un modèle chargé par `lms load` n'a aucun TTL et reste
résident jusqu'à déchargement manuel. Le JIT peut rester activé à côté comme
filet de sécurité — c'est même souhaitable, parce que `lms load` ne survit pas
au redémarrage : au premier appel après un reboot, le JIT recharge en ~20 s au
lieu d'échouer.

**L'identifiant renvoyé par `lms load` fait foi.** C'est lui, et pas le nom
affiché dans l'interface, qui doit figurer dans `model.default` de
[config.yaml:18](config.yaml).

---

## 5. Répondre ne suffit pas : le contrat applicatif

Les cinq verrous du §4 donnent un endpoint qui répond. Ils ne donnent pas un
agent qui fonctionne. Ce qui suit est la seconde moitié du travail, et elle
est moins visible parce qu'elle ne produit pas de panne franche — elle produit
des comportements erratiques.

### 5.1 Le tool calling est le seul test qui décide

Hermes est un agent : à chaque tour il envoie un system prompt long, une liste
d'outils, et attend un **appel d'outil bien formé**. Si le modèle répond en
prose au lieu d'émettre un `tool_calls`, Hermes s'installe parfaitement et se
révèle incapable de lire un fichier ou de lancer une commande.

C'est la raison pour laquelle [test_endpoint.py:180](test_endpoint.py) ne se
contente pas de vérifier qu'un outil a été appelé. Il vérifie, dans l'ordre :

1. que la requête avec `tools` ne renvoie pas un 400 — un 400 ici signifie que
   le runtime ignore le paramètre ;
2. qu'un `tool_calls` est présent et non vide ;
3. que le **nom** de l'outil est exact ;
4. que les **arguments** sont du JSON parsable ;
5. que le **schéma** est respecté (le paramètre `city` est là).

Les étapes 4 et 5 attrapent le pire cas de tous : un modèle qui appelle l'outil
correctement quatre fois sur cinq. Hermes échoue alors **par intermittence**,
ce qui est beaucoup plus long à diagnostiquer qu'un échec franc.

En cas d'échec, l'ordre de dépannage est contre-intuitif et il est important —
on ne change pas de modèle en premier :

| # | Vérifier | Pourquoi avant les autres |
|---|---|---|
| 1 | Context Length ≥ 32768 **et** KV Cache Quantization désactivée | La quantization *annule* la valeur du Context Length. C'est la cause n° 1. |
| 2 | Le template de chat est bien *Template (Jinja)* | Un template générique casse le format d'appel propre à Qwen. |
| 3 | Basculer MLX ↔ GGUF | Le support du tool calling diffère parfois entre deux builds d'un même modèle. |
| 4 | Alors seulement, changer de modèle | |

### 5.2 Le réglage qui casse tout en silence

**Context Length.** Le défaut de LM Studio est très en dessous de ce qu'un
agent consomme. Trop court, le prompt d'Hermes est tronqué **sans erreur**, et
les appels d'outils partent en vrille. C'est le réglage le plus souvent en
cause dans ce dossier.

**KV Cache Quantization.** Elle annule le Context Length ci-dessus — LM Studio
le dit lui-même, en rouge, sous la case. Et elle ne sert à rien ici : à 64 K le
cache pèse de l'ordre de 6 Go, on en a 25 de marge. Marquée *Experimental*,
c'est une variable en moins le jour où le tool calling déconne.

La combinaison des deux produit exactement le pire scénario possible : un
réglage qui a l'air posé et qui est ignoré.

### 5.3 Où vivent réellement les paramètres d'échantillonnage

Point d'architecture facile à manquer : [config.yaml](config.yaml) ne définit
**ni température ni top_p**. Hermes n'envoie donc aucun paramètre
d'échantillonnage dans ses requêtes.

**Conséquence : l'écran *Model Default Configuration* de LM Studio fait foi
sans recours.** Un `temperature: 0.8` laissé au défaut là-bas s'applique à
toutes les requêtes de l'agent, et aucune relecture de `config.yaml` ne le
révélera jamais.

Les valeurs retenues, et leur justification :

| Réglage | Valeur | Défaut | Pourquoi |
|---|---|---|---|
| Temperature | **0,2** | 0,8 | 0,8 est du chat créatif. Un agent qui appelle des outils doit être ennuyeux et reproductible. |
| Top K | **20** | 100 | Valeur recommandée par Qwen pour ce modèle. |
| Repeat Penalty | **décochée** ou 1,05 | 1,1 | Le code et le JSON sont faits de répétitions légitimes. À 1,1, la pénalité peut casser un appel d'outil en plein milieu. |
| System Prompt | vide | — | Hermes envoie le sien. |

Trois réglages qu'on cherche en vain sur cet écran, et dont l'absence n'est pas
un symptôme : **GPU Offload** n'existe pas en MLX (mémoire unifiée, tout est
déjà sur le GPU) ; **Flash Attention** est spécifique à llama.cpp/GGUF ;
**Keep Model in Memory** est un réglage serveur, traité au §4.5.

### 5.4 Le prefill commande la compression

C'est le résultat de mesure le plus utile du projet, et il a changé un réglage.

Un agent ne génère pas beaucoup de tokens — il en **relit** beaucoup. À chaque
tour, tout le contexte accumulé repasse en prefill. Les mesures :

| Mesure | Valeur |
|---|---|
| Génération | 58–61 tok/s |
| **Prefill à froid** | **~570 tok/s** |

À 570 tok/s, un contexte de 30 K se relit en **~53 s**, payées à *chaque* tour.
La génération de 300 tokens qui suit coûte 5 s. **Le prefill domine d'un ordre
de grandeur**, et bien avant que la mémoire ne sature.

D'où `compression.threshold: 0.50` dans [config.yaml:59](config.yaml) : la
compression se déclenche à la moitié de la fenêtre, soit ~16 K sur une fenêtre
de 32 K, ce qui plafonne le prefill autour de 29 s par tour. `target_ratio:
0.20` ramène ensuite le contexte à un cinquième, `protect_last_n: 20` et
`protect_first_n: 3` préservent les tours récents et l'amorce.

Ce n'est donc pas un réglage de prudence mémoire. C'est un réglage de latence,
dérivé d'un chiffre mesuré.

### 5.5 Deux pièges de mesure, et comment le script les neutralise

Les deux se traduisent par des chiffres flatteurs et faux.

**Mesurer le premier appel** inclut les ~20 s de chargement des poids et donne
un débit absurde — de l'ordre de 2 tokens en 21 secondes. Le script fait
désormais un appel de préchauffage à `max_tokens: 1` avant de chronométrer, et
signale le temps de chargement s'il dépasse 5 s
([test_endpoint.py:128-138](test_endpoint.py)).

**Rejouer deux fois le même prompt long** donne des milliers de tok/s de
prefill : LM Studio réutilise le KV cache et ne recalcule rien. Le script
préfixe le texte de remplissage par un nonce horodaté, ce qui invalide le cache
et force un vrai prefill ([test_endpoint.py:270](test_endpoint.py)).

Le second piège est le plus dangereux des deux, parce que le chiffre obtenu est
crédible sur la première exécution et faux sur toutes les suivantes.

---

## 6. La méthode de validation

Un principe a guidé la construction, et il vaut au-delà de ce projet :
**valider chaque couche avant d'en construire une autre au-dessus.**

L'endpoint a été testé depuis Windows **avant** que la VM n'existe. Ce n'est
pas une précaution de confort : cela sépare définitivement les défauts du Mac
des défauts de la virtualisation. Une panne apparue après l'installation de la
VM ne peut plus venir de LM Studio, puisque LM Studio a été prouvé bon
auparavant.

Puis rejoué **depuis la VM**, ce qui valide la couche réseau de VMware et
rien d'autre.

`test_endpoint.py` est écrit en **stdlib uniquement**, sans aucun `pip install`.
Cette contrainte n'est pas de l'ascétisme : l'outil de diagnostic doit
fonctionner sur une machine hors ligne, et un outil de diagnostic qui a besoin
du réseau pour s'installer est inutile exactement le jour où on en a besoin.

Ses quatre blocs vont du plus fondamental au plus exigeant :

| Bloc | Ce qu'il prouve | Ce qu'il ne prouve pas |
|---|---|---|
| `1/4` Joignabilité | **La totalité du réseau** : IP, routage, pare-feu, bind | rien sur le modèle |
| `2/4` Complétion | le modèle répond, et à quel débit | rien sur l'usage agent |
| `3/4` Tool calling | **le modèle est exploitable par Hermes** | — |
| `4/4` Contexte + prefill | un prompt long passe, et à quel coût par tour | — |

Un `[ OK ] endpoint joignable` dans le bloc `1/4` valide donc **toute** la
partie réseau, d'un coup. Si ce bloc passe et que le `3/4` échoue, il n'y a
plus une seule raison de toucher au réseau, au pare-feu ou à l'adressage.

Cette propriété est ce qui rend le script utile : il ne dit pas seulement ce qui
ne va pas, il dit **où arrêter de chercher**.

---

## 7. Les chiffres relevés

Machine : Mac M1 Ultra 64 Go de mémoire unifiée, 800 Go/s de bande passante.
Modèle : `Qwen3-Coder-30B-A3B-Instruct`, MLX 4-bit, résident.

| Mesure | Valeur | Commentaire |
|---|---|---|
| Génération | **58–61 tok/s** (299 tokens) | dans la fourchette annoncée |
| Prefill à froid | **~570 tok/s** (9 600 tokens) | le poste dominant |
| Chargement des poids | ~6 s par `lms load`, ~20 s en JIT | à payer au premier appel après reboot |
| Empreinte des poids | ~17 Go | sur ~45–48 Go réellement allouables au GPU |
| Marge restante | ~25 Go | KV cache + macOS, sans `sysctl` |

**Budget mémoire réel.** 64 Go de mémoire unifiée ne sont pas 64 Go pour le
modèle : macOS plafonne l'allocation GPU autour de 70–75 %. Le plafond est
relevable à la main (`sudo sysctl iogpu.wired_limit_mb=57344`, non persistant),
mais **le modèle retenu n'en a pas besoin** — et c'est un argument de choix à
part entière. Laisser au moins 8 Go à macOS : au-delà, memory pressure rouge,
swap, et l'endpoint devient inutilisable en même temps que la machine.

---

## 8. Diagnostic : du symptôme à la couche

Table d'entrée en cas de panne. La colonne de droite est la commande qui tranche
— celle dont le résultat élimine une moitié de l'arbre.

| Symptôme | Couche probable | Commande qui tranche | Où |
|---|---|---|---|
| `connection refused` | bind LM Studio (§4.1) | `lsof -nP -iTCP:1234 -sTCP:LISTEN` | Mac |
| timeout depuis la VM, OK depuis Windows | réseau VMware (§4.4) | `ip -br a` puis `curl` | VM |
| timeout depuis Windows **et** la VM | pare-feu macOS ou IP (§4.2, §4.3) | `ping 192.168.1.50` | Windows |
| tout timeout, ping OK | pare-feu macOS (§4.2) | liste des apps autorisées | Mac |
| a marché hier, plus aujourd'hui | bail DHCP ou Mac endormi | `ipconfig getifaddr en0` | Mac |
| latence de ~20 s au premier appel | TTL JIT (§4.5) | `lms ps` | Mac |
| `model not found` après une heure | double instance `…-mlx:2` (§4.5) | `lms ps` | Mac |
| 404 sur les complétions | `/chat/completions` en trop dans `base_url` | `hermes config get model.base_url` | VM |
| réponses en prose au lieu d'outils | tool calling (§5.1) | `test_endpoint.py` bloc `3/4` | VM |
| appels d'outils erratiques | Context Length / KV quant (§5.2) | écran *Model Default Configuration* | Mac |
| chaque tour prend une minute | prefill (§5.4) | bloc `4/4` | VM |
| le Mac semble hors ligne à tort | routes `utun` (§4.3c) | `route -n get default` | Mac |

**Deux règles de lecture** de cette table :

- Un timeout n'est jamais un refus. Le Mac qui `DROP` et le Mac absent
  produisent le même symptôme ; seul le `ping` les sépare.
- Un Mac sans passerelle reste **parfaitement joignable sur le LAN**. Le mode
  hors ligne n'est jamais la cause d'une panne d'endpoint — c'est la fausse
  piste la plus tentante du dossier, et elle est explicitement démentie dans
  [test_endpoint.py:76](test_endpoint.py).

---

## 9. État exact au 8 août 2026

Ce que ce document ne fera pas : laisser croire que tout est en place.

### Opérationnel

| Élément | État |
|---|---|
| LM Studio servant sur `0.0.0.0:1234` | en service |
| `Qwen3-Coder-30B-A3B-Instruct` MLX 4-bit résident | chargé, mesuré |
| Mac à `192.168.1.50`, hors ligne, deux verrous posés | en service |
| VM Ubuntu 24.04 sous VMware, mode **NAT** | en service, snapshot `01-hermes-fonctionnel-nat` |
| Hermes dans la VM, `base_url` validé depuis Windows **et** depuis la VM | en service |
| Lancement par [hermes.cmd](hermes.cmd) | en service |
| Migration VirtualBox → VMware | faite le 2 août 2026 |

### Conçu, non posé

| Élément | Bloqué par | Document |
|---|---|---|
| Comptes macOS `hermes` et `opencode` | rien — travail à faire | `CLOISONNEMENT.md` §3 |
| Vault partitionné dans `/Users/Shared/SecondBrain` + ACL | nom exact de `raw/` à relever | `CLOISONNEMENT.md` |
| Deux clés SSH `mac_job` / `mac_sftp` | rien | `HERMES_MAC.md` §3 |
| Trappe `/Users/hermes/bin/hermes-job` | rien | `HERMES_MAC.md` §4 |
| Montage SSHFS lecture seule sur `Ouvert/` | dépend des ACL | `HERMES_MAC.md` §6 |
| Règle `pf` par UID pour `opencode` | dépend des comptes | `OPENCODE_MAC.md` §3 |
| LaunchDaemons d'ingestion | dépend de `raw/` | `OPENCODE_MAC.md` §6 |
| VM en bridged + `192.168.1.60` fixe | pontage échoué, optionnel | `CLOISONNEMENT.md` §0-1 |

### Le point urgent, indépendant de tout le reste

`C:\Users\antho\.ssh\hermes_vm` est **sans passphrase**. Tout agent disposant
d'un shell sur Windows ouvre donc la VM — et héritera du Mac le jour où la VM y
aura une clé. C'est le chemin réellement praticable aujourd'hui, et c'est
trente secondes de travail :

```powershell
ssh-keygen -p -f C:\Users\antho\.ssh\hermes_vm
```

L'asymétrie est voulue et vaut d'être comprise : la clé PC → VM porte une
passphrase parce qu'**un humain la tape** et qu'un agent autonome ne le peut
pas ; les clés VM → Mac n'en portent pas, parce qu'Hermes se connecte sans toi
et qu'une passphrase casserait le pilotage par Telegram. Elles sont protégées
autrement — par l'endroit où elles vivent, et par la commande forcée qui borne
ce qu'elles ouvrent.

### Incohérences documentaires relevées

Elles n'empêchent rien de fonctionner aujourd'hui, mais elles feront perdre du
temps au moment de poser le plan de contrôle.

| # | Constat | Fichiers |
|---|---|---|
| 1 | Le sas d'entrée est appelé `Entree/` à un endroit et `raw/` à l'autre, dans le même fichier | [HERMES_MAC.md:41](HERMES_MAC.md) et §7 / vérifs 7-8 |
| 2 | Les vérifications parlent d'une clé `mac_hermes` unique, alors que le montage en compte deux (`mac_job`, `mac_sftp`) | [CLOISONNEMENT.md:430](CLOISONNEMENT.md), *Philosophie des clés* |
| 3 | La vérification `ssh … whoami` attend `hermes`, mais la commande forcée renverra `commande refusee` | [CLOISONNEMENT.md:430](CLOISONNEMENT.md) |
| 4 | Le README annonce le mode **bridged** alors que la VM tourne en NAT | [README.md:7](README.md) |
| 5 | `hermes.cmd` interroge encore `vmrun getGuestIPAddress`, donc l'étape 1 (IP fixe de la VM) n'est pas appliquée | [hermes.cmd:36](hermes.cmd) |

La n° 2 et la n° 3 sont les vestiges d'une version antérieure du montage, à une
seule clé et à shell libre. Elles décrivent un état que le montage actuel refuse
délibérément.

---

## 10. Ce que ce montage enseigne

Cinq principes se sont dégagés du travail. Ils sont transférables.

**Valider de bas en haut, et une couche à la fois.** Tester l'endpoint depuis
Windows avant que la VM n'existe a séparé définitivement deux familles de
pannes. Toute couche prouvée bonne est une couche qu'on ne rouvrira plus.

**Un outil de diagnostic ne doit dépendre de rien.** `test_endpoint.py` est en
stdlib pure parce que le jour où on en a besoin est précisément le jour où
`pip` ne passe pas.

**Distinguer le symptôme silencieux du symptôme franc.** Un `DROP` et un
`REJECT` se ressemblent pour l'utilisateur et désignent des couches opposées.
Toute la valeur d'un diagnostic tient dans ce genre de discrimination, pas dans
la longueur de la liste de vérifications.

**Documenter les replis comme des décisions, pas comme des dettes.** Le NAT
n'est pas une dérive : c'est un pontage tenté, échoué, diagnostiqué, et une
analyse de ce que la couche perdue protégeait réellement. Un repli non
documenté redevient un mystère en trois semaines.

**Mesurer avant de régler.** `compression.threshold: 0.50` n'est pas une valeur
de précaution — c'est la conséquence directe des 570 tok/s de prefill. Et les
deux pièges du §5.5 rappellent qu'une mesure mal instrumentée est pire qu'une
absence de mesure, parce qu'elle est convaincante.

Un dernier, qui gouverne l'architecture entière et déborde la question du
branchement :

> **Le Mac a les données et pas de sortie. La VM a la sortie et pas les
> données.** Le port 1234 est la seule chose qui traverse cette frontière, et
> il ne transporte que des tokens.

C'est la phrase à relire avant toute modification de ce montage. Chaque fois
qu'un changement rendra cette phrase fausse, il faudra en mesurer le prix
explicitement.
