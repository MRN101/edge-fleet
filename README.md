# Edge Fleet Health Monitor

A lightweight, centralized telemetry and health monitoring system for distributed edge nodes, built with Python, Flask, SQLite, and modern Vanilla web standards.

Edge Fleet Health Monitor enables operators to observe the operational status, resource utilization, and network connectivity of distributed computers from a single unified real-time dashboard.

---

## Features

- **Lightweight Telemetry Agent:** Periodic sampling of CPU, memory, and disk utilization via `psutil`.
- **Fault-Tolerant Transmission:** Client-side retry logic and graceful error recovery ensure agents continue running during network interruptions.
- **Authoritative Timestamping:** Server-side timestamping avoids false status alerts caused by edge clock drift.
- **Automated Offline Detection:** Nodes that fail to report within 15 seconds are flagged as offline, and automatically recover when telemetry resumes.
- **Workload Warning Triggers:** Real-time visual alerts when CPU load reaches or exceeds 80%, decoupled from node connectivity status.
- **Dual-Layer Persistence:** Dedicated snapshot table for $O(1)$ fleet status queries alongside an append-only time-series log for historical auditing.
- **Zero-Dependency Web UI:** Pure HTML, CSS, and Vanilla JavaScript with automatic 5-second polling and zero third-party frontend dependencies.

---

## Architecture & Data Flow

```
+-------------------------------------------------------------------------------+
|                             DISTRIBUTED EDGE NODES                            |
|                                                                               |
|   +--------------------+  +--------------------+  +--------------------+      |
|   |   Node: node-a     |  |   Node: node-b     |  |   Node: node-c     |      |
|   |  (agent.py worker) |  |  (agent.py worker) |  |  (agent.py worker) |      |
|   |  - psutil metrics  |  |  - psutil metrics  |  |  - psutil metrics  |      |
|   +---------+----------+  +---------+----------+  +---------+----------+      |
+-------------|-----------------------|-----------------------|-----------------+
              |                       |                       |
              | HTTP POST /api/metrics| HTTP POST /api/metrics| HTTP POST /api/metrics
              | (JSON payload)        | (JSON payload)        | (JSON payload)
              v                       v                       v
+-------------------------------------------------------------------------------+
|                          CENTRAL FLASK SERVER (app.py)                        |
|                                                                               |
|   1. Ingests and validates JSON telemetry                                     |
|   2. Stamps receipt with authoritative server timestamp                       |
|   3. Updates snapshot and writes time-series record to SQLite                 |
|   4. Evaluates node availability and workload thresholds                      |
+---------------------------------------+---------------------------------------+
                                        |
                   +--------------------+--------------------+
                   |                                         |
                   v                                         v
+--------------------------------------+   +------------------------------------+
|         SQLITE DATABASE              |   |       OPERATIONS DASHBOARD         |
|            (fleet.db)                |   |        (Vanilla JS Fetch)          |
|                                      |   |                                    |
|  - Table: nodes (fleet snapshot)     |   |  - Polls /api/nodes (every 5s)     |
|  - Table: metrics (historical log)   |   |  - Polls /api/recent-metrics (5s)  |
+--------------------------------------+   +------------------------------------+
```

### Telemetry Pipeline
1. **Sampling:** The client agent samples host CPU utilization (1-second sampling window), virtual memory, and root disk capacity.
2. **Transmission:** Metrics are transmitted via HTTP POST to `/api/metrics` with an HTTP timeout safeguard.
3. **Validation & Ingestion:** The server verifies payload integrity (data types, percentage ranges between $0.0$ and $100.0$) and updates the database.
4. **Availability Computation:** The server evaluates silence thresholds against server time (`now - last_seen > 15s`).
5. **Dashboard Rendering:** The web frontend polls the server every 5 seconds to reflect node states, health badges, and resource bars.

---

## Technology Stack

- **Backend:** Python 3.9+, Flask
- **Telemetry Collection:** `psutil`
- **Network Client:** `requests`
- **Storage:** SQLite (`sqlite3`)
- **Frontend:** HTML5, CSS3, Vanilla JavaScript (Fetch API)
- **Test Framework:** Python `unittest`

---

## Project Structure

```text
edge-fleet-monitor/
├── app.py              # Central Flask server, API endpoints, and DB initialization
├── agent.py            # Edge monitoring daemon script
├── requirements.txt    # Project dependencies
├── test_fleet.py       # Automated unit and integration test suite
├── README.md           # Documentation
├── templates/
│   └── index.html      # Operations dashboard layout
└── static/
    ├── style.css       # Clean dashboard styling and responsive layout
    └── app.js          # Client-side polling and DOM rendering
```

---

## Database Schema

The SQLite database (`fleet.db`) is initialized automatically on server launch with two dedicated tables:

### Table: `nodes` (Fleet Snapshot)
Maintains the latest known state of each unique node.

| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `node_id` | `TEXT` | `PRIMARY KEY` | Unique node identifier (e.g., `node-a`) |
| `cpu_percent` | `REAL` | `NOT NULL` | Latest CPU utilization percentage |
| `memory_percent`| `REAL` | `NOT NULL` | Latest RAM utilization percentage |
| `disk_percent` | `REAL` | `NOT NULL` | Latest root disk utilization percentage |
| `last_seen` | `REAL` | `NOT NULL` | Epoch timestamp of latest reported metrics |

### Table: `metrics` (Historical Time-Series)
Appends chronological telemetry events for audit trails and trend inspection.

| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Auto-incrementing reading ID |
| `node_id` | `TEXT` | `NOT NULL` | Identifier of reporting node |
| `cpu_percent` | `REAL` | `NOT NULL` | CPU utilization at time of report |
| `memory_percent`| `REAL` | `NOT NULL` | RAM utilization at time of report |
| `disk_percent` | `REAL` | `NOT NULL` | Disk utilization at time of report |
| `timestamp` | `REAL` | `NOT NULL` | Server receipt epoch timestamp |

---

## API Reference

### 1. Web Dashboard
```http
GET /
```
Serves the responsive web monitoring dashboard.

---

### 2. Ingest Metrics
```http
POST /api/metrics
Content-Type: application/json
```

**Request Body:**
```json
{
  "node_id": "node-a",
  "cpu_percent": 34.5,
  "memory_percent": 62.1,
  "disk_percent": 45.8
}
```

**Response (`201 Created`):**
```json
{
  "status": "success",
  "message": "Metrics recorded for node 'node-a'"
}
```

**Error Response (`400 Bad Request`):**
```json
{
  "status": "error",
  "message": "Field 'cpu_percent' must be between 0.0 and 100.0, got 105.0"
}
```

---

### 3. List Nodes & Fleet Summary
```http
GET /api/nodes
```

**Response (`200 OK`):**
```json
{
  "status": "success",
  "summary": {
    "total_nodes": 2,
    "online_nodes": 1,
    "offline_nodes": 1,
    "high_cpu_warnings": 1
  },
  "nodes": [
    {
      "node_id": "node-a",
      "cpu_percent": 88.5,
      "memory_percent": 65.0,
      "disk_percent": 42.0,
      "last_seen_epoch": 1791532214.5,
      "last_seen_formatted": "2026-10-09 13:20:14",
      "seconds_since_report": 2.4,
      "is_online": true,
      "is_high_cpu": true
    },
    {
      "node_id": "node-b",
      "cpu_percent": 22.0,
      "memory_percent": 40.0,
      "disk_percent": 30.0,
      "last_seen_epoch": 1791532180.0,
      "last_seen_formatted": "2026-10-09 13:19:40",
      "seconds_since_report": 36.9,
      "is_online": false,
      "is_high_cpu": false
    }
  ]
}
```

---

### 4. Fetch Recent Telemetry Stream
```http
GET /api/recent-metrics
```

**Response (`200 OK`):**
```json
{
  "status": "success",
  "count": 2,
  "metrics": [
    {
      "id": 104,
      "node_id": "node-a",
      "cpu_percent": 88.5,
      "memory_percent": 65.0,
      "disk_percent": 42.0,
      "timestamp_formatted": "2026-10-09 13:20:14"
    },
    {
      "id": 103,
      "node_id": "node-b",
      "cpu_percent": 22.0,
      "memory_percent": 40.0,
      "disk_percent": 30.0,
      "timestamp_formatted": "2026-10-09 13:20:10"
    }
  ]
}
```

---

## Installation & Setup

### Prerequisites
- Python 3.9 or higher

### 1. Clone or Open the Repository
```bash
cd Edge-fleet-monitor
```

### 2. Set Up a Virtual Environment

**On Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**On Linux / macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

---

## Usage

### 1. Start the Central Server
```bash
python app.py
```
The server will bind to `http://127.0.0.1:5000/`. Navigate to this URL in your web browser to view the live dashboard.

### 2. Launch Monitoring Agents
Open separate terminal sessions to launch agents representing distinct nodes:

```bash
# Terminal 2:
python agent.py node-a

# Terminal 3:
python agent.py node-b

# Terminal 4:
python agent.py node-c
```

Each agent will begin sending telemetry readings every ~5 seconds. The central dashboard will automatically reflect their online status and metrics.

---

## Operational Scenarios

### Offline Node Detection
- Stop an active agent using `Ctrl + C`.
- Because nodes report at 5-second intervals, a 15-second grace window is applied to absorb transient network jitter.
- Once 15 seconds elapse without a report, the dashboard marks the node as **OFFLINE** and highlights the elapsed downtime.
- Restarting the agent immediately transitions the node back to **ONLINE** status without data loss.

### High CPU Workload Alerts
- Nodes operating at $\ge 80\%$ CPU utilization are flagged with a **HIGH CPU** alert badge.
- High-CPU status is decoupled from connectivity: a node can remain **ONLINE** while under critical workload pressure.

---

## Testing

Run the automated test suite:

```bash
python test_fleet.py
```

The test suite validates:
- Automatic schema creation for both `nodes` and `metrics` tables.
- Input validation (missing identifiers, non-numeric values, negative percentages, values $>100\%$).
- Server-side offline detection logic ($>15$s threshold).
- High-CPU threshold detection ($\ge 80\%$).
- Node reconnection and recovery.
- Chronological retrieval of recent telemetry readings.
- Live hardware metrics extraction via `psutil`.

