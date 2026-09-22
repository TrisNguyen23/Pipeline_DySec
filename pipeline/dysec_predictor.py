import os
import json
import joblib
import pandas as pd
from scipy.sparse import csr_matrix, hstack

class DySecPredictor:
    def __init__(self, model_dir="models/rf"):
        with open(os.path.join(model_dir, "Combined_schema.json"), "r", encoding="utf-8") as f:
            schema = json.load(f)
        self.num_cols = schema["numeric_columns"]
        self.cat_cols = schema["categorical_columns"]
        
        self.vectorizer = joblib.load(os.path.join(model_dir, "Combined_vectorizer.pkl"))
        self.scaler = joblib.load(os.path.join(model_dir, "Combined_scaler.pkl"))
        self.model = joblib.load(os.path.join(model_dir, "Combined_rf_model.pkl"))

    def predict(self, df_39: pd.DataFrame) -> dict:
        x_num = csr_matrix(df_39[self.num_cols].fillna(0).astype(float).values)
        cat_text = df_39[self.cat_cols].fillna("").astype(str).agg(" ".join, axis=1)
        x_cat = self.vectorizer.transform(cat_text)
        
        x = hstack([x_num, x_cat], format="csr")
        x_scaled = self.scaler.transform(x)
        
        pred = int(self.model.predict(x_scaled)[0])
        prob = self.model.predict_proba(x_scaled)[0]
        return {
            "prediction": pred,
            "verdict": "MALICIOUS" if pred == 1 else "BENIGN",
            "p_benign": float(prob[0]),
            "p_malicious": float(prob[1])
        }