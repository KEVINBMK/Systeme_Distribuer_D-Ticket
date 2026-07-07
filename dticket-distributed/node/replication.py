"""
D-Ticket — Réplication de l'état entre nœuds.

Après chaque nouveau ticket, le nœud qui a traité la demande pousse son
état complet vers tous les autres nœuds actifs (réplication "push",
meilleure-effort). Un nœud injoignable est simplement ignoré : il se
resynchronisera lui-même à son redémarrage (voir recovery.py).
"""

import logging

import requests

logger = logging.getLogger("replication")

# Délai court : un nœud en panne ne doit pas bloquer la réponse au client.
REPLICATION_TIMEOUT_SECONDS = 2


def get_peers(registry_url: str, own_node_id: str) -> list:
    """
    Interroge le registry pour obtenir la liste des AUTRES nœuds actifs.
    Retourne une liste de dicts : [{"node_id": ..., "url": ...}, ...].
    """
    try:
        response = requests.get(f"{registry_url}/nodes", timeout=REPLICATION_TIMEOUT_SECONDS)
        response.raise_for_status()
        nodes = response.json().get("nodes", [])
    except requests.RequestException as exc:
        logger.warning("Registry injoignable (%s) : réplication impossible.", exc)
        return []

    return [
        {"node_id": n["node_id"], "url": n["url"]}
        for n in nodes
        if n["node_id"] != own_node_id and n.get("status") == "active"
    ]


def replicate_to_peers(state_snapshot: dict, peers: list) -> dict:
    """
    Envoie l'état local à chaque pair via POST /replicate.
    Retourne un résumé {node_id: "accepted" | "rejected" | "unreachable"}.
    """
    results = {}
    for peer in peers:
        try:
            response = requests.post(
                f"{peer['url']}/replicate",
                json=state_snapshot,
                timeout=REPLICATION_TIMEOUT_SECONDS,
            )
            if response.status_code == 200 and response.json().get("accepted"):
                results[peer["node_id"]] = "accepted"
            else:
                results[peer["node_id"]] = "rejected"
        except requests.RequestException:
            # Nœud en panne : on continue, il récupérera à son retour.
            results[peer["node_id"]] = "unreachable"
            logger.warning(
                "Réplication vers %s impossible (nœud injoignable).",
                peer["node_id"],
            )
    logger.info("Résultat de la réplication : %s", results)
    return results
