from __future__ import annotations

from pathlib import Path


class TraceNotFoundError(FileNotFoundError):
    """Raised when an expected trace does not exist."""


def load_trace(
    trace_path: Path,
) -> dict:

    trace_path = Path(
        trace_path
    ).resolve()

    if not trace_path.exists():
        raise TraceNotFoundError(
            f"Trace does not exist: {trace_path}"
        )

    if trace_path.is_file():

        if trace_path.stat().st_size == 0:
            raise TraceNotFoundError(
                f"Trace is empty: {trace_path}"
            )

        return {
            "path": str(trace_path),
            "size_bytes": trace_path.stat().st_size,
            "type": "file",
        }

    if trace_path.is_dir():

        trace_files = sorted(
            trace_path.glob("*.trace")
        )

        if not trace_files:
            raise TraceNotFoundError(
                f"No trace files found in: {trace_path}"
            )

        files = {}

        for path in trace_files:

            if path.stat().st_size > 0:
                files[path.stem] = {
                    "path": str(path),
                    "size_bytes": path.stat().st_size,
                }

        if not files:
            raise TraceNotFoundError(
                f"All trace files are empty: {trace_path}"
            )

        return {
            "path": str(trace_path),
            "type": "directory",
            "files": files,
        }

    raise TraceNotFoundError(
        f"Invalid trace path: {trace_path}"
    )