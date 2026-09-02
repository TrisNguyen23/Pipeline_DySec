from pathlib import Path

from config.strategies import STRATEGIES
from config.settings import (
    ROUNDS_PER_STRATEGY,
    OUTPUT_DIR,
)

from pipeline.prompt_builder import build_prompt
from pipeline.generator import generate_variant
from pipeline.harness import save_generated_code
from pipeline.executor import execute_and_trace
from pipeline.evaluator import evaluate_trace
from pipeline.validator import validate_behavior
from pipeline.logger import save_json


def run_package(package_name, original_code):
    """
    Run the robustness evaluation for one package.

    Each strategy starts from the original code.
    Within one strategy, each round continues from
    the previously generated variant.

    The experiment stops immediately when:
        behavior_preserved == True
        AND
        DySec == BENIGN
    """

    package_output_dir = (
        OUTPUT_DIR / package_name
    )

    total_attempts = 0

    print(
        f"\n[+] Starting robustness evaluation "
        f"for {package_name}"
    )

    for strategy in STRATEGIES:

        strategy_name = strategy["name"]

        print()
        print("-" * 65)
        print(f"STRATEGY: {strategy_name}")
        print("-" * 65)

        # IMPORTANT:
        # Every new strategy starts from the original code.
        current_code = original_code

        for round_number in range(
            1,
            ROUNDS_PER_STRATEGY + 1
        ):

            total_attempts += 1

            round_dir = (
                package_output_dir
                / strategy_name
                / f"round_{round_number:02d}"
            )

            round_dir.mkdir(
                parents=True,
                exist_ok=True
            )

            print()
            print(
                f">>> Round "
                f"{round_number}/{ROUNDS_PER_STRATEGY}"
            )
            print(
                f"    Attempt: {total_attempts}"
            )
            prompt = build_prompt(
                strategy=strategy,
                source_code=current_code,
            )

            prompt_file = round_dir / "prompt.txt"

            save_text(
                prompt_file,
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

                result = {
                    "package": package_name,
                    "strategy": strategy_name,
                    "round": round_number,
                    "attempt": total_attempts,
                    "status": "GENERATION_ERROR",
                    "behavior_preserved": False,
                    "dysec_verdict": None,
                    "error": generation["error"],
                }

                save_json(
                    round_dir / "result.json",
                    result,
                )

                return {
                    "package": package_name,
                    "strategy": strategy_name,
                    "round": round_number,
                    "attempt": total_attempts,
                    "status": "GENERATION_ERROR",
                    "error": generation["error"],
                }

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
            )

            behavior_preserved = behavior.get(
                "preserved",
                False
            )

            print(
                "[3] Behavior validation:"
                f" {behavior_preserved}"
            )

            trace_file = (
                round_dir / "trace.trace"
            )

            execution = execute_and_trace(
                code_path=generated_file,
                trace_path=trace_file,
            )

            if not execution["success"]:

                print(
                    "[-] Execution failed."
                )

                result = {
                    "package": package_name,
                    "strategy": strategy_name,
                    "round": round_number,
                    "attempt": total_attempts,
                    "status": "EXECUTION_ERROR",
                    "behavior_preserved": behavior_preserved,
                    "behavior_similarity": behavior.get(
                        "similarity"
                    ),
                    "dysec_verdict": None,
                    "execution": execution,
                }

                save_json(
                    round_dir / "result.json",
                    result,
                )

                return {
                    "package": package_name,
                    "strategy": strategy_name,
                    "round": round_number,
                    "attempt": total_attempts,
                    "status": "EXECUTION_ERROR",
                    "error": execution.get("error"),
                }

            print(
                "[4] Execution + tracing completed."
            )

            # ==================================================
            # 6. Evaluate with DySec
            # ==================================================

            dysec_result = evaluate_trace(
                trace_path
            )

            dysec_verdict = str(
                dysec_result.get(
                    "verdict",
                    "UNKNOWN"
                )
            ).upper()

            print(
                f"[5] DySec verdict: "
                f"{dysec_verdict}"
            )

            # ==================================================
            # 7. Determine result
            # ==================================================

            if (
                behavior_preserved
                and dysec_verdict == "BENIGN"
            ):

                status = "SUCCESSFUL_EVASION"

            elif not behavior_preserved:

                status = "BEHAVIOR_NOT_PRESERVED"

            elif dysec_verdict == "MALICIOUS":

                status = "DETECTED"

            else:

                status = "UNKNOWN"

            # ==================================================
            # 8. Save round result
            # ==================================================

            result = {
                "package": package_name,
                "strategy": strategy_name,
                "round": round_number,
                "attempt": total_attempts,

                "status": status,

                "behavior_preserved": behavior_preserved,
                "behavior_similarity": behavior.get(
                    "similarity"
                ),
                "behavior_validation_method": behavior.get(
                    "method"
                ),

                "dysec_verdict": dysec_verdict,
                "dysec_prediction": dysec_result.get(
                    "prediction"
                ),
                "dysec_confidence": dysec_result.get(
                    "confidence"
                ),
                "total_syscalls": dysec_result.get(
                    "total_syscalls"
                ),

                "execution": execution,
            }

            save_json(
                round_dir / "result.json",
                result,
            )

            # ==================================================
            # 9. Check stopping condition
            # ==================================================

            if status == "SUCCESSFUL_EVASION":

                print()
                print("=" * 65)
                print("       SUCCESSFUL EVASION FOUND")
                print("=" * 65)

                print(
                    f"Package   : {package_name}"
                )
                print(
                    f"Strategy  : {strategy_name}"
                )
                print(
                    f"Round     : {round_number}"
                )
                print(
                    f"Attempts  : {total_attempts}"
                )
                print(
                    f"DySec     : {dysec_verdict}"
                )
                print(
                    f"Behavior  : PRESERVED"
                )

                print("=" * 65)

                return {
                    "package": package_name,
                    "strategy": strategy_name,
                    "round": round_number,
                    "attempt": total_attempts,
                    "dysec_verdict": dysec_verdict,
                    "behavior_preserved": True,
                    "status": "SUCCESSFUL_EVASION",
                    "total_attempts": total_attempts,
                }

            # ==================================================
            # 10. Continue same strategy
            # ==================================================

            print(
                f"[+] Result: {status}"
            )

            if (
                round_number
                < ROUNDS_PER_STRATEGY
            ):

                print(
                    "[+] Continuing with generated "
                    "variant for next round."
                )

                current_code = generated_code

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
    print("       ALL STRATEGIES EXHAUSTED")
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
        "dysec_verdict": "MALICIOUS",
        "behavior_preserved": None,
        "status": "ALL_STRATEGIES_EXHAUSTED",
        "total_attempts": total_attempts,
    }

    save_json(
        package_output_dir / "summary.json",
        summary,
    )

    return summary