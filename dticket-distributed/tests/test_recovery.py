"""
Tests de récupération après panne.

Un nœud qui revient après une panne doit rattraper l'état le plus
récent (version la plus élevée) auprès des autres nœuds, sans perdre
aucun ticket créé pendant son absence.
"""

import requests


def test_node_recovers_latest_state_after_restart(cluster):
    """
    Scénario complet :
      1. NODE_1 tombe ;
      2. deux tickets sont créés sur NODE_2 pendant la panne ;
      3. NODE_1 redémarre et doit récupérer exactement cet état.
    """
    requests.post(f"{cluster.node_urls['NODE_1']}/shutdown-simulated", timeout=3)

    cluster.take_ticket_on("NODE_2", client="Pendant panne 1")
    result = cluster.take_ticket_on("NODE_2", client="Pendant panne 2")
    expected_version = result["version"]
    expected_last_ticket = result["ticket"]["ticket_number"]

    # Redémarrage simulé : déclenche automatiquement la récupération.
    response = requests.post(
        f"{cluster.node_urls['NODE_1']}/restart-simulated", timeout=10
    )
    assert response.status_code == 200
    recovery = response.json()["recovery"]
    assert recovery["recovered"] is True
    assert recovery["version"] == expected_version

    # L'état local de NODE_1 est bien à jour.
    state = cluster.node_state("NODE_1")
    assert state["version"] == expected_version
    assert state["last_ticket"] == expected_last_ticket
    clients = [t["client"] for t in state["tickets"]]
    assert "Pendant panne 1" in clients
    assert "Pendant panne 2" in clients


def test_recover_endpoint_is_idempotent_when_up_to_date(cluster):
    """POST /recover sur un nœud déjà à jour ne change rien."""
    version_before = cluster.node_state("NODE_3")["version"]
    response = requests.post(f"{cluster.node_urls['NODE_3']}/recover", timeout=10)
    assert response.status_code == 200
    assert response.json()["recovered"] is False
    assert cluster.node_state("NODE_3")["version"] == version_before


def test_no_duplicate_ticket_numbers_after_recovery(cluster):
    """Après une panne + récupération, aucun numéro de ticket n'est dupliqué."""
    requests.post(f"{cluster.node_urls['NODE_2']}/shutdown-simulated", timeout=3)
    cluster.take_ticket_on("NODE_1", client="Avant retour")
    requests.post(f"{cluster.node_urls['NODE_2']}/restart-simulated", timeout=10)

    # NODE_2 vient de récupérer : un nouveau ticket créé chez lui doit
    # continuer la séquence, pas la dupliquer.
    result = cluster.take_ticket_on("NODE_2", client="Après retour")
    state = cluster.node_state("NODE_2")
    numbers = [t["ticket_number"] for t in state["tickets"]]
    assert len(numbers) == len(set(numbers)), f"Doublons détectés : {numbers}"
    assert result["ticket"]["ticket_number"] == max(numbers)
