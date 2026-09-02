from pathlib import Path
import os


PROJECT_ROOT = Path(__file__).resolve().parent.parent

PACKAGES_DIR = PROJECT_ROOT / "packages"

OUTPUT_DIR = (
    PROJECT_ROOT
    / "output_data"
    / "robustness_test"
)

MODEL_PATH = (
    PROJECT_ROOT
    / "models"
    / "RF_best_model_ngrams.pkl"
)

#Setup LLM API
OLLAMA_API = os.getenv(
    "OLLAMA_API",
    "http://localhost:11434/api/generate"
)

MODEL_NAME = "qwen3:8b"

TEMPERATURE = 0.3

LLM_TIMEOUT = 60

#Setup evaluation parameters
ROUNDS_PER_STRATEGY = 5

SIMULATION_MODE = True


PYTHON_EXECUTABLE = "python3"

TRACE_TIMEOUT = 120

EXPERIMENT_NAME = "dysec_robustness_evaluation"