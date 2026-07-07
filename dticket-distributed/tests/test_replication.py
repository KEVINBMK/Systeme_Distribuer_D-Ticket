"""
Tests de réplication.

Après la création d'un ticket sur un nœud, l'état (compteur, version,
liste des tickets) doit être identique sur tous les autres nœuds actifs.
"""

import time


def _wait_for_version(cluster, node_id, expected_version, timeout=5):
    """Attend que le nœud atteigne la version attendue (réplication asynchrone)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cluster.node_state(node_id)["version"] >= expected_version:
            return True
        time.sleep(0.2)
    return False


def test_state_is_replicated_to_all_peers(cluster):
    """Un ticket créé sur NODE_1 apparaît sur NODE_2 et NODE_3."""
    result = cluster.take_ticket_on("NODE_1", client="Client répliqué")
    version = result["version"]

    for peer in ("NODE_2", "NODE_3"):
        assert _wait_for_version(cluster, peer, version), (
            f"{peer} n'a pas reçu la version {version}"
        )
        state = cluster.node_state(peer)
        assert state["last_ticket"] == result["ticket"]["ticket_number"]
        clients = [t["client"] for t in state["tickets"]]
        assert "Client répliqué" in clients


def test_all_nodes_converge_to_same_version(cluster):
    """Après plusieurs tickets sur des nœuds différents, tout le monde converge."""
    cluster.take_ticket_on("NODE_1")
    _wait_for_version(cluster, "NODE_2", cluster.node_state("NODE_1")["version"])
    cluster.take_ticket_on("NODE_2")
    _wait_for_version(cluster, "NODE_3", cluster.node_state("NODE_2")["version"])
    result = cluster.take_ticket_on("NODE_3")

    final_version = result["version"]
    for node_id in ("NODE_1", "NODE_2", "NODE_3"):
        assert _wait_for_version(cluster, node_id, final_version)

    versions = {n: cluster.node_state(n)["version"] for n in cluster.node_urls}
    assert len(set(versions.values())) == 1, f"Versions divergentes : {versions}"


def test_older_state_is_rejected(cluster):
    """Un nœud refuse un état dont la version est plus ancienne que la sienne."""
    import requests

    current = cluster.node_state("NODE_1")
    stale_state = dict(current, version=0, last_ticket=0, tickets=[])

    response = requests.post(
        f"{cluster.node_urls['NODE_1']}/replicate", json=stale_state, timeout=3
    )
    assert response.status_code == 200
    assert response.json()["accepted"] is False
    # L'état local n'a pas été écrasé.
    assert cluster.node_state("NODE_1")["version"] == current["version"]
