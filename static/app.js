/**
 * Edge Fleet Health Monitor - Frontend JavaScript
 * -------------------------------------------------
 * Periodically polls the Flask REST API endpoints:
 *   - GET /api/nodes: Latest snapshot of all edge computers
 *   - GET /api/recent-metrics: Chronological log of recent telemetry
 *
 * Uses plain Vanilla JavaScript (fetch API, DOM manipulation).
 */

// Polling interval in milliseconds (5 seconds)
const POLL_INTERVAL_MS = 5000;

// DOM Elements
const totalNodesEl = document.getElementById("total-nodes");
const onlineNodesEl = document.getElementById("online-nodes");
const offlineNodesEl = document.getElementById("offline-nodes");
const highCpuNodesEl = document.getElementById("high-cpu-nodes");
const nodesCountBadgeEl = document.getElementById("nodes-count-badge");

const nodesTableEl = document.getElementById("nodes-table");
const nodesTableBodyEl = document.getElementById("nodes-table-body");
const nodesEmptyStateEl = document.getElementById("nodes-empty-state");

const metricsTableEl = document.getElementById("metrics-table");
const metricsTableBodyEl = document.getElementById("metrics-table-body");
const metricsEmptyStateEl = document.getElementById("metrics-empty-state");

const syncDotEl = document.getElementById("sync-dot");
const syncTextEl = document.getElementById("sync-text");
const serverTimeEl = document.getElementById("server-time");
const refreshBtn = document.getElementById("refresh-btn");

/**
 * Helper to build a progress bar HTML for a given percentage value.
 * Changes color:
 *   - Red (critical) if >= 90%
 *   - Amber (high) if >= 80%
 *   - Blue (normal) otherwise
 */
function createUsageBar(percentage, isCpu = false) {
    let colorClass = "normal";
    if (percentage >= 90) {
        colorClass = "critical";
    } else if (percentage >= 80) {
        colorClass = "high";
    }

    const warningBadge = (isCpu && percentage >= 80)
        ? '<span class="warning-tag">HIGH CPU</span>'
        : '';

    return `
        <div class="usage-cell">
            <div class="usage-info">
                <span><strong>${percentage}%</strong>${warningBadge}</span>
            </div>
            <div class="usage-bar-bg">
                <div class="usage-bar-fill ${colorClass}" style="width: ${Math.min(percentage, 100)}%;"></div>
            </div>
        </div>
    `;
}

/**
 * Fetch latest nodes snapshot from GET /api/nodes and update the UI.
 */
async function fetchNodesData() {
    try {
        const response = await fetch("/api/nodes");
        if (!response.ok) {
            throw new Error(`Server returned HTTP ${response.status}`);
        }

        const data = await response.json();

        // 1. Update summary cards
        const summary = data.summary || {};
        totalNodesEl.textContent = summary.total_nodes ?? 0;
        onlineNodesEl.textContent = summary.online_nodes ?? 0;
        offlineNodesEl.textContent = summary.offline_nodes ?? 0;
        highCpuNodesEl.textContent = summary.high_cpu_warnings ?? 0;

        const nodes = data.nodes || [];
        nodesCountBadgeEl.textContent = `${nodes.length} node${nodes.length === 1 ? "" : "s"}`;

        // 2. Render Nodes Table or Empty State
        if (nodes.length === 0) {
            nodesTableEl.style.display = "none";
            nodesEmptyStateEl.style.display = "block";
            nodesTableBodyEl.innerHTML = "";
        } else {
            nodesTableEl.style.display = "table";
            nodesEmptyStateEl.style.display = "none";

            nodesTableBodyEl.innerHTML = nodes.map(node => {
                const isOnline = node.is_online;
                const statusBadge = isOnline
                    ? '<span class="status-badge badge-online">&#x25CF; ONLINE</span>'
                    : '<span class="status-badge badge-offline">&#x25CF; OFFLINE</span>';

                const rowClass = isOnline ? "" : "node-offline-row";
                const timeElapsedText = isOnline
                    ? `${node.seconds_since_report}s ago`
                    : `${node.seconds_since_report}s ago (&gt;15s timeout)`;

                return `
                    <tr class="${rowClass}">
                        <td><span class="node-id-tag">${escapeHtml(node.node_id)}</span></td>
                        <td>${statusBadge}</td>
                        <td>${createUsageBar(node.cpu_percent, true)}</td>
                        <td>${createUsageBar(node.memory_percent, false)}</td>
                        <td>${createUsageBar(node.disk_percent, false)}</td>
                        <td>${node.last_seen_formatted}</td>
                        <td>${timeElapsedText}</td>
                    </tr>
                `;
            }).join("");
        }

        // Set live sync indicator to success
        syncDotEl.classList.remove("error");
        syncTextEl.textContent = `Live Polling (updated ${new Date().toLocaleTimeString()})`;
        serverTimeEl.textContent = new Date().toLocaleTimeString();

    } catch (err) {
        console.error("Error fetching nodes:", err);
        syncDotEl.classList.add("error");
        syncTextEl.textContent = "Server unreachable";
    }
}

/**
 * Fetch recent metrics log from GET /api/recent-metrics and update the UI.
 */
async function fetchRecentMetrics() {
    try {
        const response = await fetch("/api/recent-metrics");
        if (!response.ok) return;

        const data = await response.json();
        const metrics = data.metrics || [];

        if (metrics.length === 0) {
            metricsTableEl.style.display = "none";
            metricsEmptyStateEl.style.display = "block";
            metricsTableBodyEl.innerHTML = "";
        } else {
            metricsTableEl.style.display = "table";
            metricsEmptyStateEl.style.display = "none";

            metricsTableBodyEl.innerHTML = metrics.map(m => `
                <tr>
                    <td>#${m.id}</td>
                    <td><span class="node-id-tag">${escapeHtml(m.node_id)}</span></td>
                    <td>${m.timestamp_formatted}</td>
                    <td><strong>${m.cpu_percent}%</strong></td>
                    <td>${m.memory_percent}%</td>
                    <td>${m.disk_percent}%</td>
                </tr>
            `).join("");
        }
    } catch (err) {
        console.error("Error fetching recent metrics:", err);
    }
}

/**
 * Simple sanitizer for node IDs to prevent HTML injection in table cells.
 */
function escapeHtml(str) {
    if (!str) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

/**
 * Fetch all data now.
 */
async function refreshDashboard() {
    await Promise.all([fetchNodesData(), fetchRecentMetrics()]);
}

// Initial load
refreshDashboard();

// Set up periodic polling every 5 seconds
setInterval(refreshDashboard, POLL_INTERVAL_MS);

// Manual refresh button listener
refreshBtn.addEventListener("click", () => {
    refreshBtn.disabled = true;
    refreshDashboard().finally(() => {
        setTimeout(() => { refreshBtn.disabled = false; }, 500);
    });
});
