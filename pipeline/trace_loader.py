from __future__ import annotations

from pathlib import Path


class TraceNotFoundError(FileNotFoundError):
    """Raised when an expected external trace does not exist."""


def load_trace(trace_path: Path) -> dict:
    """
    Validate and load an externally generated trace.

    Tracing is NOT performed here.
    """

    trace_path = Path(
        trace_path
    ).resolve()

    if not trace_path.exists():
        raise TraceNotFoundError(
            f"Trace does not exist: {trace_path}"
        )

    if not trace_path.is_file():
        raise TraceNotFoundError(
            f"Trace path is not a file: {trace_path}"
        )

    if trace_path.stat().st_size == 0:
        raise TraceNotFoundError(
            f"Trace is empty: {trace_path}"
        )

    return {
        "path": str(trace_path),
        "size_bytes": trace_path.stat().st_size,
    }