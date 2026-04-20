import argparse
import csv
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split

from build_dataset import DEFAULT_OUTPUT_PATH
from model import DEFAULT_MODEL_PATH, FEATURE_COLUMNS, LABELS, save_model_bundle


def parse_args():
    parser = argparse.ArgumentParser(
        description="Train a baseline presence-state classifier from feature CSV rows."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Feature CSV produced by build_dataset.py.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_MODEL_PATH,
        help="Path where the trained model pickle will be written.",
    )
    parser.add_argument(
        "--test-size",
        type=float,
        default=0.25,
        help="Validation split fraction when enough labeled rows exist.",
    )
    parser.add_argument(
        "--random-state",
        type=int,
        default=42,
        help="Random seed for reproducible training.",
    )
    return parser.parse_args()


def read_training_rows(csv_path):
    rows = []
    skipped = Counter()

    with csv_path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        missing_columns = [
            column
            for column in [*FEATURE_COLUMNS, "label"]
            if column not in (reader.fieldnames or [])
        ]
        if missing_columns:
            raise SystemExit(
                "Missing required CSV columns: " + ", ".join(missing_columns)
            )

        for row in reader:
            label = (row.get("label") or "").strip()
            if label not in LABELS:
                skipped[label or "<blank>"] += 1
                continue

            try:
                features = [float(row[column]) for column in FEATURE_COLUMNS]
            except (TypeError, ValueError):
                skipped["bad_features"] += 1
                continue

            rows.append((features, label))

    return rows, skipped


def can_validate(label_counts):
    return (
        sum(label_counts.values()) >= 4
        and len(label_counts) >= 2
        and min(label_counts.values()) >= 2
    )


def train_model(rows, test_size, random_state):
    features = [features for features, _label in rows]
    labels = [label for _features, label in rows]
    label_counts = Counter(labels)
    estimator = RandomForestClassifier(
        n_estimators=100,
        random_state=random_state,
        class_weight="balanced",
    )

    validation = None
    if can_validate(label_counts):
        train_x, test_x, train_y, test_y = train_test_split(
            features,
            labels,
            test_size=test_size,
            random_state=random_state,
            stratify=labels,
        )
        estimator.fit(train_x, train_y)
        predictions = estimator.predict(test_x)
        validation = {
            "rows": len(test_y),
            "accuracy": accuracy_score(test_y, predictions),
            "report": classification_report(
                test_y,
                predictions,
                zero_division=0,
            ),
        }
    else:
        estimator.fit(features, labels)

    return estimator, label_counts, validation


def main():
    args = parse_args()
    if not args.input.exists():
        raise SystemExit(f"Dataset CSV not found: {args.input}")
    if not (0 < args.test_size < 1):
        raise SystemExit("--test-size must be between 0 and 1")

    rows, skipped = read_training_rows(args.input)
    if not rows:
        raise SystemExit(
            "No usable labeled rows found. Expected labels: "
            + ", ".join(LABELS)
        )

    labels_seen = {label for _features, label in rows}
    if len(labels_seen) < 2:
        raise SystemExit(
            "Need at least two label classes to train a classifier. "
            f"Found: {', '.join(sorted(labels_seen))}"
        )

    estimator, label_counts, validation = train_model(
        rows,
        test_size=args.test_size,
        random_state=args.random_state,
    )
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "input_csv": str(args.input),
        "feature_columns": FEATURE_COLUMNS,
        "labels": sorted(label_counts),
        "label_counts": dict(label_counts),
        "training_rows": len(rows),
        "label_note": (
            "PIR-derived labels are rough; empty/occupied require careful labels. "
            "PIR inactivity is not proof that a room is empty."
        ),
    }
    save_model_bundle(
        {
            "model": estimator,
            "feature_columns": FEATURE_COLUMNS,
            "metadata": metadata,
        },
        args.output,
    )

    print(f"Rows used: {len(rows)}")
    print("Label counts:")
    for label, count in sorted(label_counts.items()):
        print(f"  {label}: {count}")
    if skipped:
        print("Rows skipped:")
        for label, count in sorted(skipped.items()):
            print(f"  {label}: {count}")

    if validation:
        print(f"Validation rows: {validation['rows']}")
        print(f"Validation accuracy: {validation['accuracy']:.3f}")
        print(validation["report"])
    else:
        print("Validation skipped: not enough rows per class for a stratified split.")

    print("Label note: PIR-derived labels are rough; empty/occupied labels need careful collection.")
    print(f"Model saved: {args.output}")


if __name__ == "__main__":
    main()
