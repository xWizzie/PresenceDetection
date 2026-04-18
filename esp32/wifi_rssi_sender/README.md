# PIR + Wi-Fi RSSI Sender

ESP32 sketch folder for the phase-1 combined sender.

Post combined samples to:

```text
POST http://YOUR_PC_IP_ADDRESS:5000/sensor
```

Payload:

```json
{
  "node_id": "node_1",
  "timestamp_ms": 123456,
  "uptime_ms": 123456,
  "pir": 1,
  "wifi_rssi": -61
}
```

Firmware expectations:

- Use fixed ids: `node_1`, `node_2`, `node_3`.
- Send every 300-500 ms.
- Read PIR from the configured GPIO pin.
- Read connected Wi-Fi RSSI with `WiFi.RSSI()`.
- Keep posting RSSI even when PIR is `0`.
- Reconnect Wi-Fi if disconnected.
- Retry later if the server is temporarily unavailable.
