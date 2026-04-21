import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

from build_dataset import apply_training_labels
from features import build_feature_rows, parse_received_at
from storage import DEFAULT_DB_PATH, fetch_samples, fetch_training_labels, init_storage


LABELS = ("empty", "occupied", "unlabeled")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Summarize collected occupancy data and judge baseline training readiness."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="SQLite database path.",
    )
    parser.add_argument(
        "--dataset-csv",
        type=Path,
        default=None,
        help=(
            "Optional existing dataset CSV to summarize. "
            "If omitted, rows are built from SQLite using the current feature logic."
        ),
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
        help="Sliding window size in seconds when building rows from SQLite.",
    )
    parser.add_argument(
        "--step-seconds",
        type=float,
        default=1.0,
        help="Sliding window step in seconds when building rows from SQLite.",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=3,
        help="Minimum samples required in a window.",
    )
    return parser.parse_args()


def validate_args(args):
    if args.window_seconds <= 0:
        raise SystemExit("--window-seconds must be greater than 0")
    if args.step_seconds <= 0:
        raise SystemExit("--step-seconds must be greater than 0")
    if args.min_samples <= 0:
        raise SystemExit("--min-samples must be greater than 0")


def load_raw_samples(db_path, node_id=None):
    init_storage(db_path)
    return fetch_samples(node_id=node_id, db_path=db_path)


def load_dataset_rows(args):
    if args.dataset_csv:
        return read_dataset_csv(args.dataset_csv), "csv"

    samples = load_raw_samples(args.db, node_id=args.node_id)
    rows = build_feature_rows(
        samples=samples,
        window_seconds=args.window_seconds,
        step_seconds=args.step_seconds,
        min_samples=args.min_samples,
        time_field="received_at",
    )
    return apply_training_labels(rows, args.db), "generated"


def read_dataset_csv(csv_path):
    if not csv_path.exists():
        raise SystemExit(f"Dataset CSV not found: {csv_path}")

    with csv_path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def summarize_raw_samples(samples):
    per_node = Counter(sample["node_id"] for sample in samples if sample.get("node_id"))
    times = [
        parse_received_at(sample.get("received_at"))
        for sample in samples
        if parse_received_at(sample.get("received_at")) is not None
    ]

    return {
        "total": len(samples),
        "per_node": per_node,
        "start": min(times) if times else None,
        "end": max(times) if times else None,
        "duration_seconds": (max(times) - min(times)) if len(times) >= 2 else 0,
    }


def summarize_intervals(db_path):
    intervals = []
    sessions_by_label = Counter()
    duration_by_label = Counter()

    for label in fetch_training_labels(db_path=db_path):
        normalized = label["label"]
        if normalized not in ("empty", "occupied"):
            continue

        start = parse_received_at(label["started_at"])
        end = parse_received_at(label["ended_at"]) if label["ended_at"] else None
        if start is None or end is None or end <= start:
            continue

        duration = end - start
        intervals.append({
            "label": normalized,
            "start": start,
            "end": end,
            "duration_seconds": duration,
        })
        sessions_by_label[normalized] += 1
        duration_by_label[normalized] += duration

    return {
        "total_sessions": len(intervals),
        "sessions_by_label": sessions_by_label,
        "duration_by_label": duration_by_label,
    }


def summarize_dataset_rows(rows):
    label_counts = Counter()
    per_node = defaultdict(Counter)

    for row in rows:
        label = (row.get("label") or "unlabeled").strip() or "unlabeled"
        node_id = row.get("node_id") or "<unknown>"
        label_counts[label] += 1
        per_node[node_id][label] += 1

    for label in LABELS:
        label_counts.setdefault(label, 0)

    training_ready = label_counts["empty"] + label_counts["occupied"]
    return {
        "total_rows": len(rows),
        "training_ready_rows": training_ready,
        "label_counts": label_counts,
        "per_node": dict(per_node),
    }


def readiness_verdict(dataset_summary):
    empty_rows = dataset_summary["label_counts"]["empty"]
    occupied_rows = dataset_summary["label_counts"]["occupied"]
    unlabeled_rows = dataset_summary["label_counts"]["unlabeled"]
    labeled_rows = empty_rows + occupied_rows
    notes = []

    if labeled_rows == 0:
        return "not ready", ["No labeled windows found."]

    if empty_rows == 0:
        return "not ready", ["No empty windows found."]

    if occupied_rows == 0:
        return "not ready", ["No occupied windows found."]

    minority = min(empty_rows, occupied_rows)
    majority = max(empty_rows, occupied_rows)
    minority_label = "empty" if empty_rows <= occupied_rows else "occupied"
    minority_ratio = minority / labeled_rows if labeled_rows else 0

    if labeled_rows < 200:
        notes.append(f"Only {labeled_rows} labeled windows are available.")
    if minority < 50:
        notes.append(f"Too little {minority_label} data ({minority} windows).")
    elif minority_ratio < 0.2:
        notes.append(
            f"Classes are imbalanced: {minority_label} is {minority_ratio:.1%} of labeled windows."
        )

    unlabeled_ratio = unlabeled_rows / dataset_summary["total_rows"] if dataset_summary["total_rows"] else 0
    if unlabeled_ratio > 0.6:
        notes.append(
            f"Many windows are unlabeled ({unlabeled_ratio:.1%}); training can still proceed on labeled rows."
        )

    if notes:
        if labeled_rows < 200 or minority < 50:
            return "too little labeled data", notes
        if minority_ratio < 0.2:
            return "too imbalanced", notes
        return "usable with caveats", notes

    return "enough for a first baseline", [
        f"Class balance looks workable: empty={empty_rows}, occupied={occupied_rows}."
    ]


def format_duration(seconds):
    if not seconds:
        return "0m"

    total_seconds = int(round(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes or hours:
        parts.append(f"{minutes}m")
    if not hours:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def print_summary(args, raw_summary, interval_summary, dataset_summary, dataset_source):
    verdict, notes = readiness_verdict(dataset_summary)
    label_counts = dataset_summary["label_counts"]

    print("Dataset Summary")
    print("=" * 15)
    print(f"DB: {args.db}")
    if args.dataset_csv:
        print(f"Dataset rows source: CSV ({args.dataset_csv})")
    else:
        print("Dataset rows source: generated from SQLite with current feature logic")

    print("")
    print("Raw samples")
    print(f"  Total raw samples: {raw_summary['total']}")
    if raw_summary["start"] is not None and raw_summary["end"] is not None:
        print(f"  Raw coverage: {format_duration(raw_summary['duration_seconds'])}")
    print("  Per node:")
    for node_id, count in sorted(raw_summary["per_node"].items()):
        print(f"    {node_id}: {count}")

    print("")
    print("Manual label intervals")
    print(f"  Distinct labeled intervals: {interval_summary['total_sessions']}")
    for label in ("empty", "occupied"):
        print(
            "  "
            + f"{label}: {interval_summary['sessions_by_label'][label]} sessions, "
            + f"{format_duration(interval_summary['duration_by_label'][label])}"
        )

    print("")
    print("Training-ready windows")
    print(f"  Total windows: {dataset_summary['total_rows']}")
    print(f"  Labeled windows: {dataset_summary['training_ready_rows']}")
    for label in LABELS:
        print(f"  {label}: {label_counts[label]}")

    labeled_rows = dataset_summary["training_ready_rows"]
    if labeled_rows:
        empty_ratio = label_counts["empty"] / labeled_rows
        occupied_ratio = label_counts["occupied"] / labeled_rows
        print("  Class balance:")
        print(f"    empty: {empty_ratio:.1%}")
        print(f"    occupied: {occupied_ratio:.1%}")

    print("  Per node:")
    for node_id, counts in sorted(dataset_summary["per_node"].items()):
        print(
            "    "
            + f"{node_id}: total={sum(counts.values())}, "
            + f"empty={counts['empty']}, occupied={counts['occupied']}, "
            + f"unlabeled={counts['unlabeled']}"
        )

    print("")
    print("Readiness")
    print(f"  Verdict: {verdict}")
    for note in notes:
        print(f"  - {note}")


def main():
    args = parse_args()
    validate_args(args)

    raw_samples = load_raw_samples(args.db, node_id=args.node_id)
    raw_summary = summarize_raw_samples(raw_samples)
    interval_summary = summarize_intervals(args.db)
    dataset_rows, dataset_source = load_dataset_rows(args)
    dataset_summary = summarize_dataset_rows(dataset_rows)
    print_summary(args, raw_summary, interval_summary, dataset_summary, dataset_source)


if __name__ == "__main__":
    main()
