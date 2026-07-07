"""
D-Ticket — Serveur d'un nœud distribué.

Chaque nœud est un agent autonome qui :
  - gère son propre état local persisté en JSON (distributed_state.py) ;
  - crée des tickets de façon atomique (verrou local) ;
  - réplique son état vers les autres nœuds actifs (replication.py) ;
  - se resynchronise après une panne (recovery.py) ;
  - s'annonce périodiquement auprès du registry (heartbeat).

Lancement :
    python node/node_server.py --node-id NODE_1 --port 5001
"""

import argparse
import logging
import os
import threading
import time

import requests
from flask import Flask, jsonify, request

from distributed_state import DistributedState
from recovery import recover_from_peers
from replication import get_peers, replicate_to_peers

HEARTBEAT_INTERVAL_SECONDS = 5

app = Flask(__name__)

# Ces variables globales sont initialisées dans main().
NODE_ID = None
NODE_PORT = None
REGISTRY_URL = None
state: DistributedState = None

# Panne simulée : quand ce drapeau est levé, le nœud refuse toutes les
# requêtes métier (comme s'il était éteint), mais son processus reste
# vivant pour pouvoir être "redémarré" depuis l'interface.
_simulated_down = threading.Event()

logger = logging.getLogger("node")


def _is_down() -> bool:
    return _simulated_down.is_set()


def _unavailable_response():
    """Réponse standard quand le nœud est en panne simulée."""
    return jsonify({"error": f"{NODE_ID} est en panne (simulée)"}), 503


# ----------------------------------------------------------------------
# Heartbeat vers le registry
# ----------------------------------------------------------------------


def _register_with_registry() -> bool:
    """S'enregistre (ou renouvelle le heartbeat) auprès du registry."""
    try:
        requests.post(
            f"{REGISTRY_URL}/register",
            json={"node_id": NODE_ID, "host": "127.0.0.1", "port": NODE_PORT},
            timeout=2,
        )
        return True
    except requests.RequestException:
        logger.warning("[%s] Registry injoignable pour le heartbeat.", NODE_ID)
        return False


def _heartbeat_loop():
    """Envoie un heartbeat périodique tant que le nœud n'est pas en panne."""
    while True:
        if not _is_down():
            _register_with_registry()
        time.sleep(HEARTBEAT_INTERVAL_SECONDS)


# ----------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------


@app.route("/health", methods=["GET"])
def health():
    """Le nœud est-il disponible ?"""
    if _is_down():
        return _unavailable_response()
    return jsonify(
        {
            "node_id": NODE_ID,
            "status": "active",
            "version": state.version,
            "last_ticket": state.last_ticket,
        }
    )


@app.route("/state", methods=["GET"])
def get_state():
    """Retourne l'état local complet du nœud."""
    if _is_down():
        return _unavailable_response()
    return jsonify(state.snapshot())


@app.route("/ticket", methods=["POST"])
def create_ticket():
    """
    Crée un nouveau ticket :
      1. incrémente last_ticket et version sous verrou local ;
      2. persiste l'état dans le fichier JSON ;
      3. réplique le nouvel état vers les autres nœuds actifs ;
      4. retourne le ticket au client.
    """
    if _is_down():
        return _unavailable_response()

    payload = request.get_json(silent=True) or {}
    client = payload.get("client", "Client anonyme")

    ticket = state.create_ticket(client)

    # Réplication meilleure-effort : un pair en panne n'empêche pas
    # la création du ticket (il se resynchronisera à son retour).
    peers = get_peers(REGISTRY_URL, NODE_ID)
    replication_results = replicate_to_peers(state.snapshot(), peers)

    return jsonify(
        {
            "ticket": ticket,
            "served_by": NODE_ID,
            "version": state.version,
            "replication": replication_results,
        }
    ), 201


@app.route("/replicate", methods=["POST"])
def replicate():
    """
    Reçoit l'état d'un autre nœud.
    L'état n'est accepté que si sa version est plus récente que la nôtre.
    """
    if _is_down():
        return _unavailable_response()

    remote_state = request.get_json(silent=True)
    if not remote_state:
        return jsonify({"error": "état manquant"}), 400

    accepted = state.apply_remote_state(remote_state)
    return jsonify({"accepted": accepted, "version": state.version})


@app.route("/recover", methods=["POST"])
def recover():
    """Force le nœud à récupérer l'état le plus récent chez ses pairs."""
    if _is_down():
        return _unavailable_response()

    peers = get_peers(REGISTRY_URL, NODE_ID)
    result = recover_from_peers(state, peers)
    return jsonify(result)


@app.route("/shutdown-simulated", methods=["POST"])
def shutdown_simulated():
    """
    Simule une panne logique : le nœud reste en vie mais refuse tout.
    Il cesse aussi d'envoyer son heartbeat au registry.
    """
    _simulated_down.set()
    state.log_event("PANNE SIMULÉE : le nœud ne répond plus.")
    logger.warning("[%s] Panne simulée activée.", NODE_ID)
    return jsonify({"node_id": NODE_ID, "status": "down"})


@app.route("/restart-simulated", methods=["POST"])
def restart_simulated():
    """
    Simule le redémarrage du nœud :
      1. le nœud redevient disponible ;
      2. il se ré-enregistre auprès du registry ;
      3. il lance immédiatement la procédure de récupération.
    """
    _simulated_down.clear()
    state.log_event("REDÉMARRAGE SIMULÉ : le nœud est de retour.")
    logger.info("[%s] Redémarrage simulé, récupération en cours...", NODE_ID)

    _register_with_registry()
    peers = get_peers(REGISTRY_URL, NODE_ID)
    recovery_result = recover_from_peers(state, peers)

    return jsonify(
        {"node_id": NODE_ID, "status": "active", "recovery": recovery_result}
    )


# ----------------------------------------------------------------------
# Démarrage
# ----------------------------------------------------------------------


def main():
    global NODE_ID, NODE_PORT, REGISTRY_URL, state

    parser = argparse.ArgumentParser(description="D-Ticket — nœud distribué")
    parser.add_argument("--node-id", required=True, help="Identifiant du nœud (ex: NODE_1)")
    parser.add_argument("--port", type=int, required=True, help="Port HTTP du nœud")
    parser.add_argument(
        "--registry",
        default="http://127.0.0.1:5000",
        help="URL du registry (défaut : http://127.0.0.1:5000)",
    )
    parser.add_argument(
        "--state-dir",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "state"),
        help="Dossier des fichiers d'état JSON",
    )
    args = parser.parse_args()

    NODE_ID = args.node_id
    NODE_PORT = args.port
    REGISTRY_URL = args.registry.rstrip("/")

    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s [{NODE_ID}] %(levelname)s %(message)s",
    )

    # 1. Charger (ou créer) l'état local persistant.
    state = DistributedState(NODE_ID, args.state_dir)
    state.log_event(f"Nœud démarré sur le port {NODE_PORT} (version {state.version}).")

    # 2. S'annoncer au registry, puis rattraper l'état le plus récent :
    #    un vrai redémarrage après crash passe par ce même chemin.
    _register_with_registry()
    peers = get_peers(REGISTRY_URL, NODE_ID)
    if peers:
        recover_from_peers(state, peers)

    # 3. Heartbeat périodique en tâche de fond.
    threading.Thread(target=_heartbeat_loop, daemon=True).start()

    logger.info("[%s] Nœud prêt sur le port %s.", NODE_ID, NODE_PORT)
    app.run(host="0.0.0.0", port=NODE_PORT, threaded=True)


if __name__ == "__main__":
    main()
