# D-Ticket — Système distribué de gestion de file d'attente

Projet universitaire pour un cours de **Systèmes Distribués**.

D-Ticket est une application distribuée simple où plusieurs utilisateurs prennent
des tickets de file d'attente. Le compteur de tickets est une **ressource partagée**,
**répliquée** sur trois nœuds serveurs autonomes, et **récupérable après panne**.

## Objectif pédagogique

Démontrer, avec des technologies volontairement simples, les notions fondamentales
d'un système distribué :

| Notion | Où elle est démontrée |
|---|---|
| Agents autonomes | 3 nœuds serveurs indépendants (processus séparés) |
| Ressource partagée | Le compteur `last_ticket` |
| État distribué | Chaque nœud possède sa copie locale de l'état (JSON) |
| Réplication | Chaque nouveau ticket est propagé aux autres nœuds |
| Synchronisation | Verrou local (`threading.Lock`) + versionnement de l'état |
| Tolérance aux pannes | Failover automatique vers un nœud actif |
| Récupération après crash | Un nœud qui revient rattrape la version la plus élevée |
| Journalisation | Journal d'événements par nœud, visible dans l'interface |

## Architecture

```
                        ┌──────────────┐
                        │   Registry   │  ← découverte des nœuds UNIQUEMENT
                        │  (port 5000) │    (aucun état métier)
                        └──────┬───────┘
                 heartbeat ▲   │   ▲ heartbeat
              ┌────────────┘   │   └────────────┐
              │                │                │
        ┌─────┴─────┐    ┌─────┴─────┐    ┌─────┴─────┐
        │  NODE_1   │◄──►│  NODE_2   │◄──►│  NODE_3   │
        │ port 5001 │    │ port 5002 │    │ port 5003 │
        └─────┬─────┘    └─────┬─────┘    └─────┬─────┘
              │   réplication d'état (POST /replicate)
              ▼                ▼                ▼
        node1_state.json  node2_state.json  node3_state.json
                               ▲
                        ┌──────┴───────┐
                        │  Interface   │  ← choisit automatiquement
                        │ web (8000)   │    un nœud ACTIF
                        └──────────────┘
```

- **Registry** (`registry/`) : seul composant centralisé. Il enregistre les nœuds
  (heartbeat toutes les 5 s) et les liste. Il ne stocke **aucun ticket**.
- **Nœuds** (`node/`) : agents autonomes. Chacun a son fichier d'état JSON, son
  compteur `last_ticket`, sa `version` et son journal. Ils se répliquent entre eux.
- **Interface web** (`web/`) : tableau de bord + backend qui route chaque demande
  vers un nœud actif (tolérance aux pannes côté client).

## Technologies

- Python 3 (≥ 3.10)
- Flask (serveurs HTTP)
- Requests (communication HTTP entre nœuds)
- JSON (persistance locale)
- HTML / CSS / JavaScript (interface)
- pytest (tests système)

Aucun framework distribué externe (pas de Zookeeper, Kafka, Redis, etc.).

## Installation

```bash
cd dticket-distributed
python -m venv venv
venv\Scripts\activate        # Windows  (Linux/macOS : source venv/bin/activate)
pip install -r requirements.txt
```

## Lancement (5 terminaux)

### Windows — via les scripts

```bat
scripts\start_registry.bat
scripts\start_node1.bat
scripts\start_node2.bat
scripts\start_node3.bat
scripts\start_web.bat
```

### Commandes exactes (toutes plateformes)

Depuis le dossier `dticket-distributed/` :

```bash
python registry/registry.py                                # port 5000
python node/node_server.py --node-id NODE_1 --port 5001
python node/node_server.py --node-id NODE_2 --port 5002
python node/node_server.py --node-id NODE_3 --port 5003
python web/app.py                                          # port 8000
```

Puis ouvrir **http://127.0.0.1:8000** dans un navigateur.

## Scénario de démonstration (résumé)

Voir [`docs/GUIDE_DEMO.md`](docs/GUIDE_DEMO.md) pour le déroulé détaillé.

1. Lancer les 5 services et ouvrir l'interface.
2. Prendre un ticket → il apparaît, et les 3 nœuds affichent la **même version**.
3. Cliquer sur « Simuler panne NODE_1 » → NODE_1 passe en « Inactif ».
4. Prendre un autre ticket → il est servi par NODE_2 ou NODE_3 (failover).
5. Cliquer sur « Redémarrer NODE_1 » → il **récupère** l'état le plus récent.
6. Vérifier que les 3 versions sont de nouveau identiques.

## Endpoints

### Registry (port 5000)

| Méthode | Endpoint | Rôle |
|---|---|---|
| GET | `/health` | Le registry est-il vivant ? |
| POST | `/register` | Enregistre un nœud (sert aussi de heartbeat) |
| POST | `/unregister` | Retire un nœud de l'annuaire |
| GET | `/nodes` | Liste les nœuds avec leur statut (active/inactive) |

### Nœuds (ports 5001–5003)

| Méthode | Endpoint | Rôle |
|---|---|---|
| GET | `/health` | Statut, version et dernier ticket du nœud |
| GET | `/state` | État local complet (tickets, journal…) |
| POST | `/ticket` | Crée un ticket puis réplique l'état aux pairs |
| POST | `/replicate` | Reçoit un état ; accepté seulement si version plus récente |
| POST | `/recover` | Récupère l'état le plus récent auprès des pairs |
| POST | `/shutdown-simulated` | Simule une panne logique (le nœud répond 503) |
| POST | `/restart-simulated` | Simule le retour du nœud + récupération automatique |

### Interface web (port 8000)

| Méthode | Endpoint | Rôle |
|---|---|---|
| GET | `/` | Tableau de bord |
| GET | `/api/cluster` | Statut + version de chaque nœud |
| GET | `/api/tickets` | Tickets et journal (lus depuis le nœud le plus à jour) |
| POST | `/api/ticket` | Prend un ticket via un nœud actif (failover intégré) |
| POST | `/api/nodes/<id>/fail` | Simule la panne du nœud |
| POST | `/api/nodes/<id>/restart` | Redémarre le nœud (avec récupération) |

## Notions distribuées utilisées

- **Découverte de services** : registry central minimal + heartbeat périodique.
- **Réplication "push" meilleure-effort** : le nœud qui crée un ticket pousse son
  état complet vers les pairs ; un pair injoignable ne bloque pas l'opération.
- **Versionnement (horloge logique simple)** : chaque mutation incrémente `version` ;
  un nœud n'accepte un état distant que si sa version est **strictement supérieure**.
- **Exclusion mutuelle locale** : `threading.Lock` garantit qu'un même nœud ne
  délivre jamais deux fois le même numéro, même sous requêtes concurrentes.
- **Failover** : le backend web sonde la santé des nœuds et route vers le nœud
  actif le plus à jour ; si l'appel échoue, il essaie le nœud suivant.
- **Récupération après crash** : au (re)démarrage, un nœud interroge ses pairs,
  adopte l'état de version maximale et le persiste.

## Tests

```bash
cd dticket-distributed
pytest tests/ -v
```

Les tests démarrent un **vrai cluster** (registry + 3 nœuds + web) en
sous-processus sur des ports libres, puis vérifient : la génération de tickets,
l'unicité des numéros (y compris en concurrence), la réplication, le failover
et la récupération après panne.

## Documentation

- [`docs/RAPPORT_PROJET.md`](docs/RAPPORT_PROJET.md) — rapport complet du projet.
- [`docs/GUIDE_DEMO.md`](docs/GUIDE_DEMO.md) — scénario de démonstration pas à pas.
- [`docs/QUESTIONS_DEFENSE.md`](docs/QUESTIONS_DEFENSE.md) — questions/réponses pour la défense.

## Limites connues (assumées pour un projet pédagogique)

- Réplication de l'état **complet** (pas de deltas) : simple mais non optimal.
- Pas de consensus (Raft/Paxos) : en cas de partition réseau, deux nœuds isolés
  pourraient émettre le même numéro. Acceptable ici car un seul nœud traite les
  demandes à la fois via le backend web.
- Le registry est un point de défaillance unique — mais il ne porte aucun état
  métier : s'il tombe, les nœuds continuent de servir les tickets.
