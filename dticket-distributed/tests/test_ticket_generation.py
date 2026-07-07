"""
Tests de génération de tickets.

Vérifie la règle fondamentale du système :
deux clients ne reçoivent JAMAIS le même numéro de ticket.
"""

from concurrent.futures import ThreadPoolExecutor

import requests


def test_first_ticket_is_number_one(cluster):
    """Le tout premier ticket du système porte le numéro 1."""
    result = cluster.take_ticket_on("NODE_1", client="Alice")
    assert result["ticket"]["ticket_number"] == 1
    assert result["ticket"]["client"] == "Alice"
    assert result["served_by"] == "NODE_1"


def test_two_successive_tickets_have_different_numbers(cluster):
    """Deux tickets successifs ont deux numéros différents et croissants."""
    first = cluster.take_ticket_on("NODE_1", client="Bob")
    second = cluster.take_ticket_on("NODE_1", client="Carol")
    n1 = first["ticket"]["ticket_number"]
    n2 = second["ticket"]["ticket_number"]
    assert n1 != n2
    assert n2 == n1 + 1


def test_concurrent_requests_get_unique_numbers(cluster):
    """
    Dix demandes simultanées sur le même nœud : le verrou local
    (threading.Lock) doit garantir dix numéros distincts.
    """
    def take(i):
        return cluster.take_ticket_on("NODE_2", client=f"Client {i}")

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(take, range(10)))

    numbers = [r["ticket"]["ticket_number"] for r in results]
    assert len(numbers) == len(set(numbers)), "Des numéros de ticket sont dupliqués !"


def test_ticket_via_web_backend(cluster):
    """Le backend web choisit un nœud actif et retourne un ticket valide."""
    response = requests.post(
        f"{cluster.web_url}/api/ticket", json={"client": "Client web"}, timeout=5
    )
    assert response.status_code == 201
    data = response.json()
    assert data["ticket"]["ticket_number"] >= 1
    assert data["served_by"] in ("NODE_1", "NODE_2", "NODE_3")
