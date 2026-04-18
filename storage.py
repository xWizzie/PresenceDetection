import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path("data/raw/sensor_samples.sqlite3")


def connect(db_path=DEFAULT_DB_PATH):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def init_storage(db_path=DEFAULT_DB_PATH):
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with connect(db_path) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS sensor_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                received_at TEXT NOT NULL,
                node_id TEXT NOT NULL,
                timestamp_ms REAL,
                uptime_ms REAL,
                pir INTEGER,
                wifi_rssi REAL,
                source_endpoint TEXT,
                ip TEXT
            )
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_sensor_samples_node_received
            ON sensor_samples (node_id, received_at)
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_sensor_samples_received
            ON sensor_samples (received_at)
        """)


def insert_sensor_sample(sample, db_path=DEFAULT_DB_PATH):
    pir = sample.get("pir")
    if pir is not None:
        pir = 1 if pir else 0

    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO sensor_samples (
                received_at,
                node_id,
                timestamp_ms,
                uptime_ms,
                pir,
                wifi_rssi,
                source_endpoint,
                ip
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sample["server_received_at"],
                sample["node_id"],
                sample.get("timestamp_ms"),
                sample.get("uptime_ms"),
                pir,
                sample.get("wifi_rssi"),
                sample.get("source_endpoint"),
                sample.get("ip"),
            ),
        )
        return cursor.lastrowid


def fetch_recent_samples(limit=300, node_id=None, db_path=DEFAULT_DB_PATH):
    query = """
        SELECT
            id,
            received_at,
            node_id,
            timestamp_ms,
            uptime_ms,
            pir,
            wifi_rssi,
            source_endpoint,
            ip
        FROM sensor_samples
    """
    params = []

    if node_id:
        query += " WHERE node_id = ?"
        params.append(node_id)

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    with connect(db_path) as connection:
        rows = connection.execute(query, params).fetchall()

    samples = [row_to_sample(row) for row in rows]
    samples.reverse()
    return samples


def count_samples(node_id=None, db_path=DEFAULT_DB_PATH):
    query = "SELECT COUNT(*) AS count FROM sensor_samples"
    params = []

    if node_id:
        query += " WHERE node_id = ?"
        params.append(node_id)

    with connect(db_path) as connection:
        row = connection.execute(query, params).fetchone()

    return row["count"]


def row_to_sample(row):
    pir = row["pir"]
    if pir is not None:
        pir = bool(pir)

    return {
        "id": row["id"],
        "timestamp": row["received_at"],
        "server_received_at": row["received_at"],
        "received_at": row["received_at"],
        "node_id": row["node_id"],
        "sensor": row["node_id"],
        "pir": pir,
        "motion": pir,
        "timestamp_ms": row["timestamp_ms"],
        "uptime_ms": row["uptime_ms"],
        "wifi_rssi": row["wifi_rssi"],
        "rssi": row["wifi_rssi"],
        "source_endpoint": row["source_endpoint"],
        "ip": row["ip"],
    }
