import os
import sys
import warnings

warnings.filterwarnings("ignore")

import joblib
import numpy as np

from config.settings import MODEL_PATH


def load_dysec_model(path):

    try:
        return joblib.load(path)

    except Exception:

        import pickle

        with open(path, "rb") as f:
            return pickle.load(f)


def build_feature_vector(trace_path, model):

    total_syscalls = 0

    if os.path.exists(trace_path):

        with open(
            trace_path,
            "r",
            errors="ignore"
        ) as f:

            total_syscalls = sum(
                1 for _ in f
            )

    n_features = getattr(
        model,
        "n_features_in_",
        188
    )

    feature_vector = np.zeros(
        (1, n_features)
    )

    if total_syscalls > 0:

        feature_vector[
            0,
            :min(total_syscalls, n_features)
        ] = 1.0

    return feature_vector, total_syscalls


def predict_trace(trace_path):

    model = load_dysec_model(
        MODEL_PATH
    )

    feature_vector, total_syscalls = (
        build_feature_vector(
            trace_path,
            model
        )
    )

    prediction = model.predict(
        feature_vector
    )[0]

    probabilities = None

    if hasattr(model, "predict_proba"):

        probabilities = (
            model.predict_proba(
                feature_vector
            )[0]
        )

    prediction_str = str(
        prediction
    ).lower()

    if prediction_str in [
        "0",
        "benign"
    ]:
        verdict = "BENIGN"
    else:
        verdict = "MALICIOUS"

    confidence = None

    if probabilities is not None:

        confidence = float(
            max(probabilities)
        )

    return {
        "verdict": verdict,
        "prediction": str(prediction),
        "confidence": confidence,
        "total_syscalls": total_syscalls,
    }


def main():

    if len(sys.argv) > 1:

        trace_path = sys.argv[1]

    else:

        print(
            "Usage: python run_predict.py <trace>"
        )

        return

    result = predict_trace(
        trace_path
    )

    print("=" * 60)
    print("DYSEC CLASSIFICATION")
    print("=" * 60)

    print(
        f"Trace: {trace_path}"
    )

    print(
        f"Syscalls: "
        f"{result['total_syscalls']:,}"
    )

    print(
        f"Verdict: "
        f"{result['verdict']}"
    )

    print(
        f"Prediction: "
        f"{result['prediction']}"
    )

    if result["confidence"] is not None:

        print(
            f"Confidence: "
            f"{result['confidence'] * 100:.2f}%"
        )


if __name__ == "__main__":
    main()