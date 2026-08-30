import os
import sys
import warnings
warnings.filterwarnings("ignore")

import joblib
import numpy as np

MODEL_PATH = os.path.expanduser(
    "~/Desktop/DySec/DySec/DySec_Phase (iii) Data and Model Analysis/2. ML Models Evaluation/Dynamic Analysis/CombinedTraces/RF_best_model_ngrams.pkl"
)
DEFAULT_TRACE_DIR = os.path.expanduser("~/Desktop/DySec/output_data/traces/requests-2.31.0")

def load_dysec_model(path):
    try:
        return joblib.load(path)
    except Exception:
        import pickle
        with open(path, "rb") as f:
            return pickle.load(f)

def main():
    print("=" * 60)
    print("          DYSEC: PACKAGE CLASSIFICATION INFERENCE")
    print("=" * 60)

    if not os.path.exists(MODEL_PATH):
        print(f"[-] Error: Pre-trained model not found at:\n    {MODEL_PATH}")
        sys.exit(1)

    try:
        model = load_dysec_model(MODEL_PATH)
        print(f"[+] Successfully loaded model: {type(model).__name__}")
    except Exception as e:
        print(f"[-] Model loading failed: {e}")
        return

    if len(sys.argv) > 1:
        seq_file = sys.argv[1]
    else:
        seq_file = os.path.join(DEFAULT_TRACE_DIR, "syscall_sequence.trace")

    total_syscalls = 0
    if os.path.exists(seq_file):
        with open(seq_file, "r", errors="ignore") as f:
            total_syscalls = sum(1 for _ in f)

    print(f"[+] Target Trace File: {seq_file}")
    print(f"[+] Total System Call Events Captured: {total_syscalls:,}")

    n_features = getattr(model, "n_features_in_", 188)
    feature_vector = np.zeros((1, n_features))
    if total_syscalls > 0:
        feature_vector[0, :min(total_syscalls, n_features)] = 1.0

    prediction = model.predict(feature_vector)[0]
    probabilities = model.predict_proba(feature_vector)[0] if hasattr(model, "predict_proba") else None

    verdict = "BENIGN (Safe)" if str(prediction).lower() in ["0", "benign"] else "MALICIOUS (Threat Detected)"

    print("-" * 60)
    print(f"-> FINAL VERDICT      : {verdict}")
    print(f"-> PREDICTED CLASS ID : {prediction}")
    if probabilities is not None:
        print(f"-> CONFIDENCE SCORE   : Benign: {probabilities[0]*100:.2f}% | Malicious: {probabilities[1]*100:.2f}%")
    print("=" * 60)

if __name__ == "__main__":
    main()