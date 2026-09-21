import argparse
import json
from pathlib import Path

import joblib
import pandas as pd
from scipy.sparse import hstack, csr_matrix


def load_artifacts(model_dir):
    model_dir = Path(model_dir)

    vectorizer = joblib.load(model_dir / "Combined_vectorizer.pkl")
    scaler = joblib.load(model_dir / "Combined_scaler.pkl")
    model = joblib.load(model_dir / "Combined_rf_model.pkl")

    with open(model_dir / "Combined_schema.json", "r", encoding="utf-8") as f:
        schema = json.load(f)

    with open(model_dir / "Combined_metrics.json", "r", encoding="utf-8") as f:
        metrics = json.load(f)

    return vectorizer, scaler, model, schema, metrics


def prepare_features(df, schema, vectorizer):
    numeric_columns = schema["numeric_columns"]
    categorical_columns = schema["categorical_columns"]

    required_columns = numeric_columns + categorical_columns
    missing = [col for col in required_columns if col not in df.columns]

    if missing:
        raise ValueError(
            "Missing required feature columns:\n"
            + "\n".join(f"  - {col}" for col in missing)
        )

    # -----------------------------
    # Numeric features
    # -----------------------------
    numerical_features = (
        df[numeric_columns]
        .fillna(0)
        .apply(pd.to_numeric, errors="coerce")
        .fillna(0)
        .astype(float)
    )

    numerical_sparse = csr_matrix(numerical_features.values)

    # -----------------------------
    # Categorical features
    # -----------------------------
    combined_categorical = (
        df[categorical_columns]
        .fillna("")
        .astype(str)
        .agg(" ".join, axis=1)
    )

    categorical_ngrams = vectorizer.transform(combined_categorical)

    # Same order as the original training pipeline:
    # numeric features first, categorical ngrams second.
    X = hstack(
        [numerical_sparse, categorical_ngrams],
        format="csr",
    )

    return X


def predict(input_csv, model_dir):
    print("=" * 70)
    print("DySec RF Inference")
    print("=" * 70)

    print(f"[+] Loading input: {input_csv}")

    df = pd.read_csv(input_csv)

    print(f"[+] Input rows: {len(df)}")
    print(f"[+] Input columns: {len(df.columns)}")

    (
        vectorizer,
        scaler,
        model,
        schema,
        metrics,
    ) = load_artifacts(model_dir)

    print("[+] Loaded RF artifacts")
    print(f"    Vectorizer features : {len(vectorizer.vocabulary_):,}")
    print(f"    Scaler features     : {scaler.n_features_in_:,}")
    print(f"    RF model features   : {model.n_features_in_:,}")
    print(f"    RF classes          : {model.classes_}")

    # ---------------------------------------------------------
    # Validate artifact dimensions before doing inference
    # ---------------------------------------------------------
    expected_features = (
        len(vectorizer.vocabulary_)
        + len(schema["numeric_columns"])
    )

    if expected_features != scaler.n_features_in_:
        raise ValueError(
            f"Feature dimension mismatch:\n"
            f"  vectorizer + numeric = {expected_features}\n"
            f"  scaler expects       = {scaler.n_features_in_}"
        )

    if scaler.n_features_in_ != model.n_features_in_:
        raise ValueError(
            f"Scaler/model dimension mismatch:\n"
            f"  scaler = {scaler.n_features_in_}\n"
            f"  model  = {model.n_features_in_}"
        )

    print(f"[+] Feature dimension verified: {expected_features:,}")

    # ---------------------------------------------------------
    # Feature preparation
    # ---------------------------------------------------------
    X = prepare_features(
        df,
        schema,
        vectorizer,
    )

    print(f"[+] Constructed feature matrix: {X.shape}")

    if X.shape[1] != scaler.n_features_in_:
        raise ValueError(
            f"Constructed feature matrix has {X.shape[1]:,} "
            f"features, but scaler expects {scaler.n_features_in_:,}."
        )

    # ---------------------------------------------------------
    # IMPORTANT:
    # transform() only.
    # No fit().
    # ---------------------------------------------------------
    print("[+] Applying pretrained scaler...")
    X_scaled = scaler.transform(X)

    print(f"[+] Scaled feature matrix: {X_scaled.shape}")

    # ---------------------------------------------------------
    # Pretrained RF inference
    # ---------------------------------------------------------
    print("[+] Running pretrained RF inference...")

    predictions = model.predict(X_scaled)

    probabilities = model.predict_proba(X_scaled)

    malicious_index = list(model.classes_).index(
        schema["malicious_value"]
    )

    malicious_probability = probabilities[:, malicious_index]

    # ---------------------------------------------------------
    # Results
    # ---------------------------------------------------------
    results = df.copy()

    results["prediction"] = predictions
    results["verdict"] = [
        "MALICIOUS" if p == schema["malicious_value"] else "BENIGN"
        for p in predictions
    ]

    results["malicious_probability"] = malicious_probability

    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)

    for i, prediction in enumerate(predictions):
        probability = malicious_probability[i]

        print(
            f"Row {i}: "
            f"prediction={prediction}, "
            f"verdict={results.loc[i, 'verdict']}, "
            f"malicious_probability={probability:.4f}"
        )

    # ---------------------------------------------------------
    # Save results
    # ---------------------------------------------------------
    input_path = Path(input_csv)

    output_path = (
        input_path.parent
        / f"{input_path.stem}_rf_prediction.csv"
    )

    results.to_csv(
        output_path,
        index=False,
    )

    print()
    print(f"[+] Results saved to: {output_path}")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Run pretrained DySec RF inference."
    )

    parser.add_argument(
        "input_csv",
        help="CSV containing the 14 numeric + 25 categorical features.",
    )

    parser.add_argument(
        "--model-dir",
        default="models/rf",
        help=(
            "Directory containing "
            "Combined_vectorizer.pkl, Combined_scaler.pkl, "
            "Combined_rf_model.pkl, Combined_schema.json, "
            "and Combined_metrics.json."
        ),
    )

    args = parser.parse_args()

    predict(
        input_csv=args.input_csv,
        model_dir=args.model_dir,
    )


if __name__ == "__main__":
    main()