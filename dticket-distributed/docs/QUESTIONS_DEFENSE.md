# Questions / Réponses pour la défense — D-Ticket

## Pourquoi ce projet est-il un système distribué ?

Parce qu'il est composé de **plusieurs agents autonomes** (trois nœuds serveurs,
chacun dans son propre processus, avec sa propre mémoire et sa propre
persistance) qui **coopèrent uniquement par échange de messages** (HTTP) pour
maintenir un **état global cohérent** : le compteur de tickets. Aucune mémoire
n'est partagée entre les nœuds, et le système continue de fonctionner quand un
composant tombe — deux caractéristiques définitoires des systèmes distribués.

## Quel est le rôle d'un nœud ?

Un nœud est un serveur autonome qui :

1. gère sa **copie locale** de l'état (compteur, tickets, version, journal),
   persistée dans un fichier JSON ;
2. **crée des tickets** de façon atomique (verrou local) ;
3. **réplique** son état vers les autres nœuds après chaque création ;
4. **accepte** les états plus récents venant des pairs ;
5. **se resynchronise** tout seul après une panne.

## Quel est le rôle du registry ?

C'est un **annuaire de découverte** : les nœuds s'y enregistrent (avec un
heartbeat toutes les 5 secondes) et tout composant peut lui demander la liste
des nœuds et leur statut. Il ne stocke **aucun état métier** (ni tickets, ni
compteur) : s'il tombe, les tickets continuent d'être délivrés.

## Où se trouve l'état partagé ?

**Sur chaque nœud**, sous forme d'une copie locale répliquée
(`node/state/nodeX_state.json`). Il n'y a pas de base centrale : l'état global
est l'union des copies, et le mécanisme de versionnement fait converger toutes
les copies vers la plus récente. C'est un état **distribué et répliqué**.

## Que se passe-t-il si un nœud tombe ?

1. Il cesse de répondre (503) et son heartbeat s'arrête ;
2. l'interface le marque « Inactif » ;
3. le backend web **route automatiquement** les nouvelles demandes vers un
   autre nœud actif (failover) ;
4. les tickets continuent d'être générés, sans doublon, car les nœuds restants
   possèdent déjà l'état répliqué le plus récent.

## Comment le système évite-t-il les doublons ?

À deux niveaux :

- **dans un nœud** : un `threading.Lock` rend la séquence « lire le compteur →
  incrémenter → sauvegarder » atomique ; deux requêtes simultanées obtiennent
  forcément deux numéros différents ;
- **entre nœuds** : chaque ticket est répliqué immédiatement avec un numéro de
  version ; le nœud qui prend le relais après une panne part donc du bon
  compteur. De plus, le backend web n'envoie chaque demande qu'à **un seul**
  nœud à la fois.

## Comment se fait la récupération ?

Au redémarrage (réel ou simulé), le nœud :

1. se ré-enregistre auprès du registry ;
2. demande son état complet à chaque pair actif (`GET /state`) ;
3. compare les versions et choisit **l'état de version maximale** ;
4. si cette version est supérieure à la sienne, il l'adopte, le **persiste**
   dans son fichier JSON et journalise l'opération.

Il rattrape ainsi tous les tickets créés pendant son absence.

## Pourquoi utilise-t-on une version ?

La version est une **horloge logique simple** : elle permet d'ordonner les
états sans horloge physique synchronisée. Elle sert à :

- décider si un état reçu est plus récent que l'état local (règle : on
  n'accepte que si la version est strictement supérieure) ;
- rendre la réplication **idempotente** (recevoir deux fois le même état est
  sans effet) ;
- choisir le bon état lors de la récupération ;
- afficher dans l'interface quels nœuds sont synchronisés ou en retard.

## Quelles sont les limites du système ?

- **Pas d'algorithme de consensus** (Raft/Paxos) : en cas de partition réseau
  avec des écritures simultanées sur des nœuds isolés, des doublons seraient
  possibles ;
- la réplication transfère **l'état complet** au lieu de deltas ;
- le registry est un **point de défaillance unique** pour la découverte (mais
  pas pour le service métier) ;
- la cohérence est **à terme** : un nœud peut être brièvement en retard entre
  deux réplications.

## Comment améliorer le projet ?

- Ajouter une **élection de leader** pour sérialiser globalement les écritures ;
- passer à une réplication **incrémentale** (journal d'opérations) ;
- exiger un **quorum d'accusés de réception** avant de confirmer un ticket ;
- répliquer le registry ou utiliser une découverte pair-à-pair (gossip) ;
- sécuriser les échanges (authentification entre nœuds, HTTPS).
