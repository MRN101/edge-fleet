"""
Edge Fleet Health Monitor - Monitoring Agent
--------------------------------------------
A lightweight script that runs on an edge computer (or a simulated node),
samples system resource usage (CPU, RAM, Disk) using psutil, and reports
metrics to the central Flask server every 5 seconds.

Usage:
    python agent.py <node-id>

Example:
    python agent.py node-a
"""

import os
import sys
import time
from datetime import datetime
import psutil
import requests

# Central server endpoint where metrics are received
SERVER_URL = "http://127.0.0.1:5000/api/metrics"

# Total interval between metric reports in seconds
REPORT_INTERVAL_SECONDS = 5.0

# Timeout for the HTTP POST request to avoid hanging indefinitely if server is unresponsive
REQUEST_TIMEOUT_SECONDS = 3.0


def collect_system_metrics():
    """
    Collect current system resource utilization using psutil.
    Returns a dictionary with cpu_percent, memory_percent, and disk_percent.
    """
    # psutil.cpu_percent with interval=1 blocks for 1 second to measure active CPU usage accurately
    cpu = psutil.cpu_percent(interval=1.0)

    # psutil.virtual_memory().percent returns the percentage of used RAM
    memory = psutil.virtual_memory().percent

    # psutil.disk_usage: os.path.abspath(os.sep) resolves to 'C:\\' on Windows and '/' on Linux/macOS
    root_drive = os.path.abspath(os.sep)
    disk = psutil.disk_usage(root_drive).percent

    return {
        "cpu_percent": round(cpu, 1),
        "memory_percent": round(memory, 1),
        "disk_percent": round(disk, 1),
    }


def send_report(node_id, metrics):
    """
    Send metrics payload as JSON to the Flask central server via HTTP POST.
    Returns True if successful, False otherwise.
    """
    payload = {
        "node_id": node_id,
        "cpu_percent": metrics["cpu_percent"],
        "memory_percent": metrics["memory_percent"],
        "disk_percent": metrics["disk_percent"],
    }

    response = requests.post(
        SERVER_URL,
        json=payload,
        timeout=REQUEST_TIMEOUT_SECONDS
    )

    # Raise an exception if the server returned a 4xx or 5xx status code
    response.raise_for_status()
    return True


def run_agent(node_id):
    """
    Main monitoring loop. Gathers metrics and sends them approximately every 5 seconds.
    Catches network failures gracefully so the agent keeps running even if the server is down.
    """
    print("=" * 60)
    print(f"Edge Fleet Monitoring Agent started for node: [{node_id}]")
    print(f"Reporting target: {SERVER_URL}")
    print(f"Reporting interval: ~{int(REPORT_INTERVAL_SECONDS)} seconds")
    print("Press Ctrl+C to stop the agent.")
    print("=" * 60)

    while True:
        cycle_start = time.time()
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1. Collect live hardware metrics
        metrics = collect_system_metrics()

        # 2. Attempt to transmit metrics to the central server
        try:
            send_report(node_id, metrics)
            print(
                f"[{timestamp_str}] [{node_id}] Report SENT -> "
                f"CPU: {metrics['cpu_percent']}%, "
                f"RAM: {metrics['memory_percent']}%, "
                f"Disk: {metrics['disk_percent']}%"
            )
        except requests.exceptions.ConnectionError:
            # Server is down or unreachable
            print(
                f"[{timestamp_str}] [{node_id}] Connection error: Unable to reach server at {SERVER_URL}. "
                f"Will retry next cycle..."
            )
        except requests.exceptions.Timeout:
            # Request timed out
            print(
                f"[{timestamp_str}] [{node_id}] Timeout error: Server took too long to respond. "
                f"Will retry next cycle..."
            )
        except requests.exceptions.HTTPError as e:
            # Server returned 4xx or 5xx error
            print(
                f"[{timestamp_str}] [{node_id}] HTTP error: Server rejected reading ({e}). "
                f"Will retry next cycle..."
            )
        except Exception as e:
            # Any other unexpected exception
            print(
                f"[{timestamp_str}] [{node_id}] Unexpected error: {e}. "
                f"Will retry next cycle..."
            )

        # 3. Calculate remaining sleep time to maintain steady 5-second interval
        elapsed = time.time() - cycle_start
        sleep_duration = max(0.0, REPORT_INTERVAL_SECONDS - elapsed)
        time.sleep(sleep_duration)


def main():
    # Ensure node-id is provided via command-line argument
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print("Error: Missing node ID.")
        print("Usage: python agent.py <node-id>")
        print("Example: python agent.py node-a")
        sys.exit(1)

    node_id = sys.argv[1].strip()

    try:
        run_agent(node_id)
    except KeyboardInterrupt:
        print(f"\n[{node_id}] Monitoring agent stopped by user.")
        sys.exit(0)


if __name__ == "__main__":
    main()
