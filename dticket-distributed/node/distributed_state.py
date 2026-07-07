"""
D-Ticket — Gestion de l'état distribué d'un nœud.

Chaque nœud possède son propre état local, persisté dans un fichier JSON :
  - last_ticket : dernier numéro de ticket attribué (ressource partagée) ;
  - version     : numéro de version de l'état (horloge logique simple) ;
  - tickets     : liste des tickets connus du nœud ;
  - event_log   : journal des événements locaux.

Un verrou (threading.Lock) protège toutes les mutations : deux requêtes
simultanées sur le MÊME nœud ne peuvent jamais produire le même numéro.
"""

import json
import logging
import os
import threading
from datetime import datetime

logger = logging.getLogger("distributed_state")

# Taille maximale du journal d'événements conservé dans l'état.
MAX_EVENT_LOG_SIZE = 100


def _now() -> str:
    """Horodatage lisible, utilisé dans les tickets et le journal."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class DistributedState:
    """État local d'un nœud, persistant et protégé par un verrou."""

    def __init__(self, node_id: str, state_dir: str):
        self.node_id = node_id
        # NODE_1 -> node1_state.json (conforme à la structure du projet).
        filename = node_id.replace("_", "").lower() + "_state.json"
        self.state_file = os.path.join(state_dir, filename)
        self.lock = threading.Lock()
        os.makedirs(state_dir, exist_ok=True)
        self._state = self._load_or_create()

    # ------------------------------------------------------------------
    # Persistance locale (JSON)
    # ------------------------------------------------------------------

    def _default_state(self) -> dict:
        return {
            "node_id": self.node_id,
            "last_ticket": 0,
            "version": 0,
            "tickets": [],
            "event_log": [],
        }

    def _load_or_create(self) -> dict:
        """Charge l'état depuis le disque, ou crée un état vierge."""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    state = json.load(f)
                logger.info(
                    "[%s] État rechargé depuis le disque (version=%s)",
                    self.node_id,
                    state.get("version"),
                )
                return state
            except (json.JSONDecodeError, OSError):
                logger.warning(
                    "[%s] Fichier d'état corrompu, création d'un état vierge.",
                    self.node_id,
                )
        return self._default_state()

    def _save(self) -> None:
        """Écrit l'état sur disque (appelé sous verrou uniquement)."""
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Journalisation
    # ------------------------------------------------------------------

    def _append_event(self, message: str) -> None:
        """Ajoute un événement au journal (appelé sous verrou uniquement)."""
        self._state["event_log"].append({"timestamp": _now(), "message": message})
        # On borne la taille du journal pour garder un fichier léger.
        self._state["event_log"] = self._state["event_log"][-MAX_EVENT_LOG_SIZE:]

    def log_event(self, message: str) -> None:
        """Journalise un événement et persiste l'état."""
        with self.lock:
            self._append_event(message)
            self._save()
        logger.info("[%s] %s", self.node_id, message)

    # ------------------------------------------------------------------
    # Opérations métier
    # ------------------------------------------------------------------

    def create_ticket(self, client: str) -> dict:
        """
        Crée un nouveau ticket de façon atomique :
        incrémente last_ticket, incrémente version, persiste sur disque.
        Le verrou garantit que deux requêtes simultanées sur ce nœud
        reçoivent des numéros différents.
        """
        with self.lock:
            self._state["last_ticket"] += 1
            self._state["version"] += 1
            ticket = {
                "ticket_number": self._state["last_ticket"],
                "client": client,
                "created_by": self.node_id,
                "timestamp": _now(),
            }
            self._state["tickets"].append(ticket)
            self._append_event(
                f"Ticket {ticket['ticket_number']} créé pour "
                f"'{client}' (version {self._state['version']})"
            )
            self._save()
        logger.info(
            "[%s] Ticket %s créé (version=%s)",
            self.node_id,
            ticket["ticket_number"],
            self._state["version"],
        )
        return ticket

    def apply_remote_state(self, remote_state: dict) -> bool:
        """
        Applique un état reçu d'un autre nœud (réplication ou récupération).
        Règle de cohérence : on n'accepte que si la version distante est
        STRICTEMENT plus récente que la version locale.
        Retourne True si l'état a été accepté.
        """
        remote_version = remote_state.get("version", -1)
        source = remote_state.get("node_id", "?")
        with self.lock:
            local_version = self._state["version"]
            if remote_version <= local_version:
                logger.info(
                    "[%s] État de %s refusé (version distante %s <= locale %s)",
                    self.node_id,
                    source,
                    remote_version,
                    local_version,
                )
                return False

            self._state["last_ticket"] = remote_state.get("last_ticket", 0)
            self._state["version"] = remote_version
            self._state["tickets"] = remote_state.get("tickets", [])
            self._append_event(
                f"État répliqué depuis {source} "
                f"(version {local_version} -> {remote_version})"
            )
            self._save()
        logger.info(
            "[%s] État accepté depuis %s (nouvelle version=%s)",
            self.node_id,
            source,
            remote_version,
        )
        return True

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        """Retourne une copie de l'état local (sûre à sérialiser)."""
        with self.lock:
            return json.loads(json.dumps(self._state))

    @property
    def version(self) -> int:
        with self.lock:
            return self._state["version"]

    @property
    def last_ticket(self) -> int:
        with self.lock:
            return self._state["last_ticket"]
