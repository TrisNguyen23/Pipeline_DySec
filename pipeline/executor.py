from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from config.settings import (
    PYTHON_EXECUTABLE,
    SANDBOX_TIMEOUT,
)


def execute_package(
    package_root: Path,
    environment_directory: Path,
    timeout: int = SANDBOX_TIMEOUT,
) -> dict:

    package_root = Path(
        package_root
    ).resolve()

    environment_directory = Path(
        environment_directory
    ).resolve()

    if not package_root.exists():
        raise FileNotFoundError(
            f"Package directory does not exist: "
            f"{package_root}"
        )

    environment_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    command = [
        PYTHON_EXECUTABLE,
        "-m",
        "pip",
        "install",
        "--no-deps",
        "--no-index",
        str(package_root),
    ]

    environment = os.environ.copy()

    start_time = time.monotonic()

    try:
        completed = subprocess.run(
            command,
            cwd=str(package_root),
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

        duration = (
            time.monotonic()
            - start_time
        )

        return {
            "success": (
                completed.returncode == 0
            ),
            "return_code": (
                completed.returncode
            ),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "duration": duration,
            "timed_out": False,
            "command": command,
            "package_root": str(
                package_root
            ),
        }

    except subprocess.TimeoutExpired as exc:

        return {
            "success": False,
            "return_code": None,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "duration": (
                time.monotonic()
                - start_time
            ),
            "timed_out": True,
            "command": command,
            "package_root": str(
                package_root
            ),
        }