from datetime import datetime, timedelta, timezone
from threading import Lock

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

PRESENCE_TIMEOUT_SECONDS = 30
EXPECTED_SENSORS = ("esp32-pir-1", "esp32-pir-2", "esp32-pir-3")
EVENT_HISTORY_LIMIT = 1000

sensor_state = {}
last_motion_time = {}
motion_events = []
lock = Lock()


def utc_now():
    return datetime.now(timezone.utc)


def format_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def parse_motion(value):
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


def is_present(sensor_name: str) -> bool:
    last_seen = last_motion_time.get(sensor_name)
    if last_seen is None:
        return False
    return utc_now() - last_seen < timedelta(seconds=PRESENCE_TIMEOUT_SECONDS)


def build_sensor_status(sensor: str, now: datetime):
    state = sensor_state.get(sensor)
    last_motion = last_motion_time.get(sensor)

    return {
        "seen": state is not None,
        "motion": state["motion"] if state else False,
        "present": is_present(sensor),
        "last_reported_at": state["received_at"] if state else None,
        "last_motion_at": format_timestamp(last_motion) if last_motion else None,
        "seconds_since_last_motion": (
            round((now - last_motion).total_seconds(), 3)
            if last_motion
            else None
        ),
        "uptime_ms": state.get("uptime_ms") if state else None,
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


@app.route("/pir", methods=["POST"])
def pir():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"ok": False, "error": "Invalid or missing JSON"}), 400

    sensor = str(
        data.get("sensor")
        or data.get("sensor_id")
        or data.get("device")
        or ""
    ).strip()
    motion = parse_motion(data.get("motion"))
    uptime_ms = data.get("uptime_ms")
    rssi = data.get("rssi")
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)

    if not sensor:
        return jsonify({"ok": False, "error": "Missing sensor name"}), 400

    if motion is None:
        return jsonify({
            "ok": False,
            "error": "motion must be true/false, 1/0, or motion/clear",
        }), 400

    now = utc_now()
    received_at = format_timestamp(now)

    with lock:
        sensor_state[sensor] = {
            "motion": motion,
            "uptime_ms": uptime_ms,
            "rssi": rssi,
            "ip": ip,
            "received_at": received_at,
        }

        if motion:
            last_motion_time[sensor] = now

        present = is_present(sensor)
        home_present = any(is_present(name) for name in sensor_state)
        motion_events.append({
            "timestamp": received_at,
            "sensor": sensor,
            "motion": motion,
            "present": present,
            "uptime_ms": uptime_ms,
            "rssi": rssi,
            "ip": ip,
        })
        del motion_events[:-EVENT_HISTORY_LIMIT]

    print(
        f"[{received_at}] sensor={sensor} motion={int(motion)} "
        f"uptime_ms={uptime_ms} rssi={rssi} present={present} "
        f"home_present={home_present}"
    )

    return jsonify({
        "ok": True,
        "sensor": sensor,
        "motion": motion,
        "present": present,
        "home_present": home_present,
        "presence_timeout_seconds": PRESENCE_TIMEOUT_SECONDS,
    }), 200


@app.route("/pir", methods=["GET"])
def pir_help():
    return jsonify({
        "ok": True,
        "method": "POST",
        "example_json": {
            "sensor": "esp32-pir-1",
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
        events_slice = motion_events[-limit:]
        total_stored = len(motion_events)

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
        "message": "PIR server is running",
        "endpoints": {
            "dashboard": "/",
            "post_pir": "/pir",
            "events": "/events",
            "status": "/status",
            "health": "/health",
        },
        "example_post": {
            "sensor": "esp32-pir-1",
            "motion": 1,
            "uptime_ms": 123456,
            "rssi": -62,
        },
    }), 200


if __name__ == "__main__":
    print("Starting PIR server on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
