import sqlite3
from datetime import datetime, timedelta, timezone
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
        wifi_rssi INTEGER,
        source_endpoint TEXT,
        ip TEXT
    )
"""


TRAINING_LABELS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS training_labels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        label TEXT NOT NULL,
        label_name TEXT NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        created_at TEXT NOT NULL
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
        connection.execute(TRAINING_LABELS_SCHEMA)
        migrate_sensor_samples_schema(connection)
        normalize_training_labels(connection)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_sensor_samples_node_received
            ON sensor_samples (node_id, received_at)
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_sensor_samples_received
            ON sensor_samples (received_at)
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_training_labels_started
            ON training_labels (started_at)
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_training_labels_ended
            ON training_labels (ended_at)
        """)


def migrate_sensor_samples_schema(connection):
    columns = {
        row["name"]: row["type"].upper()
        for row in connection.execute("PRAGMA table_info(sensor_samples)")
    }
    if (
        columns.get("timestamp_ms") == "INTEGER"
        and columns.get("uptime_ms") == "INTEGER"
        and columns.get("wifi_rssi") == "INTEGER"
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
            CAST(wifi_rssi AS INTEGER),
            source_endpoint,
            ip
        FROM sensor_samples_old
    """)
    connection.execute("DROP TABLE sensor_samples_old")


def normalize_training_labels(connection):
    connection.execute(
        """
        UPDATE training_labels
        SET label = 'occupied',
            label_name = 'In room'
        WHERE label IN ('still', 'moving')
        """
    )


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


def prune_sensor_samples(
    max_samples=None,
    max_age_seconds=None,
    db_path=DEFAULT_DB_PATH,
    now=None,
):
    if max_samples is None and max_age_seconds is None:
        return 0

    if now is None:
        now = datetime.now(timezone.utc)

    with connect(db_path) as connection:
        before_changes = connection.total_changes

        if max_age_seconds is not None:
            cutoff = (
                now - timedelta(seconds=max_age_seconds)
            ).isoformat().replace("+00:00", "Z")
            connection.execute(
                """
                DELETE FROM sensor_samples
                WHERE received_at < ?
                  AND NOT EXISTS (
                    SELECT 1
                    FROM training_labels
                    WHERE sensor_samples.received_at >= training_labels.started_at
                      AND (
                        training_labels.ended_at IS NULL
                        OR sensor_samples.received_at <= training_labels.ended_at
                      )
                  )
                """,
                (cutoff,),
            )

        if max_samples is not None:
            connection.execute(
                """
                DELETE FROM sensor_samples
                WHERE id NOT IN (
                    SELECT id
                    FROM sensor_samples
                    ORDER BY id DESC
                    LIMIT ?
                )
                  AND NOT EXISTS (
                    SELECT 1
                    FROM training_labels
                    WHERE sensor_samples.received_at >= training_labels.started_at
                      AND (
                        training_labels.ended_at IS NULL
                        OR sensor_samples.received_at <= training_labels.ended_at
                      )
                  )
                """,
                (max_samples,),
            )

        return connection.total_changes - before_changes


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


def stop_active_training_label(ended_at, db_path=DEFAULT_DB_PATH):
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT *
            FROM training_labels
            WHERE ended_at IS NULL
            ORDER BY started_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()

        if row is None:
            return None

        connection.execute(
            """
            UPDATE training_labels
            SET ended_at = ?
            WHERE id = ?
            """,
            (ended_at, row["id"]),
        )
        return training_label_to_dict(row, ended_at=ended_at)


def start_training_label(label, label_name, started_at, db_path=DEFAULT_DB_PATH):
    with connect(db_path) as connection:
        active = connection.execute(
            """
            SELECT *
            FROM training_labels
            WHERE ended_at IS NULL
            ORDER BY started_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()

        if active and active["label"] == label:
            return training_label_to_dict(active)

        if active:
            connection.execute(
                """
                UPDATE training_labels
                SET ended_at = ?
                WHERE id = ?
                """,
                (started_at, active["id"]),
            )

        cursor = connection.execute(
            """
            INSERT INTO training_labels (
                label,
                label_name,
                started_at,
                ended_at,
                created_at
            )
            VALUES (?, ?, ?, NULL, ?)
            """,
            (label, label_name, started_at, started_at),
        )

        row = connection.execute(
            "SELECT * FROM training_labels WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return training_label_to_dict(row)


def get_active_training_label(db_path=DEFAULT_DB_PATH):
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT *
            FROM training_labels
            WHERE ended_at IS NULL
            ORDER BY started_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()

    return training_label_to_dict(row) if row else None


def fetch_training_labels(db_path=DEFAULT_DB_PATH, include_open=True, limit=None):
    query = """
        SELECT *
        FROM training_labels
    """
    params = []

    if not include_open:
        query += " WHERE ended_at IS NOT NULL"

    query += " ORDER BY started_at ASC, id ASC"

    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    with connect(db_path) as connection:
        rows = connection.execute(query, params).fetchall()

    return [training_label_to_dict(row) for row in rows]


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


def training_label_to_dict(row, ended_at=None):
    if row is None:
        return None

    return {
        "id": row["id"],
        "label": row["label"],
        "label_name": row["label_name"],
        "started_at": row["started_at"],
        "ended_at": ended_at if ended_at is not None else row["ended_at"],
        "created_at": row["created_at"],
    }
