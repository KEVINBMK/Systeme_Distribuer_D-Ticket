"""
D-Ticket — Backend de l'interface web.

Rôle :
  - servir l'interface (HTML/CSS/JS) ;
  - interroger le registry pour découvrir les nœuds ;
  - vérifier la santé de chaque nœud en direct ;
  - choisir automatiquement un nœud ACTIF pour chaque demande de ticket
    (c'est ici que se joue la tolérance aux pannes côté client) ;
  - relayer les simulations de panne / redémarrage vers les nœuds.

Ce composant ne stocke aucun état : il ne fait que router.

Lancement :
    python web/app.py
"""

import argparse
import itertools
import logging

import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

REGISTRY_URL = "http://127.0.0.1:5000"
REQUEST_TIMEOUT_SECONDS = 3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WEB] %(levelname)s %(message)s",
)
logger = logging.getLogger("web")


# ----------------------------------------------------------------------
# Découverte et santé des nœuds
# ----------------------------------------------------------------------


def _registered_nodes() -> list:
    """Récupère la liste des nœuds connus du registry."""
    try:
        response = requests.get(f"{REGISTRY_URL}/nodes", timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json().get("nodes", [])
    except requests.RequestException:
        logger.warning("Registry injoignable.")
        return []


def _probe_node(node: dict) -> dict:
    """
    Vérifie la santé d'un nœud en direct (GET /health) et enrichit
    l'entrée du registry avec sa version et son dernier ticket.
    """
    info = {
        "node_id": node["node_id"],
        "url": node["url"],
        "status": "inactive",
        "version": None,
        "last_ticket": None,
    }
    try:
        response = requests.get(f"{node['url']}/health", timeout=REQUEST_TIMEOUT_SECONDS)
        if response.status_code == 200:
            health = response.json()
            info["status"] = "active"
            info["version"] = health.get("version")
            info["last_ticket"] = health.get("last_ticket")
    except requests.RequestException:
        pass
    return info


def _cluster_view() -> list:
    """Vue complète du cluster : statut + version de chaque nœud."""
    nodes = [_probe_node(n) for n in _registered_nodes()]

    # Un nœud actif est "synchronisé" s'il a la version maximale,
    # sinon il est "en retard" (lagging).
    active_versions = [n["version"] for n in nodes if n["status"] == "active"]
    max_version = max(active_versions) if active_versions else None
    for node in nodes:
        if node["status"] == "active":
            node["sync"] = "synchronized" if node["version"] == max_version else "lagging"
        else:
            node["sync"] = None
    return nodes


def _pick_active_node(nodes: list) -> dict | None:
    """
    Choisit le nœud qui traitera la prochaine demande.
    Stratégie simple : le premier nœud actif ayant la version la plus
    élevée (le plus à jour). Si un nœud tombe, le suivant prend le relais.
    """
    active = [n for n in nodes if n["status"] == "active"]
    if not active:
        return None
    return max(active, key=lambda n: (n["version"] or 0))


# ----------------------------------------------------------------------
# Pages et API
# ----------------------------------------------------------------------


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/cluster", methods=["GET"])
def api_cluster():
    """État distribué : statut, version et dernier ticket de chaque nœud."""
    return jsonify({"nodes": _cluster_view()})


@app.route("/api/tickets", methods=["GET"])
def api_tickets():
    """
    Liste des tickets et journal d'événements, lus depuis le nœud actif
    le plus à jour.
    """
    nodes = _cluster_view()
    node = _pick_active_node(nodes)
    if node is None:
        return jsonify({"error": "Aucun nœud actif"}), 503

    try:
        response = requests.get(f"{node['url']}/state", timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        state = response.json()
    except requests.RequestException:
        return jsonify({"error": f"{node['node_id']} injoignable"}), 503

    return jsonify(
        {
            "source": node["node_id"],
            "last_ticket": state.get("last_ticket", 0),
            "version": state.get("version", 0),
            "tickets": state.get("tickets", []),
            "event_log": state.get("event_log", []),
        }
    )


# Compteur pour la répartition round-robin des demandes de tickets.
_round_robin_counter = itertools.count()


def _ticket_candidates(nodes: list) -> list:
    """
    Ordonne les nœuds candidats pour la prochaine demande de ticket :
      1. les nœuds actifs SYNCHRONISÉS (version maximale), en round-robin
         pour répartir la charge équitablement entre eux ;
      2. puis les nœuds actifs en retard, en dernier recours (failover),
         car créer un ticket sur un nœud en retard risquerait un doublon.
    """
    active = [n for n in nodes if n["status"] == "active"]
    if not active:
        return []

    max_version = max(n["version"] or 0 for n in active)
    up_to_date = [n for n in active if (n["version"] or 0) == max_version]
    lagging = sorted(
        (n for n in active if (n["version"] or 0) < max_version),
        key=lambda n: (n["version"] or 0),
        reverse=True,
    )

    # Rotation : chaque demande commence par le nœud suivant de la liste.
    offset = next(_round_robin_counter) % len(up_to_date)
    return up_to_date[offset:] + up_to_date[:offset] + lagging


@app.route("/api/ticket", methods=["POST"])
def api_take_ticket():
    """
    Prend un ticket : choisit un nœud actif (répartition round-robin entre
    les nœuds synchronisés) et lui transmet la demande. Si le nœud choisi
    échoue au dernier moment, on essaie les suivants (failover automatique).
    """
    payload = request.get_json(silent=True) or {}
    client = payload.get("client") or "Client anonyme"

    candidates = _ticket_candidates(_cluster_view())
    if not candidates:
        return jsonify({"error": "Aucun nœud actif : impossible de créer un ticket"}), 503

    for node in candidates:
        try:
            response = requests.post(
                f"{node['url']}/ticket",
                json={"client": client},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if response.status_code == 201:
                logger.info("Ticket créé via %s", node["node_id"])
                return jsonify(response.json()), 201
        except requests.RequestException:
            logger.warning("Échec sur %s, tentative du nœud suivant...", node["node_id"])

    return jsonify({"error": "Tous les nœuds actifs ont échoué"}), 503


@app.route("/api/nodes/<node_id>/fail", methods=["POST"])
def api_fail_node(node_id):
    """Relaye la simulation de panne vers le nœud ciblé."""
    return _forward_to_node(node_id, "shutdown-simulated")


@app.route("/api/nodes/<node_id>/restart", methods=["POST"])
def api_restart_node(node_id):
    """Relaye le redémarrage simulé (avec récupération) vers le nœud ciblé."""
    return _forward_to_node(node_id, "restart-simulated")


def _forward_to_node(node_id: str, action: str):
    """Trouve l'URL du nœud dans le registry et lui envoie l'action."""
    node = next(
        (n for n in _registered_nodes() if n["node_id"] == node_id), None
    )
    if node is None:
        return jsonify({"error": f"Nœud inconnu : {node_id}"}), 404

    try:
        response = requests.post(
            f"{node['url']}/{action}", timeout=REQUEST_TIMEOUT_SECONDS
        )
        return jsonify(response.json()), response.status_code
    except requests.RequestException:
        return jsonify({"error": f"{node_id} injoignable"}), 503


def main():
    global REGISTRY_URL

    parser = argparse.ArgumentParser(description="D-Ticket — interface web")
    parser.add_argument("--port", type=int, default=8000, help="Port HTTP de l'interface")
    parser.add_argument(
        "--registry",
        default="http://127.0.0.1:5000",
        help="URL du registry",
    )
    args = parser.parse_args()
    REGISTRY_URL = args.registry.rstrip("/")

    logger.info("Interface web démarrée : http://127.0.0.1:%s", args.port)
    app.run(host="0.0.0.0", port=args.port, threaded=True)


if __name__ == "__main__":
    main()
