from datetime import datetime, timezone
from statistics import mean, pstdev


def parse_received_at(value):
    if not value:
        return None

    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return None


def sample_time_seconds(sample, time_field="received_at"):
    if time_field == "timestamp_ms":
        timestamp_ms = sample.get("timestamp_ms")
        if timestamp_ms is None:
            return None
        return timestamp_ms / 1000

    return parse_received_at(
        sample.get("received_at")
        or sample.get("server_received_at")
        or sample.get("timestamp")
    )


def format_window_time(seconds, time_field="received_at"):
    if time_field == "timestamp_ms":
        return int(round(seconds * 1000))

    return (
        datetime.fromtimestamp(seconds, timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def grouped_by_node(samples):
    grouped = {}
    for sample in samples:
        node_id = sample.get("node_id")
        if not node_id:
            continue
        grouped.setdefault(node_id, []).append(sample)
    return grouped


def build_feature_rows(
    samples,
    window_seconds=5.0,
    step_seconds=1.0,
    min_samples=3,
    time_field="received_at",
    empty_label="empty",
):
    rows = []

    for node_id, node_samples in grouped_by_node(samples).items():
        timed_samples = with_sample_times(node_samples, time_field)
        rows.extend(build_node_feature_rows(
            node_id=node_id,
            samples=timed_samples,
            window_seconds=window_seconds,
            step_seconds=step_seconds,
            min_samples=min_samples,
            time_field=time_field,
            empty_label=empty_label,
        ))

    return rows


def with_sample_times(samples, time_field):
    timed_samples = []

    for sample in samples:
        sample_time = sample_time_seconds(sample, time_field=time_field)
        if sample_time is None:
            continue

        timed_sample = dict(sample)
        timed_sample["_time_seconds"] = sample_time
        timed_samples.append(timed_sample)

    return sorted(timed_samples, key=lambda sample: sample["_time_seconds"])


def build_node_feature_rows(
    node_id,
    samples,
    window_seconds,
    step_seconds,
    min_samples,
    time_field,
    empty_label,
):
    if not samples:
        return []

    first_time = samples[0]["_time_seconds"]
    last_time = samples[-1]["_time_seconds"]
    rows = []
    window_start = first_time

    while window_start + window_seconds <= last_time:
        window_end = window_start + window_seconds
        window_samples = [
            sample
            for sample in samples
            if window_start <= sample["_time_seconds"] < window_end
        ]

        features = extract_window_features(
            node_id=node_id,
            window_start=window_start,
            window_end=window_end,
            samples=window_samples,
            min_samples=min_samples,
            time_field=time_field,
            empty_label=empty_label,
        )
        if features:
            rows.append(features)

        window_start += step_seconds

    return rows


def extract_window_features(
    node_id,
    window_start,
    window_end,
    samples,
    min_samples,
    time_field,
    empty_label,
):
    if len(samples) < min_samples:
        return None

    rssi_values = [
        sample["wifi_rssi"]
        for sample in samples
        if sample.get("wifi_rssi") is not None
    ]
    if not rssi_values:
        return None

    pir_values = [
        bool(sample["pir"])
        for sample in samples
        if sample.get("pir") is not None
    ]
    pir_sum = sum(1 for value in pir_values if value)
    pir_any = 1 if pir_sum else 0

    return {
        "node_id": node_id,
        "window_start": format_window_time(window_start, time_field),
        "window_end": format_window_time(window_end, time_field),
        "window_seconds": round(window_end - window_start, 3),
        "sample_count": len(samples),
        "rssi_count": len(rssi_values),
        "rssi_mean": round(mean(rssi_values), 4),
        "rssi_std": round(pstdev(rssi_values), 4) if len(rssi_values) > 1 else 0.0,
        "rssi_min": min(rssi_values),
        "rssi_max": max(rssi_values),
        "rssi_delta": rssi_values[-1] - rssi_values[0],
        "pir_count": len(pir_values),
        "pir_sum": pir_sum,
        "pir_any": pir_any,
        "label": "moving" if pir_any else empty_label,
    }
