"""
D-Ticket — Fixtures de test.

La fixture `cluster` démarre un vrai système complet en sous-processus :
  - 1 registry ;
  - 3 nœuds (NODE_1, NODE_2, NODE_3) avec un dossier d'état temporaire ;
  - 1 backend web.

Les ports sont choisis dynamiquement pour ne jamais entrer en conflit
avec une instance de démonstration qui tournerait déjà.
"""

import os
import socket
import subprocess
import sys
import time

import pytest
import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STARTUP_TIMEOUT_SECONDS = 15


def _free_port() -> int:
    """Demande au système d'exploitation un port libre."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_until_healthy(url: str, name: str) -> None:
    """Attend qu'un service réponde sur /health, sinon échoue."""
    deadline = time.time() + STARTUP_TIMEOUT_SECONDS
    while time.time() < deadline:
        try:
            if requests.get(f"{url}/health", timeout=1).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"{name} n'a pas démarré à temps ({url})")


class Cluster:
    """Poignée sur le cluster de test : URLs des services."""

    def __init__(self, registry_url, node_urls, web_url):
        self.registry_url = registry_url
        self.node_urls = node_urls  # {"NODE_1": "http://...", ...}
        self.web_url = web_url

    def node_state(self, node_id: str) -> dict:
        response = requests.get(f"{self.node_urls[node_id]}/state", timeout=3)
        response.raise_for_status()
        return response.json()

    def take_ticket_on(self, node_id: str, client: str = "Client test") -> dict:
        response = requests.post(
            f"{self.node_urls[node_id]}/ticket", json={"client": client}, timeout=5
        )
        response.raise_for_status()
        return response.json()


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    """Démarre un cluster complet, le fournit au test, puis l'arrête."""
    state_dir = str(tmp_path_factory.mktemp("state"))
    registry_port = _free_port()
    web_port = _free_port()
    node_ports = {"NODE_1": _free_port(), "NODE_2": _free_port(), "NODE_3": _free_port()}
    registry_url = f"http://127.0.0.1:{registry_port}"

    processes = []

    def _spawn(args):
        process = subprocess.Popen(
            [sys.executable] + args,
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        processes.append(process)
        return process

    try:
        # 1. Registry
        _spawn(["registry/registry.py", "--port", str(registry_port)])
        _wait_until_healthy(registry_url, "registry")

        # 2. Nœuds
        for node_id, port in node_ports.items():
            _spawn(
                [
                    "node/node_server.py",
                    "--node-id", node_id,
                    "--port", str(port),
                    "--registry", registry_url,
                    "--state-dir", state_dir,
                ]
            )
        node_urls = {}
        for node_id, port in node_ports.items():
            node_urls[node_id] = f"http://127.0.0.1:{port}"
            _wait_until_healthy(node_urls[node_id], node_id)

        # 3. Backend web (pas de /health : on attend la page d'accueil)
        _spawn(["web/app.py", "--port", str(web_port), "--registry", registry_url])
        web_url = f"http://127.0.0.1:{web_port}"
        deadline = time.time() + STARTUP_TIMEOUT_SECONDS
        while time.time() < deadline:
            try:
                if requests.get(web_url, timeout=1).status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError("Le backend web n'a pas démarré à temps.")

        yield Cluster(registry_url, node_urls, web_url)

    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
