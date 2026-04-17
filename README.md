# Presence Detection PIR Server

Small Flask server for receiving PIR motion updates from ESP32 boards.

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
http://YOUR_PC_IP_ADDRESS:5000/pir
```

## ESP32 JSON Payload

Send a `POST` request with JSON:

```json
{
  "sensor": "esp32-pir-1",
  "motion": 1,
  "uptime_ms": 123456,
  "rssi": -62
}
```

`motion` can be `1`, `0`, `true`, `false`, `"motion"`, or `"clear"`.

## Web Dashboard

Open this in a browser:

```text
http://YOUR_PC_IP_ADDRESS:5000/
```

The dashboard graphs recent motion events, shows the current state of each ESP32, and updates live.

## API Status

For raw JSON status:

```text
http://YOUR_PC_IP_ADDRESS:5000/status
```

For recent motion events:

```text
http://YOUR_PC_IP_ADDRESS:5000/events
```
