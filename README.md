# Presence Detection Phase 1

Flask-based phase-1 data collection server for ESP32 presence sensing experiments.

The goal is not final presence detection yet. Phase 1 collects clean time-series samples so a model can be built later for device-free presence detection from Wi-Fi disturbances. PIR is kept as a debugging and rough-labeling signal.

## What Phase 1 Does

- Receives ESP32 sensor samples over HTTP
- Tracks latest PIR and Wi-Fi RSSI values per sensor
- Keeps recent samples in memory for the dashboard
- Appends accepted samples to `data/raw/sensor_samples.jsonl`
- Shows live PIR-derived presence and Wi-Fi RSSI trends

## What Phase 1 Does Not Do

- No model training
- No final occupancy inference
- No CSI processing
- No BLE tracking
- No database, Docker, Redis, or background workers

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
  "sensor": "living-room-1",
  "timestamp_ms": 123456,
  "uptime_ms": 123456,
  "pir": 1,
  "wifi_rssi": -61
}
```

PIR-only sample:

```json
{
  "sensor": "living-room-1",
  "uptime_ms": 123456,
  "pir": 0
}
```

RSSI-only sample:

```json
{
  "sensor": "living-room-1",
  "uptime_ms": 123456,
  "wifi_rssi": -63
}
```

`pir` can be `1`, `0`, `true`, `false`, `"motion"`, or `"clear"`.

## Backward Compatibility

The old `POST /pir` endpoint still works. It uses the same ingestion logic as `/sensor`.

Legacy payload:

```json
{
  "sensor": "living-room-1",
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

- Current state per ESP32
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
GET /samples?sensor=living-room-1
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
