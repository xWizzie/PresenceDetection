import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path

from features import build_feature_rows, parse_received_at
from storage import (
    DEFAULT_DB_PATH,
    PROJECT_ROOT,
    fetch_samples,
    fetch_training_labels,
    init_storage,
)


DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "datasets" / "features.csv"

FIELDNAMES = [
    "node_id",
    "window_start",
    "window_end",
    "window_seconds",
    "sample_count",
    "rssi_count",
    "rssi_mean",
    "rssi_std",
    "rssi_min",
    "rssi_max",
    "rssi_delta",
    "pir_count",
    "pir_sum",
    "pir_any",
    "label",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build a sliding-window feature dataset from sensor_samples.sqlite3."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="SQLite database path.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="CSV output path.",
    )
    parser.add_argument(
        "--node-id",
        default=None,
        help="Optional node_id filter, for example node_1.",
    )
    parser.add_argument(
        "--window-seconds",
        type=float,
        default=5.0,
        help="Sliding window size in seconds.",
    )
    parser.add_argument(
        "--step-seconds",
        type=float,
        default=1.0,
        help="Sliding window step in seconds.",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=3,
        help="Minimum samples required in a window.",
    )
    parser.add_argument(
        "--time-field",
        choices=("received_at",),
        default="received_at",
        help="Time source used for windowing. Manual labels require received_at.",
    )
    return parser.parse_args()


def validate_args(args):
    if args.window_seconds <= 0:
        raise SystemExit("--window-seconds must be greater than 0")
    if args.step_seconds <= 0:
        raise SystemExit("--step-seconds must be greater than 0")
    if args.min_samples <= 0:
        raise SystemExit("--min-samples must be greater than 0")


def normalize_training_label(label):
    if label in ("empty", "occupied"):
        return label
    if label in ("still", "moving"):
        return "occupied"
    return None


def training_label_intervals(db_path):
    now_seconds = datetime.now(timezone.utc).timestamp()
    intervals = []

    for label in fetch_training_labels(db_path=db_path):
        start = parse_received_at(label["started_at"])
        end = parse_received_at(label["ended_at"]) if label["ended_at"] else now_seconds
        normalized_label = normalize_training_label(label["label"])

        if (
            start is None
            or end is None
            or end <= start
            or normalized_label is None
        ):
            continue

        intervals.append({
            "start": start,
            "end": end,
            "label": normalized_label,
        })

    return intervals


def apply_training_labels(rows, db_path):
    intervals = training_label_intervals(db_path)

    for row in rows:
        window_start = parse_received_at(row["window_start"])
        window_end = parse_received_at(row["window_end"])
        row["label"] = "unlabeled"

        if window_start is None or window_end is None:
            continue

        midpoint = (window_start + window_end) / 2

        for interval in intervals:
            if interval["start"] <= midpoint <= interval["end"]:
                row["label"] = interval["label"]
                break

    return rows


def write_csv(rows, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def main():
    args = parse_args()
    validate_args(args)

    init_storage(args.db)
    samples = fetch_samples(node_id=args.node_id, db_path=args.db)
    rows = build_feature_rows(
        samples=samples,
        window_seconds=args.window_seconds,
        step_seconds=args.step_seconds,
        min_samples=args.min_samples,
        time_field=args.time_field,
    )
    rows = apply_training_labels(rows, args.db)

    write_csv(rows, args.output)

    # print(f"Read samples: {len(samples)}")
    # print(f"Wrote rows: {len(rows)}")
    # print("Label source: manual training labels")
    # print("Unlabeled rows: " + str(sum(1 for row in rows if row["label"] == "unlabeled")))
    # print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
