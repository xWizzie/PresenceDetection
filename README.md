# Presence Detection Sensor Server

Small Flask server for receiving phase-1 presence sensing samples from ESP32 boards.

Phase 1 is:

- ESP32 boards send PIR state and Wi-Fi RSSI samples
- The PC receives and stores raw samples
- The dashboard shows live sensor state
- No model training yet

## Run

Install Python 3, then from this folder:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py server.py
```

The server listens on `0.0.0.0:5000`, so an ESP32 on the same Wi-Fi network can post to:

```text
http://YOUR_PC_IP_ADDRESS:5000/sensor
```

## ESP32 JSON Payload

Send a `POST` request with JSON:

```json
{
  "sensor": "living-room-1",
  "timestamp_ms": 123456,
  "uptime_ms": 123456,
  "pir": 1,
  "wifi_rssi": -61
}
```

`pir` can be `1`, `0`, `true`, `false`, `"motion"`, or `"clear"`.

The old `POST /pir` endpoint still works for PIR-only sketches, but new code should use `POST /sensor`.

## Web Dashboard

Open this in a browser:

```text
http://YOUR_PC_IP_ADDRESS:5000/
```

The dashboard graphs recent PIR-derived presence, shows Wi-Fi RSSI per ESP32, and updates live.

Raw samples are appended to:

```text
data/raw/sensor_samples.jsonl
```

## API Status

For raw JSON status:

```text
http://YOUR_PC_IP_ADDRESS:5000/status
```

For recent motion events:

```text
http://YOUR_PC_IP_ADDRESS:5000/events
```

For endpoint details:

```text
http://YOUR_PC_IP_ADDRESS:5000/api
```
