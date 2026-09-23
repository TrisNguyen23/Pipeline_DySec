from __future__ import annotations

import shutil
from pathlib import Path

from config.settings import (
    OUTPUT_DIR,
    ROUNDS_PER_STRATEGY,
    TRACE_DIR,
    SANDBOX_TIMEOUT,
)

from config.strategies import STRATEGIES

from pipeline.package_loader import (
    extract_package,
    collect_python_files,
)

from pipeline.prompt_builder import (
    build_prompt,
)

from pipeline.generator import (
    generate_variant,
)

from pipeline.harness import (
    copy_package,
)

from pipeline.validator import (
    validate_behavior,
)

from pipeline.executor import (
    execute_package,
)

from pipeline.evaluator import (
    evaluate_trace,
)

from pipeline.logger import (
    save_json,
    save_text,
)

from pipeline.trace_runner import (
    trace_package,
)

def _find_target_source(
    package_root: Path,
) -> Path:

    python_files = collect_python_files(
        package_root
    )

    if not python_files:
        raise RuntimeError(
            f"No Python source files found in "
            f"{package_root}"
        )

    return python_files[0]


def _trace_path(
    package_name: str,
    strategy_name: str,
    round_number: int,
) -> Path:

    return (
        TRACE_DIR
        / package_name
        / strategy_name
        / f"round_{round_number:02d}"
    )


def run_package(
    package_name: str,
    archive_path: Path,
) -> dict:

    archive_path = Path(archive_path).resolve()
    package_output = OUTPUT_DIR / package_name

    if package_output.exists():
        shutil.rmtree(package_output)

    package_output.mkdir(parents=True, exist_ok=True)
    original_dir = package_output / "original"
    original_root = extract_package(archive_path, original_dir)

    total_attempts = 0

    for strategy in STRATEGIES:
        strategy_name = strategy["name"]
        current_package = original_root

        for round_number in range(1, ROUNDS_PER_STRATEGY + 1):
            total_attempts += 1
            round_dir = package_output / strategy_name / f"round_{round_number:02d}"
            round_dir.mkdir(parents=True, exist_ok=True)

            target_file = _find_target_source(current_package)
            relative_path = str(target_file.relative_to(current_package))
            source_code = target_file.read_text(encoding="utf-8", errors="replace")

            prompt = build_prompt(
                strategy=strategy,
                relative_path=relative_path,
                source_code=source_code,
            )
            save_text(round_dir / "prompt.txt", prompt)

            generation = generate_variant(prompt)
            if not generation["success"]:
                result = {
                    "package": package_name,
                    "strategy": strategy_name,
                    "round": round_number,
                    "status": "GENERATION_ERROR",
                    "error": generation["error"],
                }
                save_json(round_dir / "result.json", result)
                return result

            generated_package = round_dir / "package"
            copy_package(current_package, generated_package)

            generated_target = generated_package / relative_path
            generated_target.write_text(generation["code"], encoding="utf-8")

            behavior = validate_behavior(
                original_package=original_root,
                generated_package=generated_package,
            )

            if not behavior["preserved"]:
                result = {
                    "package": package_name,
                    "strategy": strategy_name,
                    "round": round_number,
                    "status": "BEHAVIOR_NOT_PRESERVED",
                    "behavior_preserved": False,
                    "behavior_validation": behavior,
                }
                save_json(round_dir / "result.json", result)
                continue

            trace_directory = _trace_path(package_name, strategy_name, round_number)
            trace_directory.mkdir(parents=True, exist_ok=True)

            print(f"[LOOP] Running trace_package for {package_name} - {strategy_name} - round_{round_number:02d}...")
            trace_result = trace_package(
                package_dir=generated_package,
                trace_dir=trace_directory,
                sandbox_user="sandbox",
                window=120,
            )
            print(f"[LOOP] Trace status: {trace_result}")

            if not trace_result.get("trace_available", False):
                result = {
                    "package": package_name,
                    "strategy": strategy_name,
                    "round": round_number,
                    "status": "TRACE_ERROR",
                    "behavior_preserved": True,
                    "behavior_validation": behavior,
                    "trace": trace_result,
                }
                save_json(round_dir / "result.json", result)
                continue

            try:
                dysec_result = evaluate_trace(trace_directory)
            except Exception as exc:
                result = {
                    "package": package_name,
                    "strategy": strategy_name,
                    "round": round_number,
                    "status": "DYSEC_ERROR",
                    "behavior_preserved": True,
                    "behavior_validation": behavior,
                    "trace": trace_result,
                    "error": str(exc),
                }
                save_json(round_dir / "result.json", result)
                continue

            verdict = str(dysec_result.get("verdict", "UNKNOWN")).upper()

            if verdict == "BENIGN":
                result = {
                    "package": package_name,
                    "strategy": strategy_name,
                    "round": round_number,
                    "status": "SUCCESSFUL_EVASION",
                    "behavior_preserved": True,
                    "dysec_verdict": verdict,
                    "dysec_result": dysec_result,
                }
                save_json(round_dir / "result.json", result)
                summary = {**result, "total_attempts": total_attempts}
                save_json(package_output / "summary.json", summary)
                return summary

            result = {
                "package": package_name,
                "strategy": strategy_name,
                "round": round_number,
                "status": "DETECTED",
                "behavior_preserved": True,
                "dysec_verdict": verdict,
                "dysec_result": dysec_result,
            }
            save_json(round_dir / "result.json", result)

            # Cập nhật base package cho round tiếp theo
            current_package = generated_package

    summary = {
        "package": package_name,
        "strategy": None,
        "round": None,
        "status": "ALL_STRATEGIES_EXHAUSTED",
        "total_attempts": total_attempts,
        "dysec_verdict": None,
    }
    save_json(package_output / "summary.json", summary)
    return summary