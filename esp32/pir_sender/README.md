# PIR Sender

ESP32 sketch folder for the phase-1 PIR-only sender.

This is the compatibility path. It is useful while testing one HC-SR501 sensor before the combined PIR + Wi-Fi RSSI sender is ready.

Post PIR-only updates to:

```text
POST http://YOUR_PC_IP_ADDRESS:5000/pir
```

Payload:

```json
{
  "node_id": "node_1",
  "timestamp_ms": 123456,
  "uptime_ms": 123456,
  "pir": 1
}
```

Firmware expectations:

- Use a fixed `node_id`, starting with `node_1`.
- Send every 300-500 ms.
- Include `timestamp_ms` and `uptime_ms` from `millis()`.
- Send `pir` as `0` or `1`.
- Reconnect Wi-Fi if disconnected.
- Prefer `POST /sensor` once Wi-Fi RSSI is included.
