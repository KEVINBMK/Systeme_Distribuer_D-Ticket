# Guide de démonstration — D-Ticket

Déroulé pas à pas pour une défense d'environ 10 minutes.

## Préparation (avant la défense)

```bash
cd dticket-distributed
pip install -r requirements.txt
```

Pour repartir d'un état vierge, remettre les fichiers
`node/state/node*_state.json` à leur contenu initial
(`last_ticket: 0`, `version: 0`, listes vides).

## Étape 1 — Lancer le registry

```bat
scripts\start_registry.bat
```

> « Le registry est notre annuaire : il sait quels nœuds existent,
> mais il ne stocke aucun ticket. »

## Étape 2, 3, 4 — Lancer les trois nœuds

Dans trois terminaux séparés :

```bat
scripts\start_node1.bat
scripts\start_node2.bat
scripts\start_node3.bat
```

Montrer dans les logs que chaque nœud **s'enregistre** auprès du registry
et envoie un heartbeat.

## Étape 5 — Lancer l'interface web

```bat
scripts\start_web.bat
```

Ouvrir **http://127.0.0.1:8000**. Montrer :

- les 3 nœuds « Actif » et « Synchronisé » ;
- le bloc **État distribué** : version 0 partout ;
- le badge « Cluster complet ».

## Étape 6 — Prendre le Ticket 1

Saisir un nom de client (ex. « Alice ») et cliquer sur **Prendre un ticket**.

- Le ticket **N° 1** apparaît dans le tableau, avec le nœud qui l'a créé.
- Le journal d'événements montre la création puis la réplication.

## Étape 7 — Montrer la réplication

Dans le bloc **État distribué** : les trois nœuds affichent la **même version**
et le **même dernier ticket**. On peut aussi le prouver en ligne de commande :

```bash
curl http://127.0.0.1:5001/state
curl http://127.0.0.1:5002/state
curl http://127.0.0.1:5003/state
```

> « Le nœud qui a créé le ticket a poussé son état vers les deux autres. »

## Étape 8 — Simuler la panne de NODE_1

Cliquer sur **Simuler panne** sur la carte de NODE_1.

- NODE_1 passe en « Inactif » (badge rouge) ;
- le bandeau passe en « Mode dégradé — service maintenu ».

## Étape 9 — Prendre le Ticket 2 pendant la panne

Cliquer à nouveau sur **Prendre un ticket**.

## Étape 10 — Montrer que le système continue

- Le ticket **N° 2** est délivré par **NODE_2 ou NODE_3** (visible dans la
  colonne « Créé par » et dans la notification).
- Aucune erreur pour l'utilisateur : c'est le **failover automatique**.
- Dans le bloc État distribué, NODE_1 est « Hors ligne », les autres avancent.

## Étape 11 — Redémarrer NODE_1

Cliquer sur **Redémarrer** sur la carte de NODE_1.

## Étape 12 — Montrer la récupération

- NODE_1 repasse « Actif » et surtout **« Synchronisé »** : sa version a
  rejoint celle des autres **sans avoir vu passer le Ticket 2**.
- Le journal d'événements montre : `Récupération réussie depuis NODE_x
  (version 1 -> 2)`.

## Étape 13 — Expliquer réplication et récupération

Conclure avec les deux mécanismes clés :

1. **Réplication** : après chaque ticket, le nœud émetteur pousse son état
   complet vers les pairs actifs ; un pair n'accepte que si la version reçue
   est **plus récente** que la sienne.
2. **Récupération** : au retour d'une panne, le nœud interroge tous les pairs,
   choisit l'état de **version maximale**, l'adopte et le persiste en JSON.

Bonus si le temps le permet : lancer `pytest tests/ -v` pour montrer que ces
scénarios sont vérifiés automatiquement.
