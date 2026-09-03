from __future__ import annotations

from pathlib import Path

from config.strategies import STRATEGIES
from config.settings import (
    OUTPUT_DIR,
    ROUNDS_PER_STRATEGY,
    TRACE_DIR,
    SANDBOX_TIMEOUT,
)

from pipeline.prompt_builder import build_prompt
from pipeline.generator import generate_variant
from pipeline.harness import save_generated_code
from pipeline.executor import execute_python
from pipeline.evaluator import evaluate_trace
from pipeline.validator import validate_behavior
from pipeline.logger import save_json, save_text


def _get_external_trace_path(
    package_name: str,
    strategy_name: str,
    round_number: int,
) -> Path:
    """
    Resolve the trace supplied by the external tracing stage.

    Expected location:

        traces/
            <package_name>/
                <strategy_name>/
                    round_XX/
                        trace.trace
    """

    return (
        TRACE_DIR
        / package_name
        / strategy_name
        / f"round_{round_number:02d}"
        / "trace.trace"
    )


def _save_failure(
    round_dir: Path,
    package_name: str,
    strategy_name: str,
    round_number: int,
    attempt: int,
    status: str,
    **extra,
) -> dict:

    result = {
        "package": package_name,
        "strategy": strategy_name,
        "round": round_number,
        "attempt": attempt,
        "status": status,
        **extra,
    }

    save_json(
        round_dir / "result.json",
        result,
    )

    return result


def run_package(
    package_name: str,
    original_code: str,
    original_path: Path,
):
    """
    Run the complete robustness evaluation for one package.

    Tracing is external to this pipeline.

    Each strategy starts from the original source.
    Within a strategy, the next round uses the previous
    generated variant.

    The experiment stops when:

        behavior_preserved == True
        AND
        DySec verdict == BENIGN
    """

    original_path = Path(
        original_path
    ).resolve()

    if not original_path.exists():
        raise FileNotFoundError(
            f"Original package entry point does not exist: "
            f"{original_path}"
        )

    package_output_dir = (
        OUTPUT_DIR / package_name
    )

    total_attempts = 0

    print()
    print("=" * 65)
    print(
        f"STARTING ROBUSTNESS EVALUATION: "
        f"{package_name}"
    )
    print("=" * 65)

    for strategy in STRATEGIES:

        strategy_name = strategy["name"]

        print()
        print("-" * 65)
        print(f"STRATEGY: {strategy_name}")
        print("-" * 65)

        current_code = original_code
        current_code_path = original_path

        for round_number in range(
            1,
            ROUNDS_PER_STRATEGY + 1,
        ):

            total_attempts += 1

            round_dir = (
                package_output_dir
                / strategy_name
                / f"round_{round_number:02d}"
            )

            round_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

            print()
            print(
                f">>> Round "
                f"{round_number}/"
                f"{ROUNDS_PER_STRATEGY}"
            )

            print(
                f"    Attempt: {total_attempts}"
            )

            prompt = build_prompt(
                strategy=strategy,
                source_code=current_code,
            )

            save_text(
                round_dir / "prompt.txt",
                prompt,
            )

            print(
                "[1] Prompt generated."
            )

            generation = generate_variant(
                prompt
            )

            if not generation["success"]:

                print(
                    "[-] LLM generation failed."
                )

                return _save_failure(
                    round_dir,
                    package_name,
                    strategy_name,
                    round_number,
                    total_attempts,
                    "GENERATION_ERROR",
                    behavior_preserved=False,
                    dysec_verdict=None,
                    error=generation["error"],
                )

            generated_code = generation["code"]

            print(
                "[2] Generated variant."
            )

            generated_file = save_generated_code(
                generated_dir=round_dir,
                code=generated_code,
                filename="generated.py",
            )

            print(
                f"[+] Saved: {generated_file}"
            )

            behavior = validate_behavior(
                original_code=original_code,
                generated_code=generated_code,
                original_path=current_code_path,
                generated_path=generated_file,
            )

            behavior_preserved = bool(
                behavior.get(
                    "preserved",
                    False,
                )
            )

            print(
                "[3] Behavior validation: "
                f"{behavior_preserved}"
            )

            if not behavior_preserved:

                result = {
                    "package": package_name,
                    "strategy": strategy_name,
                    "round": round_number,
                    "attempt": total_attempts,
                    "status": "BEHAVIOR_NOT_PRESERVED",
                    "behavior_preserved": False,
                    "behavior_validation": behavior,
                    "dysec_verdict": None,
                }

                save_json(
                    round_dir / "result.json",
                    result,
                )

                print(
                    "[!] Behavior was not preserved."
                )

                # Do not use a behavior-breaking variant
                # as the basis for the next round.
                continue

            execution = execute_python(
                code_path=generated_file,
                timeout=SANDBOX_TIMEOUT,
                working_directory=generated_file.parent,
            )

            if not execution["success"]:

                print(
                    "[-] Generated variant execution failed."
                )

                result = {
                    "package": package_name,
                    "strategy": strategy_name,
                    "round": round_number,
                    "attempt": total_attempts,
                    "status": "EXECUTION_ERROR",
                    "behavior_preserved": True,
                    "behavior_validation": behavior,
                    "dysec_verdict": None,
                    "execution": execution,
                }

                save_json(
                    round_dir / "result.json",
                    result,
                )

                continue

            print(
                "[4] Generated variant executed."
            )

            trace_path = _get_external_trace_path(
                package_name=package_name,
                strategy_name=strategy_name,
                round_number=round_number,
            )

            print(
                f"[5] Looking for external trace:"
            )
            print(
                f"    {trace_path}"
            )

            if not trace_path.exists():

                result = {
                    "package": package_name,
                    "strategy": strategy_name,
                    "round": round_number,
                    "attempt": total_attempts,
                    "status": "TRACE_NOT_AVAILABLE",
                    "behavior_preserved": True,
                    "behavior_validation": behavior,
                    "dysec_verdict": None,
                    "execution": execution,
                    "trace_path": str(trace_path),
                }

                save_json(
                    round_dir / "result.json",
                    result,
                )

                print(
                    "[-] External trace not found."
                )

                continue

            try:

                dysec_result = evaluate_trace(
                    trace_path
                )

            except Exception as exc:

                result = {
                    "package": package_name,
                    "strategy": strategy_name,
                    "round": round_number,
                    "attempt": total_attempts,
                    "status": "DYSEC_ERROR",
                    "behavior_preserved": True,
                    "behavior_validation": behavior,
                    "dysec_verdict": None,
                    "execution": execution,
                    "trace_path": str(trace_path),
                    "error": str(exc),
                }

                save_json(
                    round_dir / "result.json",
                    result,
                )

                print(
                    f"[-] DySec evaluation failed: {exc}"
                )

                continue

            dysec_verdict = str(
                dysec_result.get(
                    "verdict",
                    "UNKNOWN",
                )
            ).upper()

            print(
                f"[6] DySec verdict: "
                f"{dysec_verdict}"
            )

            if dysec_verdict == "BENIGN":

                status = (
                    "SUCCESSFUL_EVASION"
                )

            elif dysec_verdict == "MALICIOUS":

                status = "DETECTED"

            else:

                status = "UNKNOWN"

            result = {
                "package": package_name,
                "strategy": strategy_name,
                "round": round_number,
                "attempt": total_attempts,
                "status": status,

                "behavior_preserved": True,
                "behavior_validation": behavior,

                "dysec_verdict": dysec_verdict,
                "dysec_prediction": dysec_result.get(
                    "prediction"
                ),
                "dysec_confidence": dysec_result.get(
                    "confidence"
                ),

                "trace_path": str(
                    trace_path
                ),

                "execution": execution,
            }

            save_json(
                round_dir / "result.json",
                result,
            )

            if status == "SUCCESSFUL_EVASION":

                print()
                print("=" * 65)
                print(
                    "       SUCCESSFUL EVASION FOUND"
                )
                print("=" * 65)

                print(
                    f"Package  : {package_name}"
                )
                print(
                    f"Strategy : {strategy_name}"
                )
                print(
                    f"Round    : {round_number}"
                )
                print(
                    f"Attempts : {total_attempts}"
                )
                print(
                    f"DySec    : {dysec_verdict}"
                )
                print(
                    "Behavior : PRESERVED"
                )

                print("=" * 65)

                summary = {
                    "package": package_name,
                    "strategy": strategy_name,
                    "round": round_number,
                    "attempt": total_attempts,
                    "dysec_verdict": dysec_verdict,
                    "behavior_preserved": True,
                    "status": status,
                    "total_attempts": total_attempts,
                }

                save_json(
                    package_output_dir
                    / "summary.json",
                    summary,
                )

                return summary

            if (
                round_number
                < ROUNDS_PER_STRATEGY
            ):

                current_code = generated_code
                current_code_path = generated_file

                print(
                    "[+] Continuing with generated "
                    "variant for next round."
                )

        print()
        print(
            f"[!] Strategy {strategy_name} "
            f"exhausted after "
            f"{ROUNDS_PER_STRATEGY} rounds."
        )

        print(
            "[!] Resetting to ORIGINAL code "
            "before next strategy."
        )

    print()
    print("=" * 65)
    print(
        "       ALL STRATEGIES EXHAUSTED"
    )
    print("=" * 65)

    print(
        f"Package  : {package_name}"
    )

    print(
        f"Attempts : {total_attempts}"
    )

    print(
        "DySec successfully evaded: NO"
    )

    print("=" * 65)

    summary = {
        "package": package_name,
        "strategy": None,
        "round": None,
        "attempt": total_attempts,
        "dysec_verdict": None,
        "behavior_preserved": None,
        "status": "ALL_STRATEGIES_EXHAUSTED",
        "total_attempts": total_attempts,
    }

    save_json(
        package_output_dir / "summary.json",
        summary,
    )

    return summary