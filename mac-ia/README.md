# mac-ia

Ce qui tourne sur le Mac Studio pour servir trois usages — **code**, **second
cerveau**, **chat VR vocal** — au-dessus de LM Studio.

Le plan complet est dans
`~/.claude/plans/je-veux-piloter-hermes-humble-raven.md`. Les cinq verrous du
montage réseau sont dans `oneiros/LIAISON_HERMES_MAC.md` — à lire **avant** de
diagnostiquer quoi que ce soit qui ressemble à une panne de liaison.

## La règle qui explique la forme du dépôt

**Tout est en stdlib, sauf `voice/`.**

Le Mac n'a pas de route par défaut : IPv4 vidée, IPv6 désactivé, DNS vide. C'est
voulu — c'est ce qui protège le corpus. Conséquence directe : `pip install` n'y
fonctionne pas. Un composant avec des dépendances ne pourrait donc pas y être
réparé sans rouvrir la machine, c'est-à-dire précisément le jour où on en a le
plus besoin.

Une seule brique a réellement besoin du réseau (`voice/`), donc **une seule
fenêtre d'installation** — procédure au §4.5 du plan, avec sa vérification de
refermeture. Le reste s'installe, se répare et se diagnostique hors ligne, pour
toujours.

## État

| Composant | État | Preuve |
|---|---|---|
| `router/` — résidence des modèles | **fait** | 3 bascules successives → 1 instance, sans suffixe |
| `bridge/` — Anthropic ↔ OpenAI | **fait** | 60/60, dont tool calling live en streaming *et* non-streaming |
| `brain/` — second cerveau | non commencé | bloqué en amont : vault, nom du sas, port 22 |
| `voice/` — chat VR vocal | non commencé | demande la fenêtre d'installation |

## router — un profil à la fois

```bash
python3 router/profiles.py status
python3 router/profiles.py switch code
python3 router/profiles.py serve        # HTTP sur 127.0.0.1:8080
```

Les clés de modèle dans `router/profiles.json` sont des **placeholders**.
Relevez les vraies avec `lms ls --json` avant la première bascule.

**Ce que le routeur achète.** `lms load` ne reprend pas une instance déjà
résidente : il en empile une seconde, la seconde prend le suffixe `…:2`, et
c'est la *première* qui garde le TTL. Une heure plus tard le TTL tombe,
l'instance au nom propre disparaît, et `model.default` ne correspond plus à
rien — sans que rien n'ait été touché (`LIAISON_HERMES_MAC.md` §4.5).

La procédure documentée décharge d'abord puis vérifie `lms ps`. Le routeur fait
ça, plus une chose que la procédure ne fait pas : il passe un `--identifier`
explicite. L'identifiant cesse d'être ce que le catalogue a bien voulu produire
et devient un nom **choisi**, par profil. Un `model.default: code` survit donc à
un re-téléchargement, une re-quantisation ou un renommage en amont.

La détection est gardée quand même : forcer l'identifiant rend la collision
bruyante au lieu de l'empêcher — si quelque chose tient déjà le nom, LM Studio
renvoie `code:2` et la bascule **échoue**, au lieu de réussir puis de pourrir
une heure plus tard.

**Couplage avec Hermes.** Hermes porte un `model.default` figé. Basculer sous
ses pieds lui renvoie `model not found`, pas une erreur réseau — c'est la
première chose à regarder quand il tombe sans raison. Le garde-fou lit
`~/.mac-ia/hermes.hold` ; **rien ne crée encore ce fichier**, c'est le point
d'accroche pour quand `hermes.cmd` sera mis à jour. D'ici là le garde est inerte
par construction, pas par accident.

**Sécurité.** `:1234` ne transporte que des tokens, d'où l'absence
d'authentification. `:8080` est différent : il charge des modèles arbitraires.
D'où le bind sur `127.0.0.1` par défaut, à atteindre par SSH quand le plan de
contrôle sera posé. Le serveur avertit sur stderr s'il est bindé ailleurs.

## bridge — un endpoint Anthropic devant un runtime OpenAI

```bash
python3 bridge/server.py                       # 0.0.0.0:1235 -> 127.0.0.1:1234/v1
python3 tests/test_bridge.py                   # blocs 1-4, aucun modèle requis
python3 tests/test_bridge.py --live            # + bloc 5, pile complète
```

Puis, côté client :

```bash
ANTHROPIC_BASE_URL=http://192.168.1.50:1235
```

**Le problème.** LM Studio parle OpenAI (`/v1/chat/completions`). Le Claude
Agent SDK et le harnais Claude Code parlent Anthropic (`/v1/messages`). Deux
dialectes de la même idée ; il manquait le traducteur.

**Là où passe le travail.** Le non-streaming est une transformation de
dictionnaires. Le streaming, non : OpenAI émet des **deltas plats** sans début
ni fin, Anthropic exige des **blocs encadrés** — chaque contenu ouvert par
`content_block_start`, fermé par `content_block_stop`, avec le bon index. Le
pont doit donc *inventer* un cadrage qu'OpenAI n'envoie jamais. Un client qui
reçoit un delta pour un bloc dont on ne lui a pas annoncé l'ouverture perd le
contenu ou casse. C'est `StreamTranslator`, et c'est là qu'il faut des tests.

**Ce qu'il ne fait pas, exprès.** Pas d'authentification : il est sur le même
LAN de confiance que `:1234` et hérite de cette posture au lieu d'en inventer
une autre. Et il n'invente pas de capacités — `thinking`, `cache_control` et
`output_config` sont **jetés**, pas émulés. Un appelant qui en dépend les voit
manquer, plutôt que de recevoir une imitation crédible.

### Ce que les tests prouvent, et où ils disent de s'arrêter

Blocs 1–4 : traduction pure, aucun modèle, aucun réseau. Bloc 5 : la pile
entière, **sauté** et non échoué si elle n'est pas debout.

C'est là tout l'intérêt du découpage. Un échec en 1–4 est un bug **ici**. Un
échec en 5 avec 1–4 au vert est un bug dans l'**environnement** — runtime,
modèle, Context Length, KV quantisation — et il n'y a aucune raison de relire la
traduction.

## Diagnostic

| Symptôme | Couche | La commande qui tranche |
|---|---|---|
| Hermes : `model not found`, sans rien avoir touché | profil basculé sous ses pieds | `python3 router/profiles.py status` |
| `model not found` une heure après le démarrage | double instance `…:2` (§4.5) | `lms ps --json` |
| Le pont renvoie du texte au lieu d'un `tool_use` | traduction, ou modèle sans tool calling | `tests/test_bridge.py` bloc 4, puis `--live` |
| Le client attend indéfiniment en streaming | message jamais fermé | vérifier que `message_stop` est émis |
| `pip install` échoue sur le Mac | c'est normal — machine hors ligne | `route -n get default` |
