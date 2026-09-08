from pathlib import Path
import os


PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------
# Packages
# ------------------------------------------------------------

PACKAGES_DIR = (
    PROJECT_ROOT
    / "packages"
    / "Malicious Packages"
)


# ------------------------------------------------------------
# Robustness experiment output
# ------------------------------------------------------------

OUTPUT_DIR = (
    PROJECT_ROOT
    / "output_data"
    / "robustness_test"
)

GENERATED_DIR = OUTPUT_DIR / "generated"

VALIDATION_DIR = OUTPUT_DIR / "validation"

EVALUATION_DIR = OUTPUT_DIR / "evaluation"

LOG_DIR = OUTPUT_DIR / "logs"

RESULTS_DIR = OUTPUT_DIR / "results"


# ------------------------------------------------------------
# DySec model
# ------------------------------------------------------------

MODEL_PATH = (
    PROJECT_ROOT
    / "models"
    / "RF_best_model_ngrams.pkl"
)


# ------------------------------------------------------------
# LLM
# ------------------------------------------------------------

OLLAMA_API = os.getenv(
    "OLLAMA_API",
    "http://localhost:11434/api/generate",
)

MODEL_NAME = os.getenv(
    "MODEL_NAME",
    "qwen3:8b",
)

TEMPERATURE = float(
    os.getenv(
        "TEMPERATURE",
        "0.3",
    )
)

LLM_TIMEOUT = int(
    os.getenv(
        "LLM_TIMEOUT",
        "120",
    )
)


# ------------------------------------------------------------
# Robustness loop
# ------------------------------------------------------------

ROUNDS_PER_STRATEGY = int(
    os.getenv(
        "ROUNDS_PER_STRATEGY",
        "5",
    )
)


# ------------------------------------------------------------
# Sandbox
# ------------------------------------------------------------

PYTHON_EXECUTABLE = os.getenv(
    "PYTHON_EXECUTABLE",
    "python3",
)

SANDBOX_TIMEOUT = int(
    os.getenv(
        "SANDBOX_TIMEOUT",
        "180",
    )
)

VALIDATION_TIMEOUT = int(
    os.getenv(
        "VALIDATION_TIMEOUT",
        "180",
    )
)


# ------------------------------------------------------------
# Tracing
# ------------------------------------------------------------

TRACE_DIR = Path(
    os.getenv(
        "TRACE_DIR",
        str(
            PROJECT_ROOT
            / "output_data"
            / "robustness_test"
            / "traces"
        ),
    )
)

TRACE_TIMEOUT = int(
    os.getenv(
        "TRACE_TIMEOUT",
        "180",
    )
)

TRACE_STARTUP_DELAY = float(
    os.getenv(
        "TRACE_STARTUP_DELAY",
        "2",
    )
)

SANDBOX_USER = os.getenv(
    "SANDBOX_USER",
    "dysec",
)

TRACE_WINDOW = int(
    os.getenv(
        "TRACE_WINDOW",
        "30",
    )
)


# ------------------------------------------------------------
# Experiment
# ------------------------------------------------------------

KEEP_GENERATED_VARIANTS = (
    os.getenv(
        "KEEP_GENERATED_VARIANTS",
        "true",
    ).lower()
    == "true"
)

EXPERIMENT_NAME = (
    "dysec_robustness_evaluation"
)