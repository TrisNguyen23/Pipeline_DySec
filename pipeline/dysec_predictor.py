"""
DySec Predictor Module
Executes inference on 39-feature DataFrames using Tanzir's pre-trained artifacts:
- Combined_schema.json
- Combined_vectorizer.pkl
- Combined_scaler.pkl
- Combined_rf_model.pkl
"""

import os
import json
import joblib
import numpy as np
import pandas as pd
from typing import Dict, Any
from scipy.sparse import csr_matrix, hstack


class DySecPredictor:
    def __init__(self, model_dir: str = "models/rf"):
        """
        Loads the schema, CountVectorizer, StandardScaler, and Random Forest Classifier.
        """
        self.model_dir = model_dir
        self.schema_path = os.path.join(model_dir, "Combined_schema.json")
        self.vectorizer_path = os.path.join(model_dir, "Combined_vectorizer.pkl")
        self.scaler_path = os.path.join(model_dir, "Combined_scaler.pkl")
        self.model_path = os.path.join(model_dir, "Combined_rf_model.pkl")

        # Load Schema
        with open(self.schema_path, "r", encoding="utf-8") as f:
            self.schema = json.load(f)

        self.numeric_columns = self.schema["numeric_columns"]
        self.categorical_columns = self.schema["categorical_columns"]
        self.malicious_value = self.schema.get("malicious_value", 1)

        # Load Pre-trained Artifacts
        self.vectorizer = joblib.load(self.vectorizer_path)
        self.scaler = joblib.load(self.scaler_path)
        self.model = joblib.load(self.model_path)

        # Validate dimensional alignment
        expected_features = self.model.n_features_in_
        calculated_features = len(self.numeric_columns) + len(self.vectorizer.vocabulary_)
        if calculated_features != expected_features:
            raise ValueError(
                f"Dimension Mismatch: Model expects {expected_features}, "
                f"but schema + vocabulary produces {calculated_features}."
            )

    def predict(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Predicts maliciousness for the given DataFrame.

        Parameters:
            df (pd.DataFrame): DataFrame containing 39 features.

        Returns:
            Dict[str, Any]: Prediction results including binary label, verdict, and probabilities.
        """
        # Validate columns
        missing = [
            col for col in self.numeric_columns + self.categorical_columns 
            if col not in df.columns
        ]
        if missing:
            raise ValueError(f"Missing required columns from DataFrame: {missing}")

        # 1. Numeric Feature Matrix (14 dimensions)
        x_numeric = df[self.numeric_columns].fillna(0).astype(float)
        x_numeric_sparse = csr_matrix(x_numeric.values)

        # 2. Categorical Text Sequence (n-gram tokens space-concatenated)
        categorical_text = (
            df[self.categorical_columns]
            .fillna("")
            .astype(str)
            .agg(" ".join, axis=1)
        )

        # 3. Vectorize Categorical Text into Sparse N-grams (168,837 dimensions)
        x_categorical = self.vectorizer.transform(categorical_text)

        # 4. Concatenate Numeric + Categorical Sparse Matrices (168,851 dimensions)
        x_combined = hstack([x_numeric_sparse, x_categorical], format="csr")

        # 5. Standard Scaling
        x_scaled = self.scaler.transform(x_combined)

        # 6. Random Forest Inference
        raw_pred = self.model.predict(x_scaled)[0]
        probabilities = self.model.predict_proba(x_scaled)[0]

        verdict = "MALICIOUS" if raw_pred == self.malicious_value else "BENIGN"

        package_name = df["Package_Name"].iloc[0] if "Package_Name" in df.columns else "unknown"

        return {
            "package_name": package_name,
            "prediction": int(raw_pred),
            "verdict": verdict,
            "probability_benign": float(probabilities[0]),
            "probability_malicious": float(probabilities[1]),
            "features_processed": int(x_combined.shape[1]),
        }