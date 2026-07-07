"""
Tests de tolérance aux pannes (failover).

Quand un nœud tombe, le système doit continuer à délivrer des tickets
via les nœuds restants, sans doublon et sans erreur pour le client.
"""

import requests


def test_failed_node_reports_unavailable(cluster):
    """Un nœud en panne simulée répond 503 sur /health et /ticket."""
    requests.post(f"{cluster.node_urls['NODE_1']}/shutdown-simulated", timeout=3)
    try:
        assert requests.get(
            f"{cluster.node_urls['NODE_1']}/health", timeout=3
        ).status_code == 503
        assert requests.post(
            f"{cluster.node_urls['NODE_1']}/ticket", json={}, timeout=3
        ).status_code == 503
    finally:
        requests.post(f"{cluster.node_urls['NODE_1']}/restart-simulated", timeout=5)


def test_tickets_continue_when_one_node_is_down(cluster):
    """NODE_1 en panne : le backend web bascule sur NODE_2 ou NODE_3."""
    requests.post(f"{cluster.node_urls['NODE_1']}/shutdown-simulated", timeout=3)
    try:
        response = requests.post(
            f"{cluster.web_url}/api/ticket", json={"client": "Client failover"}, timeout=10
        )
        assert response.status_code == 201
        data = response.json()
        assert data["served_by"] in ("NODE_2", "NODE_3")
        assert data["ticket"]["ticket_number"] >= 1
    finally:
        requests.post(f"{cluster.node_urls['NODE_1']}/restart-simulated", timeout=5)


def test_cluster_view_shows_failed_node_as_inactive(cluster):
    """L'API cluster du backend web voit le nœud en panne comme inactif."""
    requests.post(f"{cluster.node_urls['NODE_2']}/shutdown-simulated", timeout=3)
    try:
        response = requests.get(f"{cluster.web_url}/api/cluster", timeout=10)
        nodes = {n["node_id"]: n for n in response.json()["nodes"]}
        assert nodes["NODE_2"]["status"] == "inactive"
        assert nodes["NODE_1"]["status"] == "active"
        assert nodes["NODE_3"]["status"] == "active"
    finally:
        requests.post(f"{cluster.node_urls['NODE_2']}/restart-simulated", timeout=5)
