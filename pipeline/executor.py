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
    package_root = Path(package_root).resolve()
    environment_directory = Path(
        environment_directory
    ).resolve()

    if not package_root.exists():
        raise FileNotFoundError(
            f"Package directory does not exist: "
            f"{package_root}"
        )

    environment_directory.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    venv_python = environment_directory / "bin" / "python"

    # Create an isolated virtual environment if it does not exist.
    if not venv_python.exists():
        create_command = [
            PYTHON_EXECUTABLE,
            "-m",
            "venv",
            str(environment_directory),
        ]

        try:
            created = subprocess.run(
                create_command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "success": False,
                "return_code": None,
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
                "duration": 0.0,
                "timed_out": True,
                "command": create_command,
                "package_root": str(package_root),
                "environment_directory": str(
                    environment_directory
                ),
            }

        if created.returncode != 0:
            return {
                "success": False,
                "return_code": created.returncode,
                "stdout": created.stdout,
                "stderr": created.stderr,
                "duration": 0.0,
                "timed_out": False,
                "command": create_command,
                "package_root": str(package_root),
                "environment_directory": str(
                    environment_directory
                ),
            }

    pip_command = [
        str(venv_python),
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
            pip_command,
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
            "return_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "duration": duration,
            "timed_out": False,
            "command": pip_command,
            "package_root": str(package_root),
            "environment_directory": str(
                environment_directory
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
            "command": pip_command,
            "package_root": str(package_root),
            "environment_directory": str(
                environment_directory
            ),
        }