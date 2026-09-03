from __future__ import annotations

from pathlib import Path

from config.settings import VALIDATION_TIMEOUT
from pipeline.executor import execute_python


def _normalise_output(value) -> str:
    """
    Normalise process output only for line-ending differences.
    """

    if value is None:
        return ""

    return str(value).replace(
        "\r\n",
        "\n",
    )


def validate_behavior(
    original_code: str,
    generated_code: str,
    original_path: Path | None = None,
    generated_path: Path | None = None,
) -> dict:
    """
    Validate generated behaviour by executing both programs.

    The original and generated programs are executed independently.

    Behaviour is considered preserved when:
      1. neither execution times out;
      2. both executions have the same success state;
      3. both executions have the same return code;
      4. stdout is identical;
      5. stderr is identical.

    If file paths are supplied, those files are executed directly.

    If paths are not supplied, temporary files are created from the
    supplied source code.
    """

    if original_path is None:
        raise ValueError(
            "original_path is required for real execution."
        )

    if generated_path is None:
        raise ValueError(
            "generated_path is required for real execution."
        )

    original_path = Path(
        original_path
    ).resolve()

    generated_path = Path(
        generated_path
    ).resolve()

    if not original_path.exists():
        return {
            "preserved": False,
            "method": "execution",
            "error": (
                f"Original program does not exist: "
                f"{original_path}"
            ),
        }

    if not generated_path.exists():
        return {
            "preserved": False,
            "method": "execution",
            "error": (
                f"Generated program does not exist: "
                f"{generated_path}"
            ),
        }

    original_result = execute_python(
        code_path=original_path,
        timeout=VALIDATION_TIMEOUT,
        working_directory=original_path.parent,
    )

    generated_result = execute_python(
        code_path=generated_path,
        timeout=VALIDATION_TIMEOUT,
        working_directory=generated_path.parent,
    )

    original_stdout = _normalise_output(
        original_result.get("stdout")
    )

    generated_stdout = _normalise_output(
        generated_result.get("stdout")
    )

    original_stderr = _normalise_output(
        original_result.get("stderr")
    )

    generated_stderr = _normalise_output(
        generated_result.get("stderr")
    )

    original_success = bool(
        original_result.get("success")
    )

    generated_success = bool(
        generated_result.get("success")
    )

    original_return_code = (
        original_result.get("return_code")
    )

    generated_return_code = (
        generated_result.get("return_code")
    )

    original_timeout = bool(
        original_result.get("timed_out")
    )

    generated_timeout = bool(
        generated_result.get("timed_out")
    )

    checks = {
        "original_completed": not original_timeout,
        "generated_completed": not generated_timeout,
        "success_equal": (
            original_success
            == generated_success
        ),
        "return_code_equal": (
            original_return_code
            == generated_return_code
        ),
        "stdout_equal": (
            original_stdout
            == generated_stdout
        ),
        "stderr_equal": (
            original_stderr
            == generated_stderr
        ),
    }

    preserved = all(checks.values())

    return {
        "preserved": preserved,
        "method": "execution",
        "checks": checks,
        "original": original_result,
        "generated": generated_result,
        "error": None,
    }