import pickle
from pathlib import Path

from storage import PROJECT_ROOT


MODEL_DIR = PROJECT_ROOT / "models"
DEFAULT_MODEL_PATH = MODEL_DIR / "presence_model.pkl"

LABELS = ("empty", "occupied", "still", "moving")
FEATURE_COLUMNS = [
    "window_seconds",
    "sample_count",
    "rssi_count",
    "rssi_mean",
    "rssi_std",
    "rssi_min",
    "rssi_max",
    "rssi_delta",
]


class ModelNotFoundError(FileNotFoundError):
    pass


def feature_vector(row, feature_columns=FEATURE_COLUMNS):
    return [float(row[column]) for column in feature_columns]


def load_model_bundle(model_path=DEFAULT_MODEL_PATH):
    model_path = Path(model_path)
    if not model_path.exists():
        raise ModelNotFoundError(f"Model file not found: {model_path}")

    with model_path.open("rb") as file:
        bundle = pickle.load(file)

    if "model" not in bundle:
        raise ValueError(f"Invalid model file: {model_path}")

    return bundle


def save_model_bundle(bundle, model_path=DEFAULT_MODEL_PATH):
    model_path = Path(model_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)

    with model_path.open("wb") as file:
        pickle.dump(bundle, file)


def predict_state(feature_row, model_path=DEFAULT_MODEL_PATH):
    bundle = load_model_bundle(model_path)
    estimator = bundle["model"]
    feature_columns = bundle.get("feature_columns", FEATURE_COLUMNS)
    vector = feature_vector(feature_row, feature_columns)
    prediction = estimator.predict([vector])[0]
    confidence = None

    if hasattr(estimator, "predict_proba"):
        probabilities = estimator.predict_proba([vector])[0]
        classes = list(estimator.classes_)
        confidence = float(probabilities[classes.index(prediction)])

    return {
        "state": prediction,
        "confidence": confidence,
    }
