from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _copy_existing_trace(
    existing_trace_dir: Path,
    trace_dir: Path,
) -> dict:
    existing_trace_dir = existing_trace_dir.resolve()
    trace_dir = trace_dir.resolve()

    if not existing_trace_dir.exists():
        raise FileNotFoundError(
            f"Existing trace directory not found: {existing_trace_dir}"
        )

    trace_dir.mkdir(parents=True, exist_ok=True)
    copied_files = []

    for item in existing_trace_dir.iterdir():
        dest = trace_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)
        copied_files.append(item.name)

    return {
        "install_success": True,
        "trace_available": True,
        "trace_directory": str(trace_dir),
        "trace_files": copied_files,
        "mode": "EXISTING_TRACE",
        "source_trace_directory": str(existing_trace_dir),
    }


def trace_package(
    package_dir: Path,
    trace_dir: Path,
    sandbox_user: str,
    window: int,
) -> dict:
    package_dir = Path(package_dir).resolve()
    trace_dir = Path(trace_dir).resolve()

    # Ensure target trace directory exists
    trace_dir.mkdir(parents=True, exist_ok=True)

    # Check for pre-existing trace override
    existing_trace = os.environ.get("DYSEC_EXISTING_TRACE_DIR")
    if existing_trace:
        print("[TRACE] Using existing DySec trace:")
        print(f"[TRACE] {existing_trace}")
        return _copy_existing_trace(
            existing_trace_dir=Path(existing_trace),
            trace_dir=trace_dir,
        )

    print(f"[TRACE] Running QUT-DV25 tracer on package: {package_dir}")
    print(f"[TRACE] Target output directory: {trace_dir}")

    # Determine tracer script location
    # Prefer tracer.py or tracer(v6).py located at Pipeline_DySec or project root
    candidate_tracers = [
        # Path("tracer(v6).py").resolve(),
        # Path("tracer.py").resolve(),
        # Path(__file__).resolve().parent.parent / "tracer(v6).py",
        # Path(__file__).resolve().parent.parent / "tracer.py",
        Path("/home/sandbox/Desktop/DySec/Pipeline_DySec/pipeline/tracer.py"),
    ]

    tracer_script = None
    for candidate in candidate_tracers:
        if candidate.exists():
            tracer_script = candidate
            break

    if tracer_script is None:
        raise FileNotFoundError(
            "Could not find tracer(v6).py or tracer.py in project roots."
        )

    # Extract clean package name from path
    try:
        package_name = trace_dir.parts[-3]
    except IndexError:
        package_name = package_dir.name

    cmd = [
        sys.executable,
        str(tracer_script),
        str(package_dir),
        "--output",
        str(trace_dir),
        "--label",
        str(package_name),
        "--monitor-seconds",
        str(window),
    ]

    print(f"[TRACE] Executing: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )

    has_traces = any(trace_dir.iterdir())

    return {
        "install_success": result.returncode == 0,
        "trace_available": has_traces,
        "trace_directory": str(trace_dir),
        "return_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "mode": "QUT_DV25_LIVE_TRACE",
    }