from __future__ import annotations

import os
import shutil
from dataclasses import asdict
from pathlib import Path

from pipeline.tracer import LocalPackageTracer


def _copy_existing_trace(
    existing_trace_dir: Path,
    trace_dir: Path,
) -> dict:

    existing_trace_dir = existing_trace_dir.resolve()
    trace_dir = trace_dir.resolve()

    if not existing_trace_dir.exists():
        raise FileNotFoundError(
            f"Existing trace directory not found: "
            f"{existing_trace_dir}"
        )

    if not existing_trace_dir.is_dir():
        raise NotADirectoryError(
            f"Existing trace path is not a directory: "
            f"{existing_trace_dir}"
        )

    trace_files = list(
        existing_trace_dir.glob("*.bt")
    )

    if not trace_files:
        raise RuntimeError(
            f"No .trace files found in existing trace directory: "
            f"{existing_trace_dir}"
        )

    trace_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    copied_files = []

    for source in trace_files:
        destination = trace_dir / source.name

        shutil.copy2(
            source,
            destination,
        )

        copied_files.append(
            destination.name
        )

    return {
        "install_success": True,
        "trace_available": True,
        "trace_directory": str(trace_dir),
        "trace_files": copied_files,
        "mode": "EXISTING_TRACE",
        "source_trace_directory": str(
            existing_trace_dir
        ),
    }


def trace_package(
    package_dir: Path,
    trace_dir: Path,
    sandbox_user: str,
    window: int,
) -> dict:

    package_dir = Path(
        package_dir
    ).resolve()

    trace_dir = Path(
        trace_dir
    ).resolve()

    trace_dir.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    existing_trace = os.environ.get(
        "DYSEC_EXISTING_TRACE_DIR"
    )

    if existing_trace:
        print(
            "[TRACE] Using existing DySec trace:"
        )
        print(
            f"[TRACE] {existing_trace}"
        )

        return _copy_existing_trace(
            existing_trace_dir=Path(existing_trace),
            trace_dir=trace_dir,
        )

    print(
        "[TRACE] Using live bpftrace tracing."
    )

    tracer = LocalPackageTracer(
        trace_output_dir=trace_dir.parent,
        sandbox_user=sandbox_user,
        post_install_window=window,
    )

    result = tracer.trace(
        package_dir=package_dir,
        trace_name=trace_dir.name,
    )

    result_dict = asdict(result)

    result_dict["mode"] = "LIVE_TRACE"

    return result_dict