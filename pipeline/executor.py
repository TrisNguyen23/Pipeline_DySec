from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from config.settings import (
    PYTHON_EXECUTABLE,
    SANDBOX_TIMEOUT,
)


class ExecutionError(RuntimeError):
    """Raised when execution cannot be started."""


def execute_python(
    code_path: Path,
    timeout: int = SANDBOX_TIMEOUT,
    working_directory: Optional[Path] = None,
) -> dict:
    """
    Execute a Python program and capture its observable process result.

    This function does NOT perform DySec tracing.

    Parameters
    ----------
    code_path:
        Python file to execute.

    timeout:
        Maximum execution time in seconds.

    working_directory:
        Directory used as the subprocess working directory.
        Defaults to the directory containing code_path.
    """

    code_path = Path(code_path).resolve()

    if not code_path.exists():
        raise FileNotFoundError(
            f"Python file does not exist: {code_path}"
        )

    if not code_path.is_file():
        raise ExecutionError(
            f"Expected a file but received: {code_path}"
        )

    if code_path.suffix != ".py":
        raise ExecutionError(
            f"Expected a Python file but received: {code_path}"
        )

    if working_directory is None:
        working_directory = code_path.parent
    else:
        working_directory = Path(
            working_directory
        ).resolve()

    if not working_directory.exists():
        raise FileNotFoundError(
            f"Working directory does not exist: "
            f"{working_directory}"
        )

    environment = os.environ.copy()

    command = [
        PYTHON_EXECUTABLE,
        str(code_path),
    ]

    start_time = time.monotonic()

    try:
        completed = subprocess.run(
            command,
            cwd=str(working_directory),
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

        duration = time.monotonic() - start_time

        return {
            "success": completed.returncode == 0,
            "return_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "duration": duration,
            "timed_out": False,
            "command": command,
            "working_directory": str(
                working_directory
            ),
        }

    except subprocess.TimeoutExpired as exc:

        duration = time.monotonic() - start_time

        stdout = exc.stdout or ""
        stderr = exc.stderr or ""

        if isinstance(stdout, bytes):
            stdout = stdout.decode(
                "utf-8",
                errors="replace",
            )

        if isinstance(stderr, bytes):
            stderr = stderr.decode(
                "utf-8",
                errors="replace",
            )

        return {
            "success": False,
            "return_code": None,
            "stdout": stdout,
            "stderr": stderr,
            "duration": duration,
            "timed_out": True,
            "command": command,
            "working_directory": str(
                working_directory
            ),
        }


def execute_and_trace(
    code_path: Path,
    trace_path: Path,
    timeout: int = SANDBOX_TIMEOUT,
) -> dict:
    """
    Backwards-compatible wrapper.

    IMPORTANT:
    This project does not perform tracing.

    The trace_path argument is retained so existing callers do not
    immediately break, but this function does not create a trace.

    New code should use execute_python() directly.
    """

    execution = execute_python(
        code_path=code_path,
        timeout=timeout,
        working_directory=Path(code_path).parent,
    )

    execution["trace_path"] = str(
        Path(trace_path)
    )

    execution["tracing_external"] = True

    return execution