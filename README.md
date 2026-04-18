# Presence Detection Phase 1

Flask-based phase-1 data collection server for ESP32 presence sensing experiments.

The goal is not final presence detection yet. Phase 1 collects clean time-series samples so a model can be built later for device-free presence detection from Wi-Fi disturbances. PIR is kept as a debugging and rough-labeling signal.

## What Phase 1 Does

- Receives ESP32 node samples over HTTP
- Tracks latest PIR and Wi-Fi RSSI values per node
- Keeps recent samples in memory for the dashboard
- Stores accepted samples in SQLite at `data/raw/sensor_samples.sqlite3`
- Appends accepted samples to `data/raw/sensor_samples.jsonl`
- Shows live PIR-derived presence and Wi-Fi RSSI trends

## What Phase 1 Does Not Do

- No model training
- No final occupancy inference
- No CSI processing
- No BLE tracking
- No Docker, Redis, message brokers, or background workers

## Run

Install Python 3, then from this folder:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py server.py
```

The server listens on `0.0.0.0:5000`, so an ESP32 on the same Wi-Fi network can post to your PC:

```text
http://YOUR_PC_IP_ADDRESS:5000/sensor
```

## Main Sensor Endpoint

Use `POST /sensor` for new ESP32 firmware.

PIR + Wi-Fi RSSI sample:

```json
{
  "node_id": "node_1",
  "timestamp_ms": 123456,
  "uptime_ms": 123456,
  "pir": 1,
  "wifi_rssi": -61
}
```

PIR-only sample:

```json
{
  "node_id": "node_1",
  "uptime_ms": 123456,
  "pir": 0
}
```

RSSI-only sample:

```json
{
  "node_id": "node_1",
  "uptime_ms": 123456,
  "wifi_rssi": -63
}
```

`pir` can be `1`, `0`, `true`, `false`, `"motion"`, or `"clear"`.

`node_id` is the canonical identifier. The server still accepts older `sensor`, `sensor_id`, or `device` fields as aliases.

Recommended ESP32 behavior:

- Send a sample every 300-500 ms.
- Use fixed ids: `node_1`, `node_2`, `node_3`.
- Read PIR from the configured GPIO pin.
- Send connected Wi-Fi RSSI with `WiFi.RSSI()`.
- Reconnect Wi-Fi if disconnected, then continue posting.
- Retry later if the server is temporarily unavailable.

## Backward Compatibility

The old `POST /pir` endpoint still works. It uses the same ingestion logic as `/sensor`.

Legacy payload:

```json
{
  "sensor": "node_1",
  "motion": 1,
  "uptime_ms": 123456,
  "rssi": -62
}
```

## Dashboard

Open:

```text
http://YOUR_PC_IP_ADDRESS:5000/
```

The dashboard shows:

- Current state per ESP32 node
- PIR-derived presence timeline
- Wi-Fi RSSI trend per ESP32
- Recent PIR events

## API

Raw status:

```text
GET /status
```

Recent raw samples:

```text
GET /samples
GET /samples?limit=100
GET /samples?node_id=node_1
```

Recent persisted samples from SQLite:

```text
GET /stored-samples
GET /stored-samples?limit=100
GET /stored-samples?node_id=node_1
```

Compatibility event endpoint:

```text
GET /events
```

Endpoint details:

```text
GET /api
```

## Repo Layout

```text
PresenceDetection/
  server.py
  storage.py
  requirements.txt
  templates/
  static/
  esp32/
    pir_sender/
    wifi_rssi_sender/
  data/
    raw/
    labeled/
```

## Next Milestones

1. Send PIR + Wi-Fi RSSI samples from one ESP32.
2. Add two more ESP32 boards.
3. Collect occupied and empty sessions.
4. Label sessions in `data/labeled/`.
5. Add feature extraction and a simple model after enough data exists.
