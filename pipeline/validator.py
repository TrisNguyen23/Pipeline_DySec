from __future__ import annotations

from pathlib import Path

from config.settings import VALIDATION_TIMEOUT
from pipeline.executor import execute_package


def validate_behavior(
    original_package: Path,
    generated_package: Path,
    environment_root: Path | None = None,
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
            "error": (
                f"Original package missing: "
                f"{original_package}"
            ),
        }

    if not generated_package.exists():
        return {
            "preserved": False,
            "error": (
                f"Generated package missing: "
                f"{generated_package}"
            ),
        }

    if environment_root is None:
        environment_root = (
            generated_package.parent
            / ".validation_environments"
        )

    environment_root = Path(
        environment_root
    ).resolve()

    environment_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    original_env = (
        environment_root
        / "original"
    )

    generated_env = (
        environment_root
        / "generated"
    )

    original_result = execute_package(
        original_package,
        original_env,
        timeout=VALIDATION_TIMEOUT,
    )

    generated_result = execute_package(
        generated_package,
        generated_env,
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

    original_return = (
        original_result.get(
            "return_code"
        )
    )

    generated_return = (
        generated_result.get(
            "return_code"
        )
    )

    return_code_equal = (
        original_return
        == generated_return
    )

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
        "checks": {
            "original_completed": (
                original_completed
            ),
            "generated_completed": (
                generated_completed
            ),
            "original_success": (
                original_success
            ),
            "generated_success": (
                generated_success
            ),
            "return_code_equal": (
                return_code_equal
            ),
        },
        "original": original_result,
        "generated": generated_result,
        "error": None,
    }