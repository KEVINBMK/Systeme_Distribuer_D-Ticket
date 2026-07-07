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
// Rafraîchissement du cluster (panneau latéral + état distribué)
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

  const versions = nodes.map((n) => n.version).filter((v) => v !== null);
  $("stat-version").textContent = versions.length ? Math.max(...versions) : "—";

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
  renderVersionBars(nodes);
  $("btn-take-ticket").disabled = activeCount === 0;
}

function renderNodeCards(nodes) {
  const list = $("nodes-list");
  if (nodes.length === 0) {
    list.innerHTML = '<p class="side-empty">Aucun nœud enregistré auprès du registry.</p>';
    return;
  }

  list.innerHTML = nodes
    .map((node) => {
      const isActive = node.status === "active";
      const syncBadge =
        node.sync === "synchronized"
          ? '<span class="badge badge-mini badge-active">Synchronisé</span>'
          : node.sync === "lagging"
            ? '<span class="badge badge-mini badge-lag">En retard</span>'
            : '<span class="badge badge-mini badge-inactive">Hors ligne</span>';
      const actionButton = isActive
        ? `<button class="btn btn-ghost danger" onclick="failNode('${node.node_id}')">Simuler panne</button>`
        : `<button class="btn btn-ghost success" onclick="restartNode('${node.node_id}')">Redémarrer</button>`;

      return `
        <div class="node-card ${isActive ? "" : "node-down"}">
          <div class="node-top">
            <span class="status-dot ${isActive ? "on" : "off"}"></span>
            <span class="node-name">${escapeHtml(node.node_id)}</span>
            <span class="node-version">v${node.version ?? "?"}</span>
          </div>
          <div class="node-bottom">
            <span class="node-url">${escapeHtml(node.url.replace("http://", ""))}</span>
            ${actionButton}
          </div>
          <div class="node-bottom">
            ${syncBadge}
          </div>
        </div>`;
    })
    .join("");
}

function renderVersionBars(nodes) {
  const list = $("versions-list");
  if (nodes.length === 0) {
    list.innerHTML = '<p class="empty">—</p>';
    return;
  }

  const maxVersion = Math.max(1, ...nodes.map((n) => n.version ?? 0));

  list.innerHTML = nodes
    .map((node) => {
      const version = node.version ?? 0;
      const percent = Math.round((version / maxVersion) * 100);
      const fillClass =
        node.status !== "active" ? "off" : node.sync === "lagging" ? "lag" : "";
      const label =
        node.status !== "active"
          ? "hors ligne"
          : `v${version} / v${maxVersion}`;
      return `
        <div class="version-row">
          <div class="version-head">
            <span class="vname">${escapeHtml(node.node_id)}</span>
            <span class="vnum">${label}</span>
          </div>
          <div class="version-track">
            <div class="version-fill ${fillClass}" style="width:${node.status === "active" ? percent : 4}%"></div>
          </div>
        </div>`;
    })
    .join("");
}

// ---------------------------------------------------------------
// Rafraîchissement des tickets, du ticket de guichet et du journal
// ---------------------------------------------------------------

function classifyEvent(message) {
  if (message.includes("PANNE")) return "evt-panne";
  if (message.includes("REDÉMARRAGE") || message.includes("Récupération réussie")) return "evt-retour";
  if (message.includes("répliqué")) return "evt-replication";
  return "";
}

async function refreshTickets() {
  let data;
  try {
    const response = await fetch("/api/tickets");
    if (!response.ok) throw new Error();
    data = await response.json();
  } catch {
    return; // aucun nœud actif : on garde le dernier affichage connu
  }

  $("stat-total-tickets").textContent = data.tickets.length;
  $("tickets-source").textContent = `lu depuis ${data.source}`;

  // Ticket de guichet : le dernier ticket émis.
  const last = data.tickets[data.tickets.length - 1];
  if (last) {
    $("stub-number").textContent = String(last.ticket_number).padStart(3, "0");
    $("stub-client").textContent = last.client;
    $("stub-node").textContent = last.created_by;
    $("stub-time").textContent = last.timestamp;
  } else {
    $("stub-number").textContent = "—";
    $("stub-client").textContent = "En attente du premier ticket";
    $("stub-node").textContent = "—";
    $("stub-time").textContent = "—";
  }

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
          <td class="ticket-number">${String(t.ticket_number).padStart(3, "0")}</td>
          <td>${escapeHtml(t.client)}</td>
          <td><span class="node-chip">${escapeHtml(t.created_by)}</span></td>
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
        <li class="${classifyEvent(e.message)}">
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
