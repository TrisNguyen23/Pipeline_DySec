"""
Inference wrapper for Tanzir's DySec RF bundle.

Raw input: 39 features = 14 numeric + 25 categorical.
Internal RF input: 168851 features after CountVectorizer + numeric hstack.
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd
from scipy.sparse import csr_matrix, hstack


class DySecPredictor:
    def __init__(self, model_dir: str = "models/rf"):
        root = Path(model_dir)

        with (root / "Combined_schema.json").open("r", encoding="utf-8") as f:
            schema = json.load(f)

        self.num_cols = list(schema["numeric_columns"])
        self.cat_cols = list(schema["categorical_columns"])
        self.raw_cols = self.num_cols + self.cat_cols

        self.vectorizer = joblib.load(root / "Combined_vectorizer.pkl")
        self.scaler = joblib.load(root / "Combined_scaler.pkl")
        self.model = joblib.load(root / "Combined_rf_model.pkl")

        if len(self.raw_cols) != 39:
            raise ValueError(f"Expected 39 raw features, got {len(self.raw_cols)}")

        transformed = len(self.num_cols) + len(self.vectorizer.vocabulary_)
        scaler_features = getattr(self.scaler, "n_features_in_", None)
        rf_features = getattr(self.model, "n_features_in_", None)

        if scaler_features is not None and scaler_features != transformed:
            raise ValueError(
                f"Bundle mismatch: vectorizer+numeric={transformed}, "
                f"scaler expects {scaler_features}"
            )
        if rf_features is not None and rf_features != transformed:
            raise ValueError(
                f"Bundle mismatch: vectorizer+numeric={transformed}, "
                f"RF expects {rf_features}"
            )

    def prepare(self, df_39: pd.DataFrame):
        missing = [c for c in self.raw_cols if c not in df_39.columns]
        extra = [c for c in df_39.columns if c not in self.raw_cols]
        if missing or extra:
            raise ValueError(
                "Raw feature schema mismatch.\n"
                f"Missing: {missing}\n"
                f"Extra: {extra}"
            )

        x_num = csr_matrix(
            df_39[self.num_cols].fillna(0).astype(float).values
        )

        cat_text = (
            df_39[self.cat_cols]
            .fillna("")
            .astype(str)
            .agg(" ".join, axis=1)
        )
        x_cat = self.vectorizer.transform(cat_text)

        x = hstack([x_num, x_cat], format="csr")
        x_scaled = self.scaler.transform(x)
        return x_scaled

    def predict(self, df_39: pd.DataFrame) -> dict:
        df_39 = df_39[self.raw_cols].copy()
        x_scaled = self.prepare(df_39)

        pred = int(self.model.predict(x_scaled)[0])
        prob = self.model.predict_proba(x_scaled)[0]

        return {
            "prediction": pred,
            "verdict": "MALICIOUS" if pred == 1 else "BENIGN",
            "p_benign": float(prob[0]),
            "p_malicious": float(prob[1]),
            "raw_features": len(self.raw_cols),
            "vectorizer_features": len(self.vectorizer.vocabulary_),
            "transformed_features": int(x_scaled.shape[1]),
            "rf_features": int(getattr(self.model, "n_features_in_", x_scaled.shape[1])),
        }
