from __future__ import annotations

from pathlib import Path

from pipeline.trace_loader import load_trace
from pipeline.dysec_classifier import classify_trace


TRACE_FILE_NAME = "syscall_sequence.trace"


def evaluate_trace(
    trace_path: Path,
) -> dict:
    """
    Evaluate a DySec trace directory.

    The tracer produces multiple trace files.
    The existing DySec predictor currently accepts
    one trace file, so syscall_sequence.trace is used.
    """

    trace_path = Path(
        trace_path
    ).resolve()

    trace_metadata = load_trace(
        trace_path
    )

    if trace_path.is_dir():

        classifier_trace = (
            trace_path
            / TRACE_FILE_NAME
        )

    else:

        classifier_trace = trace_path

    result = classify_trace(
        classifier_trace
    )

    result["trace_directory"] = str(
        trace_path
    )

    result["trace_metadata"] = (
        trace_metadata
    )

    return result