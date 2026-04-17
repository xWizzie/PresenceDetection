import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

PRESENCE_TIMEOUT_SECONDS = 30
EXPECTED_SENSORS = ("living-room-1", "living-room-2", "living-room-3")
EVENT_HISTORY_LIMIT = 1000
RAW_DATA_DIR = Path("data/raw")
RAW_SAMPLE_LOG = RAW_DATA_DIR / "sensor_samples.jsonl"

sensor_state = {}
last_pir_motion_time = {}
sensor_events = []
lock = Lock()


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


def is_present(sensor_name: str) -> bool:
    last_seen = last_pir_motion_time.get(sensor_name)
    if last_seen is None:
        return False
    return utc_now() - last_seen < timedelta(seconds=PRESENCE_TIMEOUT_SECONDS)


def append_raw_sample(sample):
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with RAW_SAMPLE_LOG.open("a", encoding="utf-8") as file:
        file.write(json.dumps(sample, separators=(",", ":")) + "\n")


def normalize_sensor_payload(data, source_endpoint):
    sensor = str(
        data.get("sensor")
        or data.get("sensor_id")
        or data.get("device")
        or ""
    ).strip()

    pir_value = data.get("pir")
    if pir_value is None:
        pir_value = data.get("motion")

    pir = parse_binary_signal(pir_value)
    wifi_rssi = parse_optional_number(
        data.get("wifi_rssi")
        if data.get("wifi_rssi") is not None
        else data.get("rssi")
    )

    return {
        "sensor": sensor,
        "pir": pir,
        "wifi_rssi": wifi_rssi,
        "uptime_ms": parse_optional_number(data.get("uptime_ms")),
        "timestamp_ms": parse_optional_number(data.get("timestamp_ms")),
        "source_endpoint": source_endpoint,
    }


def ingest_sensor_sample(data, source_endpoint):
    if not data:
        return {"ok": False, "error": "Invalid or missing JSON"}, 400

    sample = normalize_sensor_payload(data, source_endpoint)
    sensor = sample["sensor"]
    pir = sample["pir"]

    if not sensor:
        return {"ok": False, "error": "Missing sensor name"}, 400

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
        sensor_state[sensor] = {
            "pir": pir,
            "motion": pir,
            "uptime_ms": sample["uptime_ms"],
            "timestamp_ms": sample["timestamp_ms"],
            "wifi_rssi": sample["wifi_rssi"],
            "rssi": sample["wifi_rssi"],
            "ip": ip,
            "received_at": received_at,
        }

        if pir:
            last_pir_motion_time[sensor] = now

        present = is_present(sensor)
        home_present = any(is_present(name) for name in sensor_state)
        event["present"] = present

        sensor_events.append(event)
        del sensor_events[:-EVENT_HISTORY_LIMIT]
        append_raw_sample(event)

    print(
        f"[{received_at}] sensor={sensor} pir={pir} "
        f"wifi_rssi={sample['wifi_rssi']} uptime_ms={sample['uptime_ms']} "
        f"present={present} home_present={home_present}"
    )

    return {
        "ok": True,
        "sensor": sensor,
        "pir": pir,
        "motion": pir,
        "wifi_rssi": sample["wifi_rssi"],
        "present": present,
        "home_present": home_present,
        "presence_timeout_seconds": PRESENCE_TIMEOUT_SECONDS,
    }, 200


def build_sensor_status(sensor: str, now: datetime):
    state = sensor_state.get(sensor)
    last_motion = last_pir_motion_time.get(sensor)

    return {
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
    }


def build_status_payload(now: datetime):
    sensor_names = sorted(set(EXPECTED_SENSORS) | set(sensor_state))
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
            "sensor": "living-room-1",
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
            "sensor": "living-room-1",
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
    try:
        limit = int(request.args.get("limit", "300"))
    except ValueError:
        limit = 300

    limit = max(1, min(limit, EVENT_HISTORY_LIMIT))

    with lock:
        events_slice = sensor_events[-limit:]
        total_stored = len(sensor_events)

    return jsonify({
        "ok": True,
        "events": events_slice,
        "limit": limit,
        "total_stored": total_stored,
    }), 200


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
            "events": "/events",
            "status": "/status",
            "health": "/health",
        },
        "example_post": {
            "sensor": "living-room-1",
            "timestamp_ms": 123456,
            "uptime_ms": 123456,
            "pir": 1,
            "wifi_rssi": -61,
        },
    }), 200


if __name__ == "__main__":
    print("Starting presence sensing server on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
