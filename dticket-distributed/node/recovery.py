"""
D-Ticket — Récupération d'un nœud après une panne.

Quand un nœud redémarre (ou reçoit POST /recover) :
  1. il demande leur état à tous les autres nœuds actifs (GET /state) ;
  2. il choisit l'état dont la version est la plus élevée ;
  3. si cette version est plus récente que la sienne, il l'adopte
     et la persiste dans son fichier JSON.

Le nœud rattrape ainsi tous les tickets créés pendant son absence.
"""

import logging

import requests

logger = logging.getLogger("recovery")

RECOVERY_TIMEOUT_SECONDS = 2


def fetch_best_peer_state(peers: list) -> dict | None:
    """
    Récupère l'état de chaque pair et retourne celui avec la version
    la plus élevée, ou None si aucun pair n'est joignable.
    """
    best_state = None
    for peer in peers:
        try:
            response = requests.get(
                f"{peer['url']}/state", timeout=RECOVERY_TIMEOUT_SECONDS
            )
            response.raise_for_status()
            state = response.json()
        except (requests.RequestException, ValueError):
            logger.warning("Récupération : %s injoignable, on l'ignore.", peer["node_id"])
            continue

        if best_state is None or state.get("version", -1) > best_state.get("version", -1):
            best_state = state

    if best_state is not None:
        logger.info(
            "Meilleur état trouvé : %s (version=%s)",
            best_state.get("node_id"),
            best_state.get("version"),
        )
    else:
        logger.info("Aucun pair joignable : le nœud garde son état local.")
    return best_state


def recover_from_peers(state, peers: list) -> dict:
    """
    Exécute la procédure complète de récupération sur `state`
    (instance de DistributedState).
    Retourne un résumé de l'opération pour l'API et le journal.
    """
    local_version_before = state.version
    best_state = fetch_best_peer_state(peers)

    if best_state is None:
        state.log_event("Récupération : aucun pair joignable, état local conservé.")
        return {
            "recovered": False,
            "reason": "aucun pair joignable",
            "version": state.version,
        }

    accepted = state.apply_remote_state(best_state)
    if accepted:
        state.log_event(
            f"Récupération réussie depuis {best_state.get('node_id')} "
            f"(version {local_version_before} -> {state.version})"
        )
    else:
        state.log_event(
            "Récupération : l'état local était déjà à jour "
            f"(version {state.version})."
        )

    return {
        "recovered": accepted,
        "source": best_state.get("node_id"),
        "version": state.version,
    }
