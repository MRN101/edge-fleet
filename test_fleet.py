"""
Unit and Integration Tests for Edge Fleet Health Monitor
---------------------------------------------------------
Verifies:
1. Database initialization and table schemas.
2. Metric ingestion via POST /api/metrics (valid and invalid inputs).
3. Offline node detection logic (>15 seconds inactivity).
4. High-CPU warning flag logic (>= 80%).
5. Node listing and summary counts via GET /api/nodes.
6. Recent readings endpoint GET /api/recent-metrics.
7. Dashboard HTML delivery via GET /.
8. Agent metric collection via psutil.
"""

import os
import time
import unittest
import app as flask_app
import agent as edge_agent


class TestEdgeFleetMonitor(unittest.TestCase):
    def setUp(self):
        # Use an isolated test database
        flask_app.DATABASE_FILE = "test_fleet.db"
        if os.path.exists("test_fleet.db"):
            os.remove("test_fleet.db")

        # Initialize test database
        flask_app.init_db()

        # Set up Flask test client
        self.client = flask_app.app.test_client()
        self.client.testing = True

    def tearDown(self):
        # Clean up test database file
        if os.path.exists("test_fleet.db"):
            os.remove("test_fleet.db")

    def test_database_initialization(self):
        """Test 1: Verify database and tables are created automatically."""
        self.assertTrue(os.path.exists("test_fleet.db"))
        conn = flask_app.get_db_connection()
        cursor = conn.cursor()

        # Check nodes table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='nodes'")
        self.assertIsNotNone(cursor.fetchone())

        # Check metrics table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='metrics'")
        self.assertIsNotNone(cursor.fetchone())
        conn.close()

    def test_valid_metrics_submission(self):
        """Test 2: Test sending valid metric readings."""
        payload = {
            "node_id": "node-test-1",
            "cpu_percent": 45.5,
            "memory_percent": 60.2,
            "disk_percent": 30.0
        }
        response = self.client.post("/api/metrics", json=payload)
        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertEqual(data["status"], "success")

        # Verify entry in 'nodes' table
        conn = flask_app.get_db_connection()
        row = conn.execute("SELECT * FROM nodes WHERE node_id='node-test-1'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["cpu_percent"], 45.5)
        self.assertEqual(row["memory_percent"], 60.2)
        self.assertEqual(row["disk_percent"], 30.0)

        # Verify entry in 'metrics' table
        metric_row = conn.execute("SELECT * FROM metrics WHERE node_id='node-test-1'").fetchone()
        self.assertIsNotNone(metric_row)
        self.assertEqual(metric_row["cpu_percent"], 45.5)
        conn.close()

    def test_invalid_metrics_and_missing_node_id(self):
        """Test 3: Test rejection of invalid values and missing fields."""
        # Missing node_id
        res = self.client.post("/api/metrics", json={
            "cpu_percent": 20.0,
            "memory_percent": 50.0,
            "disk_percent": 50.0
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("node_id", res.get_json()["message"])

        # Blank node_id
        res = self.client.post("/api/metrics", json={
            "node_id": "   ",
            "cpu_percent": 20.0,
            "memory_percent": 50.0,
            "disk_percent": 50.0
        })
        self.assertEqual(res.status_code, 400)

        # Negative CPU percentage
        res = self.client.post("/api/metrics", json={
            "node_id": "node-err",
            "cpu_percent": -5.0,
            "memory_percent": 50.0,
            "disk_percent": 50.0
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("between 0.0 and 100.0", res.get_json()["message"])

        # CPU percentage over 100
        res = self.client.post("/api/metrics", json={
            "node_id": "node-err",
            "cpu_percent": 150.0,
            "memory_percent": 50.0,
            "disk_percent": 50.0
        })
        self.assertEqual(res.status_code, 400)

        # Non-numeric value for memory
        res = self.client.post("/api/metrics", json={
            "node_id": "node-err",
            "cpu_percent": 50.0,
            "memory_percent": "ninety",
            "disk_percent": 50.0
        })
        self.assertEqual(res.status_code, 400)

        # Non-JSON payload
        res = self.client.post("/api/metrics", data="plain text not json")
        self.assertEqual(res.status_code, 400)

    def test_offline_detection_and_high_cpu(self):
        """Test 4: Verify offline detection (>15s) and high CPU warning (>=80%)."""
        conn = flask_app.get_db_connection()
        now = time.time()

        # Insert node-active: reported 2 seconds ago (ONLINE, normal CPU)
        conn.execute("""
            INSERT INTO nodes (node_id, cpu_percent, memory_percent, disk_percent, last_seen)
            VALUES (?, ?, ?, ?, ?)
        """, ("node-active", 35.0, 40.0, 50.0, now - 2))

        # Insert node-hot: reported 3 seconds ago (ONLINE, HIGH CPU)
        conn.execute("""
            INSERT INTO nodes (node_id, cpu_percent, memory_percent, disk_percent, last_seen)
            VALUES (?, ?, ?, ?, ?)
        """, ("node-hot", 88.5, 40.0, 50.0, now - 3))

        # Insert node-silent: reported 25 seconds ago (OFFLINE)
        conn.execute("""
            INSERT INTO nodes (node_id, cpu_percent, memory_percent, disk_percent, last_seen)
            VALUES (?, ?, ?, ?, ?)
        """, ("node-silent", 10.0, 20.0, 30.0, now - 25))

        conn.commit()
        conn.close()

        # Query /api/nodes
        response = self.client.get("/api/nodes")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        # Check summary
        summary = data["summary"]
        self.assertEqual(summary["total_nodes"], 3)
        self.assertEqual(summary["online_nodes"], 2)
        self.assertEqual(summary["offline_nodes"], 1)
        self.assertEqual(summary["high_cpu_warnings"], 1)

        # Check individual node statuses
        nodes = {n["node_id"]: n for n in data["nodes"]}

        self.assertTrue(nodes["node-active"]["is_online"])
        self.assertFalse(nodes["node-active"]["is_high_cpu"])

        self.assertTrue(nodes["node-hot"]["is_online"])
        self.assertTrue(nodes["node-hot"]["is_high_cpu"])

        self.assertFalse(nodes["node-silent"]["is_online"])
        self.assertGreater(nodes["node-silent"]["seconds_since_report"], 15.0)

    def test_node_reconnection_resumes_online_status(self):
        """Test 5: Verify that an offline node automatically becomes online when it reports again."""
        conn = flask_app.get_db_connection()
        now = time.time()
        # Node was offline (reported 40s ago)
        conn.execute("""
            INSERT INTO nodes (node_id, cpu_percent, memory_percent, disk_percent, last_seen)
            VALUES (?, ?, ?, ?, ?)
        """, ("node-recovered", 10.0, 20.0, 30.0, now - 40))
        conn.commit()
        conn.close()

        # Confirm offline
        res1 = self.client.get("/api/nodes").get_json()
        self.assertFalse(res1["nodes"][0]["is_online"])

        # Agent reports new metrics
        self.client.post("/api/metrics", json={
            "node_id": "node-recovered",
            "cpu_percent": 25.0,
            "memory_percent": 30.0,
            "disk_percent": 35.0
        })

        # Confirm it is now online again
        res2 = self.client.get("/api/nodes").get_json()
        self.assertTrue(res2["nodes"][0]["is_online"])
        self.assertEqual(res2["nodes"][0]["cpu_percent"], 25.0)

    def test_recent_metrics_endpoint(self):
        """Test 6: Test that GET /api/recent-metrics returns historical records."""
        for i in range(5):
            self.client.post("/api/metrics", json={
                "node_id": f"node-{i}",
                "cpu_percent": 10.0 + i,
                "memory_percent": 20.0 + i,
                "disk_percent": 30.0 + i
            })

        response = self.client.get("/api/recent-metrics")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["count"], 5)
        # Should be ordered DESC (latest first)
        self.assertEqual(data["metrics"][0]["node_id"], "node-4")

    def test_dashboard_page_load(self):
        """Test 7: Test that GET / serves the HTML dashboard."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Edge Fleet Health Monitor", html)
        self.assertIn("nodes-table", html)
        self.assertIn("metrics-table", html)

    def test_agent_metrics_collection(self):
        """Test 8: Test agent psutil metrics collection function."""
        metrics = edge_agent.collect_system_metrics()
        self.assertIn("cpu_percent", metrics)
        self.assertIn("memory_percent", metrics)
        self.assertIn("disk_percent", metrics)
        self.assertGreaterEqual(metrics["cpu_percent"], 0.0)
        self.assertLessEqual(metrics["cpu_percent"], 100.0)
        self.assertGreaterEqual(metrics["memory_percent"], 0.0)
        self.assertLessEqual(metrics["memory_percent"], 100.0)
        self.assertGreaterEqual(metrics["disk_percent"], 0.0)
        self.assertLessEqual(metrics["disk_percent"], 100.0)


if __name__ == "__main__":
    unittest.main()
