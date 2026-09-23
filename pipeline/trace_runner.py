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

    trace_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------
    # Existing trace override
    # ---------------------------------------------------------
    existing_trace = os.environ.get("DYSEC_EXISTING_TRACE_DIR")

    if existing_trace:
        print("[TRACE] Using existing DySec trace:")
        print(f"[TRACE] {existing_trace}")

        return _copy_existing_trace(
            existing_trace_dir=Path(existing_trace),
            trace_dir=trace_dir,
        )

    # ---------------------------------------------------------
    # Locate tracer
    # ---------------------------------------------------------
    print(f"[TRACE] Running QUT-DV25 tracer on package: {package_dir}")
    print(f"[TRACE] Target output directory: {trace_dir}")

    tracer_script = Path(
        "/home/sandbox/Desktop/DySec/Pipeline_DySec/pipeline/tracer.py"
    )

    if not tracer_script.exists():
        raise FileNotFoundError(
            f"Tracer not found: {tracer_script}"
        )

    # ---------------------------------------------------------
    # Build command
    # ---------------------------------------------------------
    cmd = [
        "/usr/bin/python3",
        str(tracer_script),
        str(package_dir),
        "--output",
        str(trace_dir),
        "--monitor-seconds",
        str(window),
    ]

    print(f"[TRACE] Executing: {' '.join(cmd)}")

    # ---------------------------------------------------------
    # Debug environment
    # ---------------------------------------------------------
    print("\n========== TRACE ENV DEBUG ==========")
    print("Python:", "/usr/bin/python3")
    print("sys.executable:", sys.executable)
    print("Tracer:", tracer_script)
    print("Package:", package_dir)
    print("Output:", trace_dir)
    print("Window:", window)
    print("Current working directory:", os.getcwd())
    print("USER:", os.environ.get("USER"))
    print("HOME:", os.environ.get("HOME"))
    print("PATH:", os.environ.get("PATH"))
    print("=====================================\n")

    # ---------------------------------------------------------
    # Run tracer
    # ---------------------------------------------------------
    env = os.environ.copy()

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        cwd=str(tracer_script.parent),
        env=env,
    )

    # ---------------------------------------------------------
    # Debug result
    # ---------------------------------------------------------
    print("\n========== TRACER DEBUG ==========")
    print("COMMAND:", " ".join(cmd))
    print("RETURN CODE:", result.returncode)

    print("STDOUT:")
    print(result.stdout)

    print("STDERR:")
    print(result.stderr)

    print("==================================\n")

    # ---------------------------------------------------------
    # Determine trace success
    # ---------------------------------------------------------
    trace_files = []

    if trace_dir.exists():
        trace_files = [
            p for p in trace_dir.rglob("*")
            if p.is_file()
        ]

    has_traces = len(trace_files) > 0
    tracer_success = result.returncode == 0

    if not tracer_success:
        print(
            f"[TRACE ERROR] Tracer exited with code "
            f"{result.returncode}"
        )

    print(
        f"[TRACE] Files generated: {len(trace_files)}"
    )

    print(
        f"[TRACE] Tracer success: {tracer_success}"
    )

    print(
        f"[TRACE] Trace available: "
        f"{tracer_success and has_traces}"
    )

    # ---------------------------------------------------------
    # Return result
    # ---------------------------------------------------------
    return {
        "install_success": tracer_success,
        "trace_available": tracer_success and has_traces,
        "trace_directory": str(trace_dir),
        "trace_files": [
            str(p.relative_to(trace_dir))
            for p in trace_files
        ],
        "return_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "mode": "QUT_DV25_LIVE_TRACE",
    }