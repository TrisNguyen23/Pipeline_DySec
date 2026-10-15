
from __future__ import annotations

from pathlib import Path
from typing import Any

from config.settings import VALIDATION_TIMEOUT
from pipeline.executor import execute_package


def _error_message(result: dict[str, Any] | None) -> str | None:
    """Extract a useful error message from an execution result."""
    if not result:
        return None

    stderr = result.get("stderr")
    error = result.get("error")

    if error:
        return str(error)

    if stderr and str(stderr).strip():
        return str(stderr).strip()[-2000:]

    return None


def _execute_safely(
    package: Path,
    environment: Path,
) -> dict[str, Any]:
    """
    Execute the existing package-validation operation.

    Exceptions are recorded as inconclusive validation errors rather than
    being misclassified as package installation failures.
    """
    try:
        result = execute_package(
            package,
            environment,
            timeout=VALIDATION_TIMEOUT,
        )

        if not isinstance(result, dict):
            return {
                "success": False,
                "timed_out": False,
                "return_code": None,
                "error": (
                    "Executor returned an unexpected result type: "
                    f"{type(result).__name__}"
                ),
                "execution_error": True,
            }

        return result

    except Exception as exc:
        return {
            "success": False,
            "timed_out": False,
            "return_code": None,
            "error": f"{type(exc).__name__}: {exc}",
            "execution_error": True,
        }


def _classify_results(
    original_result: dict[str, Any],
    generated_result: dict[str, Any],
) -> dict[str, Any]:
    """Classify validation outcomes without conflating failure causes."""

    # A timeout prevents a reliable conclusion about installation.
    if (
        original_result.get("timed_out", False)
        or generated_result.get("timed_out", False)
    ):
        return {
            "status": "VALIDATION_TIMEOUT",
            "failure_stage": "installation",
            "preserved": False,
            "reason": "Original or generated package validation timed out.",
        }

    # An exception or malformed result may indicate an infrastructure issue.
    if (
        original_result.get("execution_error", False)
        or generated_result.get("execution_error", False)
    ):
        return {
            "status": "VALIDATION_INCONCLUSIVE",
            "failure_stage": "execution",
            "preserved": False,
            "reason": (
                _error_message(original_result)
                or _error_message(generated_result)
                or "An execution error prevented reliable classification."
            ),
        }

    # Missing return codes make the execution result incomplete.
    if (
        original_result.get("return_code") is None
        or generated_result.get("return_code") is None
    ):
        return {
            "status": "VALIDATION_INCONCLUSIVE",
            "failure_stage": "result_validation",
            "preserved": False,
            "reason": "An execution result has no return_code.",
        }

    original_success = bool(original_result.get("success", False))
    generated_success = bool(generated_result.get("success", False))

    # The baseline must be valid before attributing a failure to mutation.
    if not original_success:
        return {
            "status": "BASELINE_INSTALLATION_FAILED",
            "failure_stage": "baseline_installation",
            "preserved": False,
            "reason": (
                _error_message(original_result)
                or "The original package failed installation validation."
            ),
        }

    if not generated_success:
        return {
            "status": "MUTANT_INSTALLATION_FAILED",
            "failure_stage": "mutant_installation",
            "preserved": False,
            "reason": (
                _error_message(generated_result)
                or "The generated package failed installation validation."
            ),
        }

    return_code_equal = (
        original_result.get("return_code")
        == generated_result.get("return_code")
    )

    if not return_code_equal:
        return {
            "status": "VALIDATION_INCONCLUSIVE",
            "failure_stage": "result_consistency",
            "preserved": False,
            "reason": (
                "Both installations reported success, but their "
                "return codes differ."
            ),
        }

    return {
        "status": "INSTALLATION_PASSED",
        "failure_stage": None,
        "preserved": True,
        "reason": None,
    }


def validate_behavior(
    original_package: Path,
    generated_package: Path,
    environment_root: Path | None = None,
) -> dict[str, Any]:
    """
    Validate installation outcomes for an original/generated package pair.

    Compatibility:
      - Keeps the existing 'preserved', 'method', 'checks',
        'original', 'generated', and 'error' fields.
      - Adds 'status', 'failure_stage', and 'reason'.

    Important:
      INSTALLATION_PASSED only means both installation checks passed.
      It does not establish functional behavior preservation.
    """
    original_package = Path(original_package).resolve()
    generated_package = Path(generated_package).resolve()

    if not original_package.exists() or not original_package.is_dir():
        message = f"Original package directory missing: {original_package}"
        return {
            "preserved": False,
            "method": "package_installation",
            "status": "VALIDATION_INCONCLUSIVE",
            "failure_stage": "input_validation",
            "checks": {},
            "original": None,
            "generated": None,
            "error": message,
            "reason": message,
        }

    if not generated_package.exists() or not generated_package.is_dir():
        message = f"Generated package directory missing: {generated_package}"
        return {
            "preserved": False,
            "method": "package_installation",
            "status": "VALIDATION_INCONCLUSIVE",
            "failure_stage": "input_validation",
            "checks": {},
            "original": None,
            "generated": None,
            "error": message,
            "reason": message,
        }

    if environment_root is None:
        environment_root = (
            generated_package.parent / ".validation_environments"
        )

    environment_root = Path(environment_root).resolve()

    try:
        environment_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        message = (
            f"Could not prepare validation environment directory: "
            f"{type(exc).__name__}: {exc}"
        )
        return {
            "preserved": False,
            "method": "package_installation",
            "status": "VALIDATION_INCONCLUSIVE",
            "failure_stage": "environment_setup",
            "checks": {},
            "original": None,
            "generated": None,
            "error": message,
            "reason": message,
        }

    original_result = _execute_safely(
        original_package,
        environment_root / "original",
    )

    generated_result = _execute_safely(
        generated_package,
        environment_root / "generated",
    )

    classification = _classify_results(
        original_result,
        generated_result,
    )

    original_completed = not bool(
        original_result.get("timed_out", False)
    )
    generated_completed = not bool(
        generated_result.get("timed_out", False)
    )

    original_success = bool(original_result.get("success", False))
    generated_success = bool(generated_result.get("success", False))

    original_return = original_result.get("return_code")
    generated_return = generated_result.get("return_code")

    return_code_equal = (
        original_return is not None
        and generated_return is not None
        and original_return == generated_return
    )

    return {
        "preserved": classification["preserved"],
        "method": "package_installation",
        "status": classification["status"],
        "failure_stage": classification["failure_stage"],
        "checks": {
            "original_completed": original_completed,
            "generated_completed": generated_completed,
            "original_success": original_success,
            "generated_success": generated_success,
            "return_code_equal": return_code_equal,
        },
        "original": original_result,
        "generated": generated_result,
        "error": classification["reason"],
        "reason": classification["reason"],
    }
