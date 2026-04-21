# Presence Detection Phase 1

Flask-based phase-1 data collection server for ESP32 presence sensing experiments.

The goal is not final presence detection yet. Phase 1 collects clean time-series samples so a model can be built later for device-free presence detection from Wi-Fi disturbances. PIR is kept as a debugging signal and input feature, not as training ground truth.

## What Phase 1 Does

- Receives ESP32 node samples over HTTP
- Tracks latest PIR and Wi-Fi RSSI values per node
- Keeps recent samples in memory for the dashboard
- Stores a rolling live sample buffer in SQLite at `data/raw/sensor_samples.sqlite3`
- Shows live PIR-derived presence and Wi-Fi RSSI trends
- Provides a training-label page for manual room-state labels

## What Phase 1 Does Not Do

- No deep learning
- No final production-grade occupancy inference
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

On the current LAN, the dashboard URL should look like:

```text
http://192.168.1.9:5000/
```

If a phone cannot open it, check that the phone is on the same Wi-Fi network, not mobile data or a guest/client-isolated network. If the URL still does not load, allow Python through Windows Firewall for private networks, or add an inbound TCP rule for port `5000`.

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

Training labels page:

```text
http://YOUR_PC_IP_ADDRESS:5000/training
```

Use this page while collecting model data. The label buttons create time ranges in SQLite:

- `empty`: out of room
- `occupied`: in room, sitting or moving

Use the collection switch or `Pause labeling` when the current room state should not be used for training. Keep collection off while transitioning between states, such as walking into the room or standing up from sitting, then start the correct label once the state is stable.

## API

Raw status:

```text
GET /status
```

In `/status`, each sensor's `present` value is PIR-derived. It is `true` when that sensor has reported PIR motion within the current presence timeout, which defaults to 180 seconds. `home_present` is `true` if any sensor is currently `present`. This is only a phase-1 debugging signal, not final occupancy inference.

Adjust the presence timeout:

```text
GET /settings
POST /settings
```

`POST /settings` accepts `presence_timeout_seconds` from `5` to `3600`.

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

Training label state:

```text
GET /training-label
POST /training-label
```

`POST /training-label` accepts `empty`, `occupied`, or an empty label to pause.
Responses include `collecting: true` while a training label interval is open.

Compatibility event endpoint:

```text
GET /events
```

Endpoint details:

```text
GET /api
```

Live model state:

```text
GET /state
GET /state?window_seconds=5&min_samples=3
```

`/state` loads the trained model from `models/presence_model.pkl`, builds the latest RSSI feature window per node from SQLite, and returns a predicted state plus confidence when available. If no model has been trained yet, it returns a clear error instead of crashing.

## Storage Retention

The raw `sensor_samples` table is a rolling live buffer, not a permanent archive. It keeps enough data for the dashboard and live inference:

- dashboard max window: `60` minutes
- expected dashboard fetch rate: `12` samples per second
- stored sample cap: `50000`
- stored sample max age: `7200` seconds

Old unlabeled rows are pruned periodically after new sensor samples arrive. Manual training label intervals are stored separately in `training_labels`, and any sensor samples that fall inside a training label interval are protected from the live-sample retention rule.

## Build A Feature Dataset

After collecting raw ESP32 samples, build a CSV dataset from SQLite:

```powershell
py build_dataset.py
```

Default output:

```text
data/datasets/features.csv
```

The builder creates sliding windows per `node_id` using `received_at` and labels each window from the manual training intervals saved by `/training`.

Default settings:

- window size: `5` seconds
- step: `1` second
- minimum samples per window: `3`
- label: `occupied` if the window midpoint falls inside an `In room` interval
- label: `empty` if the window midpoint falls inside an `Out of room` interval
- label: `unlabeled` if the window midpoint is outside manual label intervals

PIR values are kept in the dataset as `pir_count`, `pir_sum`, and `pir_any` feature columns. PIR is never used to create the label.

Useful options:

```powershell
py build_dataset.py --node-id node_1
py build_dataset.py --window-seconds 3 --step-seconds 1
py build_dataset.py --output data/datasets/node_1_features.csv
```

Collect labels on `/training` before building the dataset. Windows outside labeled intervals stay `unlabeled` and are ignored by training.

CSV columns include:

```text
node_id, window_start, window_end, sample_count, rssi_mean, rssi_std, rssi_min, rssi_max, rssi_delta, pir_sum, pir_any, label
```

## Check Dataset Readiness

Before training, summarize the collected data and class balance:

```powershell
py summarize_dataset.py
```

Useful options:

```powershell
py summarize_dataset.py --node-id node_1
py summarize_dataset.py --window-seconds 3 --step-seconds 1
py summarize_dataset.py --dataset-csv data/datasets/features.csv
```

This reports raw sample counts, labeled interval coverage, training-ready window counts, class balance, per-node counts, and a simple readiness verdict for the first `occupied` vs `empty` baseline.

## Train The Baseline Model

Train a simple RandomForest baseline from the feature CSV:

```powershell
py train.py
```

Default model output:

```text
models/presence_model.pkl
```

Useful options:

```powershell
py train.py --input data/datasets/features.csv
py train.py --output models/presence_model.pkl
```

Training uses window, RSSI, and PIR feature columns and ignores `unlabeled` rows. The trained classes are binary occupancy labels: `empty` and `occupied`.

Label honesty:

- Manual labels are the only ground truth.
- `In room` maps to `occupied`.
- `Out of room` maps to `empty`.
- PIR is an input feature only; PIR inactivity is not proof of `empty`.
- Treat this as a first baseline classifier, not a reliable occupancy model yet.

Run live inference after training:

```powershell
py server.py
```

Then call:

```text
http://YOUR_PC_IP_ADDRESS:5000/state
```

## Repo Layout

```text
PresenceDetection/
  server.py
  storage.py
  features.py
  build_dataset.py
  summarize_dataset.py
  train.py
  model.py
  requirements.txt
  models/
  templates/
  static/
  esp32/
    pir_sender/
    wifi_rssi_sender/
  data/
    raw/
    datasets/
```

## Next Milestones

1. Send PIR + Wi-Fi RSSI samples from one ESP32.
2. Add two more ESP32 boards.
3. Collect occupied and empty sessions.
4. Build feature datasets with `build_dataset.py`.
5. Label sessions with the `/training` page.
6. Collect better `occupied` and `empty` labels for model quality.
