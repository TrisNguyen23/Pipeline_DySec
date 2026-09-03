from __future__ import annotations

from pathlib import Path

from pipeline.trace_loader import load_trace


def evaluate_trace(
    trace_path: Path,
) -> dict:
    """
    Evaluate an externally generated DySec trace.

    The trace itself must already exist.
    This function does not create traces.
    """

    trace_path = Path(
        trace_path
    ).resolve()

    trace = load_trace(
        trace_path
    )
    from run_predict import predict_trace

    result = predict_trace(
        trace_path
    )

    if not isinstance(result, dict):
        raise RuntimeError(
            "predict_trace() must return a dictionary."
        )

    result["trace_path"] = str(
        trace_path
    )

    result["trace_metadata"] = trace

    return result