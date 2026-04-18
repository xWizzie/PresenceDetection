import json
from datetime import datetime, timedelta, timezone
from threading import Lock

from flask import Flask, jsonify, render_template, request

from storage import (
    DEFAULT_DB_PATH,
    PROJECT_ROOT,
    count_samples,
    fetch_recent_samples,
    init_storage,
    insert_sensor_sample,
)

app = Flask(__name__)

PRESENCE_TIMEOUT_SECONDS = 30
EXPECTED_NODES = ("node_1", "node_2", "node_3")
EVENT_HISTORY_LIMIT = 1000
STATUS_HISTORY_LIMIT = 60
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
RAW_SAMPLE_LOG = RAW_DATA_DIR / "sensor_samples.jsonl"

sensor_state = {}
last_pir_motion_time = {}
sensor_events = []
samples_by_sensor = {}
lock = Lock()

init_storage()


def utc_now():
    return datetime.now(timezone.utc)


def format_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def parse_binary_signal(value):
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, int) and value in (0, 1):
        return value == 1

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("1", "true", "yes", "on", "motion", "detected"):
            return True
        if normalized in ("0", "false", "no", "off", "clear", "none"):
            return False

    return None


def parse_optional_number(value):
    if value is None or value == "":
        return None

    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None

    if parsed.is_integer():
        return int(parsed)
    return parsed


def parse_number_field(data, field_name, min_value=None):
    if field_name not in data or data[field_name] == "":
        return None, None

    parsed = parse_optional_number(data[field_name])
    if parsed is None:
        return None, f"{field_name} must be a number"

    if min_value is not None and parsed < min_value:
        return None, f"{field_name} must be at least {min_value}"

    return parsed, None


def parse_rssi_field(data):
    if "wifi_rssi" in data:
        field_name = "wifi_rssi"
    elif "rssi" in data:
        field_name = "rssi"
    else:
        return None, None, False

    parsed, error = parse_number_field(data, field_name)
    if parsed is not None and not isinstance(parsed, int):
        return None, f"{field_name} must be an integer", True

    return parsed, error, True


def is_present(sensor_name: str) -> bool:
    last_seen = last_pir_motion_time.get(sensor_name)
    if last_seen is None:
        return False
    return utc_now() - last_seen < timedelta(seconds=PRESENCE_TIMEOUT_SECONDS)


def append_raw_sample(sample):
    try:
        RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
        with RAW_SAMPLE_LOG.open("a", encoding="utf-8") as file:
            file.write(json.dumps(sample, separators=(",", ":")) + "\n")
    except Exception as error:
        print(f"Warning: could not append JSONL sample: {error}")


def normalize_sensor_payload(data, source_endpoint):
    node_id = str(
        data.get("node_id")
        or data.get("sensor")
        or data.get("sensor_id")
        or data.get("device")
        or ""
    ).strip()

    has_pir = "pir" in data
    has_motion = "motion" in data
    uptime_ms, uptime_error = parse_number_field(data, "uptime_ms", min_value=0)
    timestamp_ms, timestamp_error = parse_number_field(
        data,
        "timestamp_ms",
        min_value=0,
    )
    wifi_rssi, rssi_error, has_wifi_rssi = parse_rssi_field(data)

    pir_value = data.get("pir")
    if not has_pir:
        pir_value = data.get("motion")

    pir = parse_binary_signal(pir_value)

    return {
        "node_id": node_id,
        "sensor": node_id,
        "pir": pir,
        "wifi_rssi": wifi_rssi,
        "uptime_ms": uptime_ms,
        "timestamp_ms": timestamp_ms,
        "source_endpoint": source_endpoint,
        "has_pir_signal": has_pir or has_motion,
        "has_wifi_rssi": has_wifi_rssi,
        "validation_errors": [
            error
            for error in (uptime_error, timestamp_error, rssi_error)
            if error
        ],
    }


def append_sample_to_memory(event):
    sensor_events.append(event)
    del sensor_events[:-EVENT_HISTORY_LIMIT]

    sensor_samples = samples_by_sensor.setdefault(event["sensor"], [])
    sensor_samples.append(event)
    del sensor_samples[:-EVENT_HISTORY_LIMIT]


def summarize_sensor_history(sensor):
    samples = samples_by_sensor.get(sensor, [])
    recent = samples[-STATUS_HISTORY_LIMIT:]
    rssi_values = [
        sample["wifi_rssi"]
        for sample in recent
        if sample.get("wifi_rssi") is not None
    ]
    pir_samples = [
        sample
        for sample in recent
        if sample.get("pir") is not None
    ]

    return {
        "stored_samples": len(samples),
        "summary_window_samples": len(recent),
        "pir_samples": len(pir_samples),
        "pir_motion_samples": sum(1 for sample in pir_samples if sample["pir"]),
        "wifi_rssi_samples": len(rssi_values),
        "wifi_rssi_avg": (
            round(sum(rssi_values) / len(rssi_values), 2)
            if rssi_values
            else None
        ),
        "wifi_rssi_min": min(rssi_values) if rssi_values else None,
        "wifi_rssi_max": max(rssi_values) if rssi_values else None,
    }


def ingest_sensor_sample(data, source_endpoint):
    if not data:
        return {"ok": False, "error": "Invalid or missing JSON"}, 400

    if not isinstance(data, dict):
        return {"ok": False, "error": "JSON payload must be an object"}, 400

    sample = normalize_sensor_payload(data, source_endpoint)
    node_id = sample["node_id"]
    sensor = sample["sensor"]
    pir = sample["pir"]

    if not node_id:
        return {"ok": False, "error": "Missing node_id"}, 400

    if sample["validation_errors"]:
        return {
            "ok": False,
            "error": "; ".join(sample["validation_errors"]),
        }, 400

    if sample["has_pir_signal"] and pir is None:
        return {
            "ok": False,
            "error": "pir/motion must be true/false, 1/0, or motion/clear",
        }, 400

    if sample["has_wifi_rssi"] and sample["wifi_rssi"] is None:
        return {
            "ok": False,
            "error": "wifi_rssi/rssi must be a number",
        }, 400

    if pir is None and sample["wifi_rssi"] is None:
        return {
            "ok": False,
            "error": "Send at least one signal: pir/motion or wifi_rssi/rssi",
        }, 400

    now = utc_now()
    received_at = format_timestamp(now)
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)

    event = {
        "timestamp": received_at,
        "server_received_at": received_at,
        "node_id": node_id,
        "sensor": sensor,
        "pir": pir,
        "motion": pir,
        "present": False,
        "uptime_ms": sample["uptime_ms"],
        "timestamp_ms": sample["timestamp_ms"],
        "wifi_rssi": sample["wifi_rssi"],
        "rssi": sample["wifi_rssi"],
        "ip": ip,
        "source_endpoint": source_endpoint,
    }

    with lock:
        previous_state = sensor_state.get(sensor, {})
        next_state = {
            "pir": previous_state.get("pir"),
            "motion": previous_state.get("motion"),
            "uptime_ms": sample["uptime_ms"],
            "timestamp_ms": sample["timestamp_ms"],
            "wifi_rssi": previous_state.get("wifi_rssi"),
            "rssi": previous_state.get("rssi"),
            "ip": ip,
            "received_at": received_at,
        }

        if pir is not None:
            next_state["pir"] = pir
            next_state["motion"] = pir

        if sample["wifi_rssi"] is not None:
            next_state["wifi_rssi"] = sample["wifi_rssi"]
            next_state["rssi"] = sample["wifi_rssi"]

        sensor_state[sensor] = next_state

        if pir:
            last_pir_motion_time[sensor] = now

        present = is_present(sensor)
        home_present = any(is_present(name) for name in sensor_state)
        event["present"] = present

        sample_id = insert_sensor_sample(event)
        event["sample_id"] = sample_id
        append_sample_to_memory(event)
        append_raw_sample(event)

    print(
        f"[{received_at}] sensor={sensor} pir={pir} "
        f"wifi_rssi={sample['wifi_rssi']} uptime_ms={sample['uptime_ms']} "
        f"present={present} home_present={home_present}"
    )

    return {
        "ok": True,
        "node_id": node_id,
        "sensor": sensor,
        "pir": pir,
        "motion": pir,
        "wifi_rssi": sample["wifi_rssi"],
        "present": present,
        "home_present": home_present,
        "presence_timeout_seconds": PRESENCE_TIMEOUT_SECONDS,
        "sample_id": sample_id,
    }, 200


def build_sensor_status(sensor: str, now: datetime):
    state = sensor_state.get(sensor)
    last_motion = last_pir_motion_time.get(sensor)

    return {
        "node_id": sensor,
        "seen": state is not None,
        "pir": state["pir"] if state else None,
        "motion": state["motion"] if state else None,
        "present": is_present(sensor),
        "last_reported_at": state["received_at"] if state else None,
        "last_pir_motion_at": format_timestamp(last_motion) if last_motion else None,
        "last_motion_at": format_timestamp(last_motion) if last_motion else None,
        "seconds_since_last_motion": (
            round((now - last_motion).total_seconds(), 3)
            if last_motion
            else None
        ),
        "uptime_ms": state.get("uptime_ms") if state else None,
        "timestamp_ms": state.get("timestamp_ms") if state else None,
        "wifi_rssi": state.get("wifi_rssi") if state else None,
        "rssi": state.get("rssi") if state else None,
        "ip": state.get("ip") if state else None,
        "history": summarize_sensor_history(sensor),
    }


def build_status_payload(now: datetime):
    sensor_names = sorted(set(EXPECTED_NODES) | set(sensor_state))
    sensors = {
        sensor: build_sensor_status(sensor, now)
        for sensor in sensor_names
    }

    return {
        "ok": True,
        "home_present": any(sensor["present"] for sensor in sensors.values()),
        "presence_timeout_seconds": PRESENCE_TIMEOUT_SECONDS,
        "server_time": format_timestamp(now),
        "sensors": sensors,
        "nodes": sensors,
        "sample_history_limit": EVENT_HISTORY_LIMIT,
    }


@app.route("/", methods=["GET"])
def home():
    return render_template("dashboard.html")


@app.route("/sensor", methods=["POST"])
def sensor_ingest():
    payload, status_code = ingest_sensor_sample(
        request.get_json(silent=True),
        source_endpoint="/sensor",
    )
    return jsonify(payload), status_code


@app.route("/sensor", methods=["GET"])
def sensor_help():
    return jsonify({
        "ok": True,
        "method": "POST",
        "example_json": {
            "node_id": "node_1",
            "timestamp_ms": 123456,
            "uptime_ms": 123456,
            "pir": 1,
            "wifi_rssi": -61,
        },
    }), 200


@app.route("/pir", methods=["POST"])
def pir():
    payload, status_code = ingest_sensor_sample(
        request.get_json(silent=True),
        source_endpoint="/pir",
    )
    return jsonify(payload), status_code


@app.route("/pir", methods=["GET"])
def pir_help():
    return jsonify({
        "ok": True,
        "message": "Legacy PIR endpoint. Prefer POST /sensor.",
        "method": "POST",
        "example_json": {
            "node_id": "node_1",
            "motion": 1,
            "uptime_ms": 123456,
            "rssi": -62,
        },
    }), 200


@app.route("/status", methods=["GET"])
def status():
    now = utc_now()

    with lock:
        payload = build_status_payload(now)

    return jsonify(payload), 200


@app.route("/events", methods=["GET"])
def events():
    payload, status_code = recent_samples_payload(response_key="events")
    return jsonify(payload), status_code


@app.route("/samples", methods=["GET"])
def samples():
    payload, status_code = recent_samples_payload(response_key="samples")
    return jsonify(payload), status_code


@app.route("/stored-samples", methods=["GET"])
def stored_samples():
    payload, status_code = stored_samples_payload()
    return jsonify(payload), status_code


def recent_samples_payload(response_key):
    try:
        limit = int(request.args.get("limit", "300"))
    except ValueError:
        return {"ok": False, "error": "limit must be an integer"}, 400

    limit = max(1, min(limit, EVENT_HISTORY_LIMIT))
    sensor_filter = request.args.get("node_id") or request.args.get("sensor")

    with lock:
        if sensor_filter:
            matching_samples = samples_by_sensor.get(sensor_filter, [])
        else:
            matching_samples = sensor_events

        samples_slice = matching_samples[-limit:]
        total_stored = len(sensor_events)

    payload = {
        "ok": True,
        response_key: samples_slice,
        "limit": limit,
        "node_id": sensor_filter,
        "sensor": sensor_filter,
        "total_stored": total_stored,
    }

    if response_key != "samples":
        payload["samples"] = samples_slice
    if response_key != "events":
        payload["events"] = samples_slice

    return payload, 200


def stored_samples_payload():
    try:
        limit = int(request.args.get("limit", "300"))
    except ValueError:
        return {"ok": False, "error": "limit must be an integer"}, 400

    limit = max(1, min(limit, EVENT_HISTORY_LIMIT))
    node_id = request.args.get("node_id") or request.args.get("sensor")

    return {
        "ok": True,
        "samples": fetch_recent_samples(limit=limit, node_id=node_id),
        "limit": limit,
        "node_id": node_id,
        "sensor": node_id,
        "total_stored": count_samples(),
        "filtered_total": count_samples(node_id=node_id) if node_id else None,
        "storage": {
            "type": "sqlite",
            "path": str(DEFAULT_DB_PATH),
        },
    }, 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True}), 200


@app.route("/api", methods=["GET"])
def api_info():
    return jsonify({
        "ok": True,
        "message": "Presence sensing server is running",
        "endpoints": {
            "dashboard": "/",
            "post_sensor": "/sensor",
            "legacy_post_pir": "/pir",
            "samples": "/samples",
            "stored_samples": "/stored-samples",
            "events": "/events",
            "status": "/status",
            "health": "/health",
        },
        "example_post": {
            "node_id": "node_1",
            "timestamp_ms": 123456,
            "uptime_ms": 123456,
            "pir": 1,
            "wifi_rssi": -61,
        },
        "accepted_id_fields": ["node_id", "sensor", "sensor_id", "device"],
    }), 200


if __name__ == "__main__":
    print("Starting presence sensing server on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
