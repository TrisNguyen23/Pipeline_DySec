from pipeline.dysec_predictor import DySecPredictor

p = DySecPredictor("models/rf")

print("Categorical columns:", len(p.cat_cols))
print("Vectorizer:", p.vectorizer)
print("Scaler:", p.scaler)
print("RF features:", p.model.n_features_in_)
print("\n=== MODEL DETAILS ===")
print("Model type:", type(p.model))
print("Model n_features_in_:", p.model.n_features_in_)

print("\n=== VECTORIZER DETAILS ===")
print("ngram_range:", p.vectorizer.ngram_range)
print("vocabulary size:", len(p.vectorizer.vocabulary_))

print("\n=== SCALER DETAILS ===")
print("Scaler:", p.scaler)
print("Scaler n_features_in_:", p.scaler.n_features_in_)
print("\nNumeric columns:")
print(p.num_cols)

print("\nCategorical columns:")
print(p.cat_cols)