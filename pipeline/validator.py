from __future__ import annotations

from pathlib import Path

from config.settings import VALIDATION_TIMEOUT
from pipeline.executor import execute_package


def _normalise(value) -> str:

    if value is None:
        return ""

    return (
        str(value)
        .replace("\r\n", "\n")
        .strip()
    )


def validate_behavior(
    original_package: Path,
    generated_package: Path,
) -> dict:

    original_package = Path(
        original_package
    ).resolve()

    generated_package = Path(
        generated_package
    ).resolve()

    if not original_package.exists():
        return {
            "preserved": False,
            "method": "package_installation",
            "error": (
                "Original package does not exist."
            ),
        }

    if not generated_package.exists():
        return {
            "preserved": False,
            "method": "package_installation",
            "error": (
                "Generated package does not exist."
            ),
        }

    original_env = (
        original_package
        / ".validation_env"
    )

    generated_env = (
        generated_package
        / ".validation_env"
    )

    original_result = execute_package(
        package_root=original_package,
        environment_directory=original_env,
        timeout=VALIDATION_TIMEOUT,
    )

    generated_result = execute_package(
        package_root=generated_package,
        environment_directory=generated_env,
        timeout=VALIDATION_TIMEOUT,
    )

    checks = {
        "original_completed": (
            not original_result["timed_out"]
        ),
        "generated_completed": (
            not generated_result["timed_out"]
        ),
        "success_equal": (
            original_result["success"]
            == generated_result["success"]
        ),
        "return_code_equal": (
            original_result["return_code"]
            == generated_result["return_code"]
        ),
        "stdout_equal": (
            _normalise(
                original_result["stdout"]
            )
            ==
            _normalise(
                generated_result["stdout"]
            )
        ),
    }

    return {
        "preserved": all(
            checks.values()
        ),
        "method": "package_installation",
        "checks": checks,
        "original": original_result,
        "generated": generated_result,
        "error": None,
    }