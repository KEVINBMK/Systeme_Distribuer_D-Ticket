"""
D-Ticket — Registry (annuaire de nœuds).

Le registry est le SEUL composant centralisé du système.
Son unique rôle est la découverte des nœuds :
  - enregistrer les nœuds actifs (avec heartbeat) ;
  - lister les nœuds disponibles ;
  - marquer un nœud comme inactif si son heartbeat est trop ancien.

Il ne stocke AUCUN état métier (aucun ticket, aucun compteur).
"""

import argparse
import json
import logging
import os
import threading
import time

from flask import Flask, jsonify, request

# Un nœud est considéré inactif si aucun heartbeat depuis ce délai (secondes).
HEARTBEAT_TIMEOUT_SECONDS = 15

NODES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nodes.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [REGISTRY] %(levelname)s %(message)s",
)
logger = logging.getLogger("registry")

app = Flask(__name__)

# Verrou pour protéger l'accès concurrent au fichier nodes.json.
_lock = threading.Lock()


def _load_nodes() -> dict:
    """Charge le fichier nodes.json (retourne un dict vide si absent/corrompu)."""
    if not os.path.exists(NODES_FILE):
        return {}
    try:
        with open(NODES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.warning("nodes.json illisible, on repart d'une liste vide.")
        return {}


def _save_nodes(nodes: dict) -> None:
    """Sauvegarde la liste des nœuds dans nodes.json."""
    with open(NODES_FILE, "w", encoding="utf-8") as f:
        json.dump(nodes, f, indent=2, ensure_ascii=False)


def _node_status(node: dict) -> str:
    """Détermine le statut d'un nœud à partir de son dernier heartbeat."""
    age = time.time() - node.get("last_heartbeat", 0)
    return "active" if age <= HEARTBEAT_TIMEOUT_SECONDS else "inactive"


@app.route("/health", methods=["GET"])
def health():
    """Le registry lui-même est-il en vie ?"""
    return jsonify({"status": "ok", "service": "registry"})


@app.route("/register", methods=["POST"])
def register():
    """Enregistre (ou ré-enregistre) un nœud. Sert aussi de heartbeat."""
    payload = request.get_json(silent=True) or {}
    node_id = payload.get("node_id")
    host = payload.get("host", "127.0.0.1")
    port = payload.get("port")

    if not node_id or not port:
        return jsonify({"error": "node_id et port sont obligatoires"}), 400

    with _lock:
        nodes = _load_nodes()
        is_new = node_id not in nodes
        nodes[node_id] = {
            "node_id": node_id,
            "host": host,
            "port": int(port),
            "url": f"http://{host}:{port}",
            "last_heartbeat": time.time(),
        }
        _save_nodes(nodes)

    if is_new:
        logger.info("Nouveau nœud enregistré : %s (http://%s:%s)", node_id, host, port)
    return jsonify({"status": "registered", "node_id": node_id})


@app.route("/unregister", methods=["POST"])
def unregister():
    """Retire explicitement un nœud de l'annuaire."""
    payload = request.get_json(silent=True) or {}
    node_id = payload.get("node_id")
    if not node_id:
        return jsonify({"error": "node_id est obligatoire"}), 400

    with _lock:
        nodes = _load_nodes()
        removed = nodes.pop(node_id, None)
        _save_nodes(nodes)

    if removed:
        logger.info("Nœud retiré : %s", node_id)
    return jsonify({"status": "unregistered", "node_id": node_id})


@app.route("/nodes", methods=["GET"])
def list_nodes():
    """Liste tous les nœuds connus avec leur statut (active / inactive)."""
    with _lock:
        nodes = _load_nodes()

    result = []
    for node in nodes.values():
        result.append(
            {
                "node_id": node["node_id"],
                "url": node["url"],
                "host": node["host"],
                "port": node["port"],
                "status": _node_status(node),
            }
        )
    # Tri stable par identifiant pour un affichage prévisible.
    result.sort(key=lambda n: n["node_id"])
    return jsonify({"nodes": result})


def main():
    parser = argparse.ArgumentParser(description="D-Ticket Registry")
    parser.add_argument("--port", type=int, default=5000, help="Port HTTP du registry")
    args = parser.parse_args()

    # On repart d'un annuaire vide à chaque démarrage : les nœuds vivants
    # se ré-enregistrent d'eux-mêmes via leur heartbeat périodique.
    with _lock:
        _save_nodes({})

    logger.info("Registry démarré sur le port %s", args.port)
    app.run(host="0.0.0.0", port=args.port, threaded=True)


if __name__ == "__main__":
    main()
