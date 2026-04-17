# PIR Sender

ESP32 sketch folder for the phase-1 PIR signal sender.

Post PIR-only updates to the compatibility endpoint:

```text
POST http://YOUR_PC_IP_ADDRESS:5000/pir
```

Prefer moving new firmware to `POST /sensor` once Wi-Fi RSSI is included.
