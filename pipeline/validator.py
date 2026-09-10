from __future__ import annotations

from pathlib import Path

from config.settings import VALIDATION_TIMEOUT
from pipeline.executor import execute_package


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
            "checks": {},
            "original": None,
            "generated": None,
            "error": (
                "Original package does not exist."
            ),
        }

    if not generated_package.exists():
        return {
            "preserved": False,
            "method": "package_installation",
            "checks": {},
            "original": None,
            "generated": None,
            "error": (
                "Generated package does not exist."
            ),
        }

    original_env = (
        original_package / ".validation_env"
    )

    generated_env = (
        generated_package / ".validation_env"
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

    original_completed = not bool(
        original_result.get(
            "timed_out",
            False,
        )
    )

    generated_completed = not bool(
        generated_result.get(
            "timed_out",
            False,
        )
    )

    original_success = bool(
        original_result.get(
            "success",
            False,
        )
    )

    generated_success = bool(
        generated_result.get(
            "success",
            False,
        )
    )

    success_equal = (
        original_success
        == generated_success
    )

    return_code_equal = (
        original_result.get("return_code")
        == generated_result.get("return_code")
    )

    checks = {
        "original_completed": original_completed,
        "generated_completed": generated_completed,
        "success_equal": success_equal,
        "return_code_equal": return_code_equal,
    }

    # Behavior can only be considered preserved
    # when both packages actually execute/install
    # successfully and produce the same result.
    preserved = (
        original_completed
        and generated_completed
        and original_success
        and generated_success
        and return_code_equal
    )

    return {
        "preserved": preserved,
        "method": "package_installation",
        "checks": checks,
        "original": original_result,
        "generated": generated_result,
        "error": None,
    }