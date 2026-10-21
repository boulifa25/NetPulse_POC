# NetPulse POC : surveillance de bornes WiFi

Un parc de **10 fausses bornes WiFi** (dans Docker) réparties sur 3 sites, un **gardien**
Python qui les interroge en SNMP toutes les 30 secondes, un **cahier** PostgreSQL
où chaque mesure et chaque alerte est enregistrée, et une **API** qui les met à disposition.

```
[10 fausses bornes]  <--SNMP--  [Gardien Python]  --écrit-->  [PostgreSQL]  <--lit--  [API FastAPI]  <-- navigateur, page web…
 ports 1161 à 1170              toutes les 30 s,               port 5433               port 8000
                                règles d'alerte
```

## Avancement (feuille de route en 11 étapes)

| # | Étape | État |
|---|---|---|
| 1 | Une fausse borne | ✅ |
| 2 | Un parc multi-sites (10 bornes, hôtel / résidence / magasin) | ✅ |
| 3 | Le gardien automatique (toutes les 30 s) | ✅ |
| 4 | Le cahier (PostgreSQL) | ✅ |
| 5 | Les premières alertes (panne, surcharge) | ✅ |
| 6 | Le gardien malin (IA) | ✅ |
| 7 | Comprendre une grosse panne (1 alerte par site) | ✅ |
| 8 | L'API FastAPI | ✅ |
| 9 | L'écran de contrôle | ✅ |
| 10 | Les notifications (email / Slack) | à faire |
| 11 | La vitrine | à faire |

## Contenu du dossier

| Fichier | Rôle |
|---|---|
| `simulator/Dockerfile` | Fabrique la fausse borne (un mini Linux avec un agent SNMP) |
| `simulator/snmpd.conf` | Modèle : identité de la borne et ce qu'elle accepte de répondre |
| `simulator/entrypoint.sh` | Donne son nom, son emplacement et son profil à la borne au démarrage |
| `simulator/clients_wifi.sh` | Invente le nombre d'appareils connectés selon l'heure et le type de site |
| `simulator/surcharge.sh` | Étape 5 : commande `surcharge N` pour simuler une foule sur une borne |
| `simulator/forcer_clients.sh` | Étape 6 : commande `forcer-clients N` pour rendre une borne « bizarre » |
| `simulator/bornes.env` | Réglages communs des bornes (fuseau horaire) |
| `docker-compose.yml` | Lance les 10 bornes et la base PostgreSQL |
| `database/schema.sql` | Étapes 4 et 5 : les tables du cahier (sites, bornes, mesures, alertes) |
| `collector/interroger_borne.py` | Étape 1 : interroge une borne et affiche ses réponses |
| `collector/bornes.py` | Étape 2 : inventaire des sites et des 10 bornes |
| `collector/interroger_bornes.py` | Étape 2 : interroge les 10 bornes en parallèle, bilan par site |
| `collector/gardien.py` | Étapes 3 et 4 : surveille les bornes toutes les 30 s, signale les changements, enregistre les mesures |
| `collector/cahier.py` | Étape 4 : écriture des mesures dans PostgreSQL |
| `collector/historique.py` | Étape 4 : relit l'historique des bornes |
| `collector/regles.py` | Étapes 5 à 7 : toutes les règles d'alerte (panne, surcharge, anomalie, site hors service) et leurs seuils |
| `collector/alertes.py` | Étape 5 : affiche les alertes en cours et terminées |
| `collector/normes.py` | Étape 6 : apprend ce qui est normal pour chaque borne et repère ce qui sort de l'ordinaire |
| `collector/generer_historique.py` | Étape 6 : fabrique un historique simulé pour l'apprentissage |
| `collector/api.py` | Étapes 8 et 9 : l'API FastAPI (sites, bornes, mesures, normes, alertes) ; sert aussi l'écran de contrôle |
| `collector/ecran.html` | Étape 9 : l'écran de contrôle, servi par l'API sur http://127.0.0.1:8000/ |

## Prérequis (une seule fois)

1. **Docker Desktop** lancé (l'icône de la baleine doit être verte).
   Vérifie dans un terminal : `docker --version`
2. **Python 3.10 ou plus** : `python --version`

Ouvre un terminal dans le dossier `netpulse-poc`, puis :

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r collector\requirements.txt
```

## Étape 1 : une fausse borne

```powershell
docker compose up -d --build borne-hotel-01   # construit et démarre une seule borne
docker compose ps                             # STATUS doit être "Up"
python collector\interroger_borne.py
```

Résultat attendu (les chiffres changent) :

```
Réponse de la borne :
  - Nom de la borne : borne-hotel-01
  - Emplacement : Hotel Paris - Accueil
  - Allumée depuis (1/100 s) : 4210
  - Clients WiFi connectés : 14
```

Panne : `docker compose stop borne-hotel-01`, relance le script
(`La borne ne répond pas : No SNMP response received before timeout`), puis
`docker compose start borne-hotel-01`.

## Étape 2 : 10 bornes sur 3 sites

Toutes les bornes utilisent la **même image** ; chacune reçoit son nom, son emplacement et
son **profil** de fréquentation par variables d'environnement.

| Site | Type | Bornes | Ports | Fréquentation simulée |
|---|---|---|---|---|
| Hotel Paris | hôtel | borne-hotel-01 à 04 | 1161 à 1164 | calme la nuit, plein le soir |
| Residence Lyon | résidence | borne-residence-01 à 03 | 1165 à 1167 | vide en journée (travail), plein le soir |
| Magasin Marseille | magasin | borne-magasin-01 à 03 | 1168 à 1170 | quasi vide hors horaires (9 h-20 h), pic l'après-midi |

L'inventaire côté Python est dans `collector/bornes.py` : garde-le synchronisé avec
`docker-compose.yml`.

```powershell
docker compose up -d --build --remove-orphans
python collector\interroger_bornes.py
```

Résultat attendu (extrait) :

```
Residence Lyon : 3/3 bornes en ligne, 19 clients WiFi
  [OK]    borne-residence-01   Residence Lyon - Hall              8 clients
  ...
Bilan : 10/10 bornes en ligne.
```

## Étape 3 : le gardien automatique

`collector/gardien.py` interroge les 10 bornes toutes les 30 secondes et ne signale que
ce qui **change** :

| Événement | Quand |
|---|---|
| `[PANNE]` | une borne qui répondait ne répond plus |
| `[RETOUR]` | une borne en panne répond de nouveau (avec la durée de la coupure) |
| `[REDÉMARRAGE]` | la borne répond, mais son compteur « allumée depuis » est reparti de zéro : elle a redémarré entre deux tours sans qu'on la voie tomber |

Chaque tour affiche une ligne de résumé ; les événements sont aussi écrits dans
`collector/evenements.log`.

```powershell
python collector\gardien.py                  # Ctrl+C pour arrêter
python collector\gardien.py --intervalle 5   # tours de 5 s, pratique pour tester
```

Pour tester, laisse le gardien tourner et, dans un **deuxième** terminal :

```powershell
docker compose stop borne-residence-02      # -> [PANNE]
docker compose start borne-residence-02     # -> [RETOUR] ... (coupure : 10 s)
docker compose restart borne-magasin-01     # -> [REDÉMARRAGE]
```

## Étape 4 : le cahier (PostgreSQL)

À chaque tour, le gardien enregistre **une mesure par borne** dans PostgreSQL, y compris
quand la borne ne répond pas (pour garder la trace des coupures).

| Table | Contenu |
|---|---|
| `sites` | les 3 sites et leur type (hotel, residence, magasin) |
| `bornes` | les 10 bornes, leur site, leur port et leur emplacement |
| `mesures` | horodatage, en ligne oui/non, clients, allumée depuis (s), erreur |

La base tourne dans Docker (service `base`), sur le **port 5433** : le 5432 de ce PC est déjà
pris par un autre PostgreSQL. Les données sont dans le volume Docker `netpulse-donnees` et
survivent aux redémarrages. Le gardien crée les tables et l'inventaire tout seul au démarrage.

```powershell
docker compose up -d base                        # (déjà lancée par "docker compose up -d")
python collector\gardien.py                      # chaque tour affiche "enregistré"

python collector\historique.py                   # bilan de chaque borne
python collector\historique.py borne-residence-02        # ses 20 dernières mesures
python collector\historique.py borne-residence-02 -n 50
```

Exemple après une coupure de `borne-residence-02` :

```
2026-10-21 17:04:03  [OK]       5 clients   allumée depuis 2 s
2026-10-21 17:04:00  [PANNE]  No SNMP response received before timeout
2026-10-21 17:03:53  [PANNE]  No SNMP response received before timeout
2026-10-21 17:03:42  [OK]       6 clients   allumée depuis 153 s
```

Si la base tombe, le gardien **continue de surveiller** : il affiche
`[CAHIER] base injoignable`, puis `[CAHIER] base de nouveau joignable` dès qu'elle revient.
Les mesures prises pendant la coupure de la base sont perdues.

Pour explorer la base à la main :

```powershell
docker exec -it netpulse-base psql -U netpulse
```

Identifiants (démo locale uniquement) : `netpulse` / `netpulse`, base `netpulse`.
Pour une autre base : variable d'environnement `NETPULSE_DB`
(ex. `postgresql://user:motdepasse@hote:5432/base`).

## Étape 5 : les premières alertes

À chaque tour, le gardien applique les règles de `collector/regles.py` et **ouvre ou ferme
des alertes** dans la table `alertes` (même transaction que les mesures) :

| Règle | Gravité | S'ouvre quand… | Se ferme quand… |
|---|---|---|---|
| `panne` | critique | la borne ne répond pas | elle répond de nouveau |
| `surcharge` | avertissement | **35 clients ou plus** | elle repasse **sous 30 clients** |

L'écart entre 35 et 30 évite qu'une borne qui oscille autour du seuil ouvre et ferme une
alerte à chaque tour. En temps normal, une borne simulée monte au plus à 27 clients.

Une alerte est **en cours** tant que sa colonne `fin` est vide. Il ne peut y avoir qu'une
alerte en cours par borne et par type : si le gardien redémarre pendant une panne, il
retrouve l'alerte existante au lieu d'en créer une deuxième.

```powershell
python collector\gardien.py --intervalle 5      # dans un 1er terminal

# dans un 2e terminal :
docker compose stop borne-hotel-02              # -> [ALERTE] #1 panne (critique)
docker exec borne-magasin-01 surcharge 40       # -> [ALERTE] #2 surcharge (avertissement)
docker compose start borne-hotel-02             # -> [FIN ALERTE] #1 panne terminée après 36 s
docker exec borne-magasin-01 surcharge 0        # -> [FIN ALERTE] #2 surcharge terminée

python collector\alertes.py                     # alertes en cours + 20 dernières terminées
```

Exemple :

```
Alertes en cours : 0
  aucune

2 dernières alertes terminées
  #1    CRITIQUE  panne      2026-10-21 17:10:36  (        36 s)  borne-hotel-02 (Hotel Paris) ne répond plus
  #2    AVERTIS.  surcharge  2026-10-21 17:10:36  (        36 s)  borne-magasin-01 (Magasin Marseille) : 67 clients connectés (seuil : 35)
```

Pour changer un seuil : modifie `SEUIL_SURCHARGE` / `SEUIL_FIN_SURCHARGE` dans
`collector/regles.py`, puis relance le gardien.

## Étape 6 : le gardien malin

Les règles de l'étape 5 ne voient que les cas extrêmes (muette, plus de 35 clients). Le gardien
malin repère une borne **bizarre** : par exemple 2 clients à 17 h sur une borne d'hôtel qui en a
d'habitude 14. Aucune règle simple n'est dépassée, mais quelque chose ne va pas (borne mal
placée, antenne abîmée, WiFi qui décroche les clients…).

**Comment il apprend** (`collector/normes.py`) : pour chaque borne et **chaque heure de la
journée**, il retient le nombre de clients habituel (la médiane) et la variation habituelle
autour (l'écart médian). Il utilise les 14 derniers jours de mesures, au démarrage du gardien
puis toutes les heures. Médiane et écart médian ignorent les valeurs extrêmes : une surcharge de
test ne fausse pas ce qui est « normal ». Le résultat est rangé dans la table `normes`
(10 bornes × 24 heures = 240 créneaux).

**Quand il alerte** (règle `anomalie` dans `collector/regles.py`, gravité avertissement) :

| | Condition |
|---|---|
| Ouverture | **3 tours de suite**, la borne est à au moins **4 écarts habituels** ET **6 clients** de sa normale |
| Fermeture | la borne revient à moins de 2,5 écarts habituels ou de 4 clients de sa normale |
| Jamais | si la borne est en panne ou en surcharge (déjà expliqué par une règle simple) |

C'est de l'apprentissage statistique, pas un réseau de neurones : chaque alerte s'explique
(« 2 clients alors qu'il y en a d'habitude ~14 vers 17 h »).

**Historique pour apprendre** : on n'a pas des semaines de vraies mesures, donc
`generer_historique.py` crée 7 jours de mesures simulées (une toutes les 5 min, mêmes profils
que les fausses bornes). Elles sont marquées `simulee` : elles servent à apprendre, jamais à
juger l'état actuel d'une borne.

```powershell
python collector\generer_historique.py          # 7 jours simulés + apprentissage
python collector\normes.py borne-hotel-03        # ce qui est normal pour cette borne, heure par heure
python collector\gardien.py --intervalle 5       # dans un 1er terminal

# dans un 2e terminal :
docker exec borne-hotel-03 forcer-clients 2      # -> ~3 tours plus tard : [ALERTE] anomalie
docker exec borne-hotel-03 forcer-clients normal # -> [FIN ALERTE] anomalie
```

Exemple :

```
17:20:21  [IA]          normes apprises : 240 créneaux (borne x heure) sur les 14 derniers jours
17:21:01  [ALERTE]      #3 anomalie (avertissement) : borne-hotel-03 (Hotel Paris) : 2 clients alors qu'il y en a d'habitude ~14 vers 17 h
17:21:26  [FIN ALERTE]  #3 anomalie terminée après 25 s : borne-hotel-03 (Hotel Paris) : ...
```

Sur les 20 160 mesures simulées (comportement normal), le détecteur ne déclenche aucune fausse
alerte. Attention : ces mesures suivent exactement les profils appris ; de vraies bornes seront
plus irrégulières et les seuils devront sans doute être ajustés.

**Fuseau horaire** : les bornes vivent à l'heure locale (UTC+1, réglée dans
`simulator/bornes.env`), et les normes sont calculées dans le même fuseau
(`FUSEAU_HORAIRE` dans `collector/bornes.py`). Les deux doivent rester identiques.

## Étape 7 : comprendre une grosse panne

Quand **toutes les bornes d'un site** se taisent au même moment, ce n'est pas 4 bornes cassées :
c'est le site (courant, box Internet, switch). Le gardien crée alors **une seule** alerte
critique `site_hors_service` au lieu d'une alerte `panne` par borne.

| Situation | Alertes |
|---|---|
| Tout le site tombe d'un coup | 1 alerte `site_hors_service` |
| Une borne tombe, puis le reste du site peu après | l'alerte `panne` de la première est **regroupée** dans l'alerte du site (fermée, avec un lien `regroupee_dans`) : il reste 1 alerte en cours |
| Le site revient, sauf certaines bornes | l'alerte de site se ferme ; chaque borne encore muette reçoit son alerte `panne` (le problème est redevenu local) |

La règle ne s'applique qu'aux sites d'au moins 2 bornes. Une alerte vise maintenant soit une
borne (`borne_id`), soit un site (`site_id`), jamais les deux.

```powershell
python collector\gardien.py --intervalle 5      # dans un 1er terminal

# dans un 2e terminal : on coupe tout l'Hotel Paris
docker compose stop borne-hotel-01 borne-hotel-02 borne-hotel-03 borne-hotel-04
docker compose start borne-hotel-01 borne-hotel-02 borne-hotel-03 borne-hotel-04

python collector\alertes.py
```

Exemple :

```
17:25:01  [ALERTE]      #4 site_hors_service (critique) : Hotel Paris : les 4 bornes sont muettes en même temps (coupure de courant ou d'Internet sur le site ?)
17:25:19  [FIN ALERTE]  #4 site_hors_service terminée après 17 s : Hotel Paris : ...

17:25:33  [ALERTE]      #5 panne (critique) : borne-hotel-01 (Hotel Paris) ne répond plus
17:25:52  [ALERTE]      #6 site_hors_service (critique) : Hotel Paris : les 4 bornes sont muettes en même temps ...
17:25:52  [REGROUPÉE]   #5 panne rattachée à l'alerte de site #6 : borne-hotel-01 (Hotel Paris) ne répond plus
```

Les lignes `[PANNE]` / `[RETOUR]` du gardien restent affichées borne par borne : c'est le
journal brut de ce qu'il observe. Ce sont les **alertes** qui sont regroupées.

## Étape 8 : l'API

Jusqu'ici, pour voir les données, il fallait lancer un script Python dans un terminal. L'API
est un petit serveur web qui les **distribue** : on lui pose une question sous forme d'adresse,
elle répond en JSON. C'est elle que la page web de l'étape 9 interrogera, et elle permet à
n'importe quel autre outil d'accéder aux données sans connaître la base ni son mot de passe.

L'API ne fait que **lire** : c'est toujours le gardien qui interroge les bornes et écrit.

```powershell
pip install -r collector\requirements.txt   # une fois : ajoute FastAPI
python collector\api.py                     # Ctrl+C pour arrêter
```

Ouvre **http://127.0.0.1:8000/docs** : la documentation interactive liste toutes les routes ;
« Try it out » puis « Execute » pour en tester une.

| Route | Réponse |
|---|---|
| `GET /sante` | l'API, la base et le gardien fonctionnent-ils ? (gardien actif = une mesure il y a moins de 2 min) |
| `GET /sites` | les 3 sites et leur état : `operationnel`, `degrade`, `hors_service` |
| `GET /sites/{id}` | un site, ses bornes et ses alertes en cours |
| `GET /sites/{id}/historique` | clients du site au fil du temps, comparés au normal appris (`?heures=`, `?pas_minutes=`) : sert aux graphiques de l'étape 9 |
| `GET /bornes` | toutes les bornes et leur dernier état mesuré (`?site_id=` pour filtrer) |
| `GET /bornes/{nom}` | une borne (ex. `borne-hotel-03`) et ses alertes en cours |
| `GET /bornes/{nom}/mesures` | son historique (`?limite=`, `?depuis=`, `?inclure_simulees=true`) |
| `GET /bornes/{nom}/normes` | ce que le gardien malin a appris pour elle, heure par heure |
| `GET /alertes` | les alertes (`?en_cours=true`, `?type=`, `?gravite=`, `?site_id=`, `?borne=`, `?limite=`) |
| `GET /alertes/{id}` | une alerte |

Exemples à ouvrir dans le navigateur (le gardien doit tourner pour que les données soient fraîches) :

- http://127.0.0.1:8000/sites
- http://127.0.0.1:8000/alertes?en_cours=true
- http://127.0.0.1:8000/bornes/borne-hotel-03/mesures?limite=10

Réponse de `/sites/1` pendant une panne de `borne-hotel-02` (extrait) :

```json
{"id": 1, "nom": "Hotel Paris", "type": "hotel", "etat": "degrade",
 "nb_bornes": 4, "bornes_en_ligne": 3, "alertes_en_cours": 1, ...
 "alertes": [{"id": 10, "type": "panne", "gravite": "critique",
              "message": "borne-hotel-02 (Hotel Paris) ne répond plus", "en_cours": true, ...}]}
```

Les dates sont à l'heure locale des sites (ex. `2026-10-21T17:31:06+01:00`). Une borne ou une
alerte inconnue renvoie **404**, un paramètre invalide **422**. Si la base est arrêtée, l'API
renvoie **503** avec un message clair, puis repart toute seule quand la base revient.

## Étape 9 : l'écran de contrôle

Une page web qui montre l'état du réseau d'un coup d'œil. Elle est servie par l'API et lit
toutes ses données dans l'API (aucun accès direct à la base).

**Pour la voir, deux terminaux :**

```powershell
python collector\gardien.py      # terminal 1 : surveille les bornes et remplit la base
python collector\api.py          # terminal 2 : sert l'écran et l'API
```

Puis ouvre **http://127.0.0.1:8000/**.

| Zone | Contenu |
|---|---|
| En-tête | état du gardien : `● Gardien actif`, `▲ Gardien arrêté` ou `✕ Base injoignable`, avec un bandeau d'explication si quelque chose ne va pas |
| Chiffres clés | bornes en ligne (et lesquelles sont muettes), clients connectés, alertes en cours (critiques / avertissements), sites opérationnels |
| Alertes en cours | les critiques d'abord, avec leur type (Panne, Surcharge, Anomalie (IA), Site hors service) et depuis quand |
| Une carte par site | état du site, graphique des clients sur 6 h / 24 h / 3 jours comparé au **normal attendu** appris par l'IA (ligne pointillée), et chaque borne en vert ● ou rouge ✕, avec un badge si elle a une alerte |
| Dernières alertes terminées | leur durée, et le lien « regroupée dans #… » de l'étape 7 |

Survole un graphique pour lire les valeurs à une heure précise. Les parties grisées du
graphique sont l'historique **simulé** de l'étape 6 (pas de vraies mesures) ; un trou dans la
courbe veut dire que le gardien ne tournait pas. La page se met à jour toute seule (toutes les
5 s, les graphiques toutes les 30 s), en mode clair ou sombre selon Windows.

Pour une démo, provoque des alertes pendant que la page est ouverte :

```powershell
docker compose stop borne-hotel-02           # Panne : la borne passe au rouge, Hotel Paris "Dégradé"
docker exec borne-magasin-01 surcharge 40    # Surcharge
docker exec borne-hotel-03 forcer-clients 2  # Anomalie (IA), ~3 tours plus tard
docker compose stop borne-residence-01 borne-residence-02 borne-residence-03   # Site hors service
```

(Et pour tout remettre : `docker compose start`, `surcharge 0`, `forcer-clients normal`.)

## Si ça bloque

- `Activate.ps1 ne peut pas être chargé` : lance une fois
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, puis réessaie.
- `docker : commande introuvable` ou erreur de connexion : Docker Desktop n'est pas démarré.
- Une borne ne répond pas alors qu'elle est "Up" : `docker compose logs <nom-de-la-borne>`.
  (Le message `systemstats_linux: unexpected header length` est sans importance.)
- `Base injoignable` : `docker compose up -d base`, puis `docker compose ps` (doit être `healthy`).
