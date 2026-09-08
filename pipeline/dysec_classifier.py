from __future__ import annotations

from pathlib import Path

from run_predict import predict_trace


def classify_trace(
    trace_path: Path,
) -> dict:
    """
    Run the existing DySec predictor on one trace file.
    """

    trace_path = Path(
        trace_path
    ).resolve()

    if not trace_path.exists():
        raise FileNotFoundError(
            f"Trace does not exist: {trace_path}"
        )

    if not trace_path.is_file():
        raise ValueError(
            f"Trace path is not a file: {trace_path}"
        )

    result = predict_trace(
        trace_path
    )

    if not isinstance(result, dict):
        raise RuntimeError(
            "DySec predictor must return a dictionary."
        )

    verdict = str(
        result.get(
            "verdict",
            "UNKNOWN",
        )
    ).upper()

    return {
        **result,
        "verdict": verdict,
        "trace_path": str(trace_path),
    }