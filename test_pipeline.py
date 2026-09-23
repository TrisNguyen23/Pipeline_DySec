import os
from pipeline.feature_extractor import DySecFeatureExtractor
from pipeline.dysec_predictor import DySecPredictor
from config.settings import PROJECT_ROOT

def test_inference_flow():
    schema_path = os.path.join(PROJECT_ROOT, "models", "rf", "Combined_schema.json")
    model_dir = os.path.join(PROJECT_ROOT, "models", "rf")
    
    extractor = DySecFeatureExtractor(schema_path)
    predictor = DySecPredictor(model_dir)
    
    # Giả lập 1 trace record rỗng/mẫu để test khớp chiều ma trận
    dummy_trace_dir = "/tmp/dummy_trace"
    os.makedirs(dummy_trace_dir, exist_ok=True)
    
    df_39 = extractor.extract(dummy_trace_dir, "test_pkg")
    assert df_39.shape[1] >= 39, "Cột trích xuất không đủ 39 features!"
    
    res = predictor.predict(df_39)
    print("[PASS] DySec Inference Pipeline Test:", res)

if __name__ == "__main__":
    test_inference_flow()