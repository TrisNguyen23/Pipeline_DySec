from __future__ import annotations

import shutil
from pathlib import Path
import os

from config.settings import (
    OUTPUT_DIR,
    ROUNDS_PER_STRATEGY,
    TRACE_DIR,
    SANDBOX_TIMEOUT,
    SANDBOX_USER,
    TRACE_WINDOW,
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

from pipeline.trace_runner import (
    trace_package,
)

from pipeline.evaluator import (
    evaluate_trace,
)

from pipeline.logger import (
    save_json,
    save_text,
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

    archive_path = Path(
        archive_path
    ).resolve()

    package_output = (
        OUTPUT_DIR
        / package_name
    )

    if package_output.exists():
        shutil.rmtree(
            package_output
        )

    package_output.mkdir(
        parents=True,
        exist_ok=True,
    )

    original_dir = (
        package_output
        / "original"
    )

    original_root = extract_package(
        archive_path,
        original_dir,
    )

    total_attempts = 0

    for strategy in STRATEGIES:

        strategy_name = strategy["name"]

        current_package = original_root

        for round_number in range(
            1,
            ROUNDS_PER_STRATEGY + 1,
        ):

            total_attempts += 1

            round_dir = (
                package_output
                / strategy_name
                / f"round_{round_number:02d}"
            )

            round_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

            # ----------------------------------------------------------
            # 1. Find source code
            # ----------------------------------------------------------

            target_file = _find_target_source(
                current_package
            )

            relative_path = str(
                target_file.relative_to(
                    current_package
                )
            )

            source_code = target_file.read_text(
                encoding="utf-8",
                errors="replace",
            )

            # ----------------------------------------------------------
            # 2. Build prompt
            # ----------------------------------------------------------

            prompt = build_prompt(
                strategy=strategy,
                relative_path=relative_path,
                source_code=source_code,
            )

            save_text(
                round_dir / "prompt.txt",
                prompt,
            )

            # ----------------------------------------------------------
            # 3. Generate variant
            # ----------------------------------------------------------

            generation = generate_variant(
                prompt
            )

            if not generation["success"]:

                result = {
                    "package": package_name,
                    "strategy": strategy_name,
                    "round": round_number,
                    "status": "GENERATION_ERROR",
                    "error": generation["error"],
                }

                save_json(
                    round_dir / "result.json",
                    result,
                )

                continue

            # ----------------------------------------------------------
            # 4. Create generated package
            # ----------------------------------------------------------

            generated_package = (
                round_dir
                / "package"
            )

            copy_package(
                current_package,
                generated_package,
            )

            generated_target = (
                generated_package
                / relative_path
            )

            generated_target.write_text(
                generation["code"],
                encoding="utf-8",
            )

            save_text(
                round_dir / "generated_code.py",
                generation["code"],
            )

            # ----------------------------------------------------------
            # 5. Validate behaviour
            # ----------------------------------------------------------

            behavior = validate_behavior(
                original_package=original_root,
                generated_package=generated_package,
            )

            if not behavior["preserved"]:

                result = {
                    "package": package_name,
                    "strategy": strategy_name,
                    "round": round_number,
                    "status": (
                        "BEHAVIOR_NOT_PRESERVED"
                    ),
                    "behavior_preserved": False,
                    "behavior_validation": behavior,
                }

                save_json(
                    round_dir / "result.json",
                    result,
                )

                continue

            # ----------------------------------------------------------
            # 6. Dynamic tracing
            # ----------------------------------------------------------

            trace_directory = _trace_path(
                package_name,
                strategy_name,
                round_number,
            )

            try:

                trace_result = trace_package(
                    package_dir=generated_package,
                    trace_dir=trace_directory,
                    sandbox_user=SANDBOX_USER,
                    window=TRACE_WINDOW,
                )

            except Exception as exc:

                result = {
                    "package": package_name,
                    "strategy": strategy_name,
                    "round": round_number,
                    "status": "TRACING_ERROR",
                    "behavior_preserved": True,
                    "behavior_validation": behavior,
                    "error": str(exc),
                }

                save_json(
                    round_dir / "result.json",
                    result,
                )

                continue

            save_json(
                round_dir / "trace_result.json",
                trace_result,
            )

            if not trace_result["install_success"]:

                result = {
                    "package": package_name,
                    "strategy": strategy_name,
                    "round": round_number,
                    "status": "TRACE_INSTALL_ERROR",
                    "behavior_preserved": True,
                    "behavior_validation": behavior,
                    "trace_result": trace_result,
                }

                save_json(
                    round_dir / "result.json",
                    result,
                )

                continue

            if not trace_result["trace_available"]:

                result = {
                    "package": package_name,
                    "strategy": strategy_name,
                    "round": round_number,
                    "status": "NO_TRACE",
                    "behavior_preserved": True,
                    "behavior_validation": behavior,
                    "trace_result": trace_result,
                }

                save_json(
                    round_dir / "result.json",
                    result,
                )

                continue

            # ----------------------------------------------------------
            # 7. DySec classification
            # ----------------------------------------------------------

            try:

                dysec_result = evaluate_trace(
                    trace_directory
                )

            except Exception as exc:

                result = {
                    "package": package_name,
                    "strategy": strategy_name,
                    "round": round_number,
                    "status": "DYSEC_ERROR",
                    "behavior_preserved": True,
                    "behavior_validation": behavior,
                    "trace_result": trace_result,
                    "error": str(exc),
                }

                save_json(
                    round_dir / "result.json",
                    result,
                )

                continue

            # ----------------------------------------------------------
            # 8. Save result
            # ----------------------------------------------------------

            verdict = str(
                dysec_result.get(
                    "verdict",
                    "UNKNOWN",
                )
            ).upper()

            if verdict == "BENIGN":

                result = {
                    "package": package_name,
                    "strategy": strategy_name,
                    "round": round_number,
                    "status": "SUCCESSFUL_EVASION",
                    "behavior_preserved": True,
                    "behavior_validation": behavior,
                    "trace_result": trace_result,
                    "dysec_verdict": verdict,
                    "dysec_result": dysec_result,
                }

                save_json(
                    round_dir / "result.json",
                    result,
                )

                summary = {
                    **result,
                    "total_attempts": total_attempts,
                }

                save_json(
                    package_output / "summary.json",
                    summary,
                )

                return summary

            # ----------------------------------------------------------
            # 9. Detected → continue to next round
            # ----------------------------------------------------------

            result = {
                "package": package_name,
                "strategy": strategy_name,
                "round": round_number,
                "status": "DETECTED",
                "behavior_preserved": True,
                "behavior_validation": behavior,
                "trace_result": trace_result,
                "dysec_verdict": verdict,
                "dysec_result": dysec_result,
            }

            save_json(
                round_dir / "result.json",
                result,
            )

            current_package = generated_package

    # --------------------------------------------------------------
    # 10. All strategies exhausted
    # --------------------------------------------------------------

    summary = {
        "package": package_name,
        "strategy": None,
        "round": None,
        "status": "ALL_STRATEGIES_EXHAUSTED",
        "total_attempts": total_attempts,
        "dysec_verdict": None,
    }

    save_json(
        package_output / "summary.json",
        summary,
    )

    return summary