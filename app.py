"""
Edge Fleet Health Monitor - Central Server
------------------------------------------
A simple, beginner-friendly Flask application that receives metrics
from distributed edge monitoring agents, stores them in SQLite,
and serves a live dashboard.
"""

import os
import sqlite3
import time
from datetime import datetime
from flask import Flask, jsonify, render_template, request

# Initialize Flask application
app = Flask(__name__)

# Name of our local SQLite database file
DATABASE_FILE = "fleet.db"

# Threshold in seconds to consider an edge node offline
OFFLINE_THRESHOLD_SECONDS = 15

# Threshold percentage to flag high CPU usage
HIGH_CPU_THRESHOLD_PERCENT = 80.0


def get_db_connection():
    """
    Open a connection to the SQLite database.
    row_factory = sqlite3.Row allows accessing columns by name like dictionaries.
    """
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """
    Automatically create the required database tables if they do not exist.
    This runs once when the Flask server starts up.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Table 1: nodes - stores the latest snapshot of each edge computer
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS nodes (
            node_id TEXT PRIMARY KEY,
            cpu_percent REAL NOT NULL,
            memory_percent REAL NOT NULL,
            disk_percent REAL NOT NULL,
            last_seen REAL NOT NULL
        )
    """)

    # Table 2: metrics - stores chronological historical readings for auditing/trends
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id TEXT NOT NULL,
            cpu_percent REAL NOT NULL,
            memory_percent REAL NOT NULL,
            disk_percent REAL NOT NULL,
            timestamp REAL NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def validate_percentage(field_name, value):
    """
    Helper function to validate that a metric reading is a number between 0 and 100.
    Returns (True, None) if valid, or (False, error_message) if invalid.
    """
    if value is None:
        return False, f"Missing required field: '{field_name}'"

    # Check that value is an integer or float (and not a boolean, since bool subclasses int)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False, f"Field '{field_name}' must be a number, got {type(value).__name__}"

    if value < 0.0 or value > 100.0:
        return False, f"Field '{field_name}' must be between 0.0 and 100.0, got {value}"

    return True, None


@app.route("/")
def index():
    """
    Serve the main HTML dashboard interface.
    """
    return render_template("index.html")


@app.route("/api/metrics", methods=["POST"])
def receive_metrics():
    """
    Receive telemetry metrics from an edge agent.
    Validates input, updates the node's current status in 'nodes',
    and appends the reading to the historical 'metrics' log.
    """
    # 1. Parse JSON body
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({
            "status": "error",
            "message": "Invalid JSON body. Please provide a JSON object."
        }), 400

    # 2. Validate node_id
    node_id = data.get("node_id")
    if not node_id or not isinstance(node_id, str) or not node_id.strip():
        return jsonify({
            "status": "error",
            "message": "Field 'node_id' is required and must be a non-empty string."
        }), 400

    node_id = node_id.strip()

    # 3. Validate CPU, memory, and disk percentages
    for field in ["cpu_percent", "memory_percent", "disk_percent"]:
        is_valid, err_msg = validate_percentage(field, data.get(field))
        if not is_valid:
            return jsonify({"status": "error", "message": err_msg}), 400

    cpu_percent = float(data["cpu_percent"])
    memory_percent = float(data["memory_percent"])
    disk_percent = float(data["disk_percent"])

    # 4. Use server receipt time as the authoritative timestamp.
    # Distributed edge systems often experience clock drift or unsynchronized RTCs.
    # Using server time guarantees accurate offline detection across all nodes.
    server_time = time.time()

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 5. Update or insert the latest snapshot in the 'nodes' table
        cursor.execute("""
            INSERT INTO nodes (node_id, cpu_percent, memory_percent, disk_percent, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                cpu_percent = excluded.cpu_percent,
                memory_percent = excluded.memory_percent,
                disk_percent = excluded.disk_percent,
                last_seen = excluded.last_seen
        """, (node_id, cpu_percent, memory_percent, disk_percent, server_time))

        # 6. Append to the historical 'metrics' log table
        cursor.execute("""
            INSERT INTO metrics (node_id, cpu_percent, memory_percent, disk_percent, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (node_id, cpu_percent, memory_percent, disk_percent, server_time))

        conn.commit()
    finally:
        conn.close()

    return jsonify({
        "status": "success",
        "message": f"Metrics recorded for node '{node_id}'"
    }), 201


@app.route("/api/nodes", methods=["GET"])
def get_nodes():
    """
    Return the current status of all known edge nodes.
    Calculates whether each node is online (reported within 15s)
    and flags high CPU usage (>= 80%).
    """
    now = time.time()
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT node_id, cpu_percent, memory_percent, disk_percent, last_seen
        FROM nodes
        ORDER BY node_id ASC
    """)
    rows = cursor.fetchall()
    conn.close()

    nodes_list = []
    for row in rows:
        seconds_ago = round(now - row["last_seen"], 1)
        is_online = seconds_ago <= OFFLINE_THRESHOLD_SECONDS
        is_high_cpu = row["cpu_percent"] >= HIGH_CPU_THRESHOLD_PERCENT

        # Human-readable format of last seen time
        formatted_time = datetime.fromtimestamp(row["last_seen"]).strftime("%Y-%m-%d %H:%M:%S")

        nodes_list.append({
            "node_id": row["node_id"],
            "cpu_percent": round(row["cpu_percent"], 1),
            "memory_percent": round(row["memory_percent"], 1),
            "disk_percent": round(row["disk_percent"], 1),
            "last_seen_epoch": row["last_seen"],
            "last_seen_formatted": formatted_time,
            "seconds_since_report": seconds_ago,
            "is_online": is_online,
            "is_high_cpu": is_high_cpu
        })

    # Summary counts for dashboard header badges
    online_count = sum(1 for n in nodes_list if n["is_online"])
    offline_count = sum(1 for n in nodes_list if not n["is_online"])
    high_cpu_count = sum(1 for n in nodes_list if n["is_high_cpu"] and n["is_online"])

    return jsonify({
        "status": "success",
        "summary": {
            "total_nodes": len(nodes_list),
            "online_nodes": online_count,
            "offline_nodes": offline_count,
            "high_cpu_warnings": high_cpu_count
        },
        "nodes": nodes_list
    }), 200


@app.route("/api/recent-metrics", methods=["GET"])
def get_recent_metrics():
    """
    Return the most recent metrics readings from all nodes (latest 15 readings).
    Useful for visualizing raw event history on the dashboard.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, node_id, cpu_percent, memory_percent, disk_percent, timestamp
        FROM metrics
        ORDER BY id DESC
        LIMIT 15
    """)
    rows = cursor.fetchall()
    conn.close()

    recent_readings = []
    for row in rows:
        formatted_time = datetime.fromtimestamp(row["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
        recent_readings.append({
            "id": row["id"],
            "node_id": row["node_id"],
            "cpu_percent": round(row["cpu_percent"], 1),
            "memory_percent": round(row["memory_percent"], 1),
            "disk_percent": round(row["disk_percent"], 1),
            "timestamp_formatted": formatted_time
        })

    return jsonify({
        "status": "success",
        "count": len(recent_readings),
        "metrics": recent_readings
    }), 200


if __name__ == "__main__":
    # Ensure database tables exist before taking requests
    init_db()
    print("Edge Fleet Health Monitor server starting on http://127.0.0.1:5000 ...")
    app.run(host="127.0.0.1", port=5000, debug=False)
