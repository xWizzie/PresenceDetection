# Wi-Fi RSSI Sender

ESP32 sketch folder for the phase-1 PIR + Wi-Fi RSSI sender.

Post combined samples to:

```text
POST http://YOUR_PC_IP_ADDRESS:5000/sensor
```

Payload:

```json
{
  "sensor": "living-room-1",
  "timestamp_ms": 123456,
  "uptime_ms": 123456,
  "pir": 1,
  "wifi_rssi": -61
}
```
