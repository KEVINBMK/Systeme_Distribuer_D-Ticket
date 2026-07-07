/**
 * D-Ticket — Logique de l'interface web.
 *
 * L'interface interroge périodiquement le backend web qui, lui,
 * agrège l'état du registry et des nœuds. Toute la tolérance aux
 * pannes (choix d'un nœud actif) est gérée côté serveur web.
 */

const REFRESH_INTERVAL_MS = 2000;

// ---------------------------------------------------------------
// Utilitaires
// ---------------------------------------------------------------

function $(id) {
  return document.getElementById(id);
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = String(text ?? "");
  return div.innerHTML;
}

let notificationTimer = null;

function notify(message, type) {
  const box = $("notification");
  box.textContent = message;
  box.className = `notification ${type}`;
  clearTimeout(notificationTimer);
  notificationTimer = setTimeout(() => box.classList.add("hidden"), 5000);
}

// ---------------------------------------------------------------
// Rafraîchissement du cluster (nœuds + état distribué)
// ---------------------------------------------------------------

async function refreshCluster() {
  let nodes = [];
  try {
    const response = await fetch("/api/cluster");
    nodes = (await response.json()).nodes || [];
  } catch {
    $("global-status").textContent = "Backend web injoignable";
    $("global-status").className = "badge badge-inactive";
    return;
  }

  const activeCount = nodes.filter((n) => n.status === "active").length;
  $("stat-active-nodes").textContent = `${activeCount} / ${nodes.length}`;

  const globalStatus = $("global-status");
  if (nodes.length === 0) {
    globalStatus.textContent = "Aucun nœud enregistré";
    globalStatus.className = "badge badge-neutral";
  } else if (activeCount === nodes.length) {
    globalStatus.textContent = "Cluster complet";
    globalStatus.className = "badge badge-active";
  } else if (activeCount > 0) {
    globalStatus.textContent = "Mode dégradé — service maintenu";
    globalStatus.className = "badge badge-lag";
  } else {
    globalStatus.textContent = "Cluster hors service";
    globalStatus.className = "badge badge-inactive";
  }

  renderNodeCards(nodes);
  renderVersionsTable(nodes);
  $("btn-take-ticket").disabled = activeCount === 0;
}

function renderNodeCards(nodes) {
  const list = $("nodes-list");
  if (nodes.length === 0) {
    list.innerHTML = '<p class="empty">Aucun nœud enregistré auprès du registry.</p>';
    return;
  }

  list.innerHTML = nodes
    .map((node) => {
      const isActive = node.status === "active";
      const statusBadge = isActive
        ? '<span class="badge badge-active">Actif</span>'
        : '<span class="badge badge-inactive">Inactif</span>';
      const syncBadge =
        node.sync === "synchronized"
          ? '<span class="badge badge-sync">Synchronisé</span>'
          : node.sync === "lagging"
            ? '<span class="badge badge-lag">En retard</span>'
            : "";
      const actionButton = isActive
        ? `<button class="btn btn-small btn-danger" onclick="failNode('${node.node_id}')">Simuler panne</button>`
        : `<button class="btn btn-small btn-success" onclick="restartNode('${node.node_id}')">Redémarrer</button>`;

      return `
        <div class="node-card ${isActive ? "" : "node-down"}">
          <div class="node-identity">
            <span class="node-name">${escapeHtml(node.node_id)}</span>
            <span class="node-url">${escapeHtml(node.url)}</span>
          </div>
          <div class="node-actions">
            ${statusBadge}
            ${syncBadge}
            ${actionButton}
          </div>
        </div>`;
    })
    .join("");
}

function renderVersionsTable(nodes) {
  const body = $("versions-body");
  if (nodes.length === 0) {
    body.innerHTML = '<tr><td colspan="4" class="empty">—</td></tr>';
    return;
  }

  body.innerHTML = nodes
    .map((node) => {
      const sync =
        node.sync === "synchronized"
          ? '<span class="badge badge-sync">Synchronisé</span>'
          : node.sync === "lagging"
            ? '<span class="badge badge-lag">En retard</span>'
            : '<span class="badge badge-inactive">Hors ligne</span>';
      return `
        <tr>
          <td><strong>${escapeHtml(node.node_id)}</strong></td>
          <td>${node.version ?? "—"}</td>
          <td>${node.last_ticket ?? "—"}</td>
          <td>${sync}</td>
        </tr>`;
    })
    .join("");
}

// ---------------------------------------------------------------
// Rafraîchissement des tickets et du journal
// ---------------------------------------------------------------

async function refreshTickets() {
  let data;
  try {
    const response = await fetch("/api/tickets");
    if (!response.ok) throw new Error();
    data = await response.json();
  } catch {
    return; // aucun nœud actif : on garde le dernier affichage connu
  }

  $("stat-last-ticket").textContent = data.last_ticket > 0 ? `N° ${data.last_ticket}` : "—";
  $("stat-total-tickets").textContent = data.tickets.length;
  $("tickets-source").textContent = `(lu depuis ${data.source})`;

  const ticketsBody = $("tickets-body");
  if (data.tickets.length === 0) {
    ticketsBody.innerHTML =
      '<tr><td colspan="4" class="empty">Aucun ticket pour le moment.</td></tr>';
  } else {
    ticketsBody.innerHTML = [...data.tickets]
      .reverse()
      .map(
        (t) => `
        <tr>
          <td class="ticket-number">N° ${t.ticket_number}</td>
          <td>${escapeHtml(t.client)}</td>
          <td>${escapeHtml(t.created_by)}</td>
          <td>${escapeHtml(t.timestamp)}</td>
        </tr>`
      )
      .join("");
  }

  const log = $("event-log");
  if (data.event_log.length === 0) {
    log.innerHTML = '<li class="empty">Aucun événement.</li>';
  } else {
    log.innerHTML = [...data.event_log]
      .reverse()
      .map(
        (e) => `
        <li>
          <span class="event-time">${escapeHtml(e.timestamp)}</span>
          ${escapeHtml(e.message)}
        </li>`
      )
      .join("");
  }
}

// ---------------------------------------------------------------
// Actions utilisateur
// ---------------------------------------------------------------

async function takeTicket() {
  const button = $("btn-take-ticket");
  button.disabled = true;
  try {
    const client = $("client-name").value.trim() || "Client anonyme";
    const response = await fetch("/api/ticket", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client }),
    });
    const data = await response.json();
    if (response.ok) {
      notify(
        `Ticket N° ${data.ticket.ticket_number} délivré par ${data.served_by} (version ${data.version}).`,
        "success"
      );
    } else {
      notify(data.error || "Impossible de créer un ticket.", "error");
    }
  } catch {
    notify("Erreur de communication avec le serveur web.", "error");
  } finally {
    button.disabled = false;
    await Promise.all([refreshCluster(), refreshTickets()]);
  }
}

async function failNode(nodeId) {
  try {
    await fetch(`/api/nodes/${nodeId}/fail`, { method: "POST" });
    notify(`Panne simulée sur ${nodeId}.`, "error");
  } catch {
    notify(`Impossible de contacter ${nodeId}.`, "error");
  }
  await refreshCluster();
}

async function restartNode(nodeId) {
  try {
    const response = await fetch(`/api/nodes/${nodeId}/restart`, { method: "POST" });
    const data = await response.json();
    const version = data.recovery ? data.recovery.version : "?";
    notify(`${nodeId} redémarré — état récupéré (version ${version}).`, "success");
  } catch {
    notify(`Impossible de redémarrer ${nodeId}.`, "error");
  }
  await Promise.all([refreshCluster(), refreshTickets()]);
}

// ---------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------

$("btn-take-ticket").addEventListener("click", takeTicket);
$("client-name").addEventListener("keydown", (event) => {
  if (event.key === "Enter") takeTicket();
});

refreshCluster();
refreshTickets();
setInterval(refreshCluster, REFRESH_INTERVAL_MS);
setInterval(refreshTickets, REFRESH_INTERVAL_MS);
