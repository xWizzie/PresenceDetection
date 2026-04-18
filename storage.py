import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "raw" / "sensor_samples.sqlite3"


SENSOR_SAMPLES_SCHEMA = """
    CREATE TABLE IF NOT EXISTS sensor_samples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        received_at TEXT NOT NULL,
        node_id TEXT NOT NULL,
        timestamp_ms INTEGER,
        uptime_ms INTEGER,
        pir INTEGER,
        wifi_rssi REAL,
        source_endpoint TEXT,
        ip TEXT
    )
"""


def connect(db_path=DEFAULT_DB_PATH):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def init_storage(db_path=DEFAULT_DB_PATH):
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with connect(db_path) as connection:
        connection.execute(SENSOR_SAMPLES_SCHEMA)
        migrate_sensor_samples_schema(connection)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_sensor_samples_node_received
            ON sensor_samples (node_id, received_at)
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_sensor_samples_received
            ON sensor_samples (received_at)
        """)


def migrate_sensor_samples_schema(connection):
    columns = {
        row["name"]: row["type"].upper()
        for row in connection.execute("PRAGMA table_info(sensor_samples)")
    }
    if (
        columns.get("timestamp_ms") == "INTEGER"
        and columns.get("uptime_ms") == "INTEGER"
    ):
        return

    connection.execute("ALTER TABLE sensor_samples RENAME TO sensor_samples_old")
    connection.execute(SENSOR_SAMPLES_SCHEMA)
    connection.execute("""
        INSERT INTO sensor_samples (
            id,
            received_at,
            node_id,
            timestamp_ms,
            uptime_ms,
            pir,
            wifi_rssi,
            source_endpoint,
            ip
        )
        SELECT
            id,
            received_at,
            node_id,
            CAST(timestamp_ms AS INTEGER),
            CAST(uptime_ms AS INTEGER),
            pir,
            wifi_rssi,
            source_endpoint,
            ip
        FROM sensor_samples_old
    """)
    connection.execute("DROP TABLE sensor_samples_old")


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


def fetch_samples(node_id=None, db_path=DEFAULT_DB_PATH):
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

    query += " ORDER BY node_id ASC, received_at ASC, id ASC"

    with connect(db_path) as connection:
        rows = connection.execute(query, params).fetchall()

    return [row_to_sample(row) for row in rows]


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
