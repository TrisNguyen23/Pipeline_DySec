from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ============================================================
# Dataset / output
# ============================================================

PACKAGES_DIR = (
    PROJECT_ROOT / "packages" / "Malicious Packages"
)

OUTPUT_DIR = (
    PROJECT_ROOT / "output_data" / "robustness_test"
)

GENERATED_DIR = OUTPUT_DIR / "generated"
VALIDATION_DIR = OUTPUT_DIR / "validation"
EVALUATION_DIR = OUTPUT_DIR / "evaluation"
LOG_DIR = OUTPUT_DIR / "logs"
RESULTS_DIR = OUTPUT_DIR / "results"


# ============================================================
# LLM
# ============================================================

OLLAMA_API = os.getenv(
    "OLLAMA_API",
    "http://192.168.10.1:11434/api/generate",
)

MODEL_NAME = os.getenv(
    "MODEL_NAME",
    "qwen3:8b",
)

TEMPERATURE = float(
    os.getenv("TEMPERATURE", "0.5")
)

LLM_TIMEOUT = int(
    os.getenv("LLM_TIMEOUT", "500")
)


# ============================================================
# Experiment
# ============================================================

EXPERIMENT_NAME = (
    "dysec_progressive_llm_robustness"
)

EXPERIMENT_ROUNDS = int(
    os.getenv("EXPERIMENT_ROUNDS", "15")
)

EXPERIMENT_SEED = int(
    os.getenv("EXPERIMENT_SEED", "42")
)

EXPERIMENT_METHODS = (
    "random",
    "function_level",
    "proposed",
    "proposed_feedback",
)

PROMPT_VERSION = os.getenv(
    "PROMPT_VERSION",
    "v2",
)

# Important:
# The current validator performs installation validation,
# not full semantic/behavioral equivalence.
VALIDATION_TYPE = "installation"


# ============================================================
# Execution / validation
# ============================================================

PYTHON_EXECUTABLE = os.getenv(
    "PYTHON_EXECUTABLE",
    "python3",
)

SANDBOX_TIMEOUT = int(
    os.getenv("SANDBOX_TIMEOUT", "180")
)

VALIDATION_TIMEOUT = int(
    os.getenv("VALIDATION_TIMEOUT", "180")
)


# ============================================================
# Trace configuration
# ============================================================

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
    os.getenv("TRACE_TIMEOUT", "180")
)

TRACE_STARTUP_DELAY = float(
    os.getenv("TRACE_STARTUP_DELAY", "2")
)

SANDBOX_USER = os.getenv(
    "SANDBOX_USER",
    "dysec",
)

TRACE_WINDOW = int(
    os.getenv("TRACE_WINDOW", "120")
)


# ============================================================
# Artifact retention
# ============================================================

KEEP_GENERATED_VARIANTS = (
    os.getenv(
        "KEEP_GENERATED_VARIANTS",
        "true",
    ).lower()
    == "true"
)