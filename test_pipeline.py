from pipeline.feature_extractor import DySecFeatureExtractor
from pipeline.dysec_predictor import DySecPredictor

# 1. Initialize extractor and predictor
extractor = DySecFeatureExtractor("models/rf/Combined_schema.json")
predictor = DySecPredictor("models/rf")

# 2. Extract features from a trace directory
# If logs are missing, extractor uses clean baseline defaults
sample_df = extractor.extract(trace_dir="output_data/sample_traces", package_name="demo_variant")

# 3. Run inference
result = predictor.predict(sample_df)

print("Inference Result:")
for key, value in result.items():
    print(f"  {key}: {value}")