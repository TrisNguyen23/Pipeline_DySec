from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from config.settings import (
    EXPERIMENT_ROUNDS,
    OUTPUT_DIR,
    PYTHON_EXECUTABLE,
    SANDBOX_USER,
    TRACE_DIR,
    TRACE_WINDOW,
)
from pipeline.diversity_checker import (
    analyze_diversity,
)
from pipeline.generator import (
    generate_variant,
)
from pipeline.mutation_planner import (
    build_mutation_plan,
)
from pipeline.package_loader import (
    collect_transformable_python_files,
    copy_package,
    create_package_archive,
    extract_package,
)
from pipeline.prompt_builder import (
    build_prompt,
)
from pipeline.source_guard import (
    source_change_guard,
)
from pipeline.trace_runner import (
    trace_package,
)
from pipeline.validator import (
    validate_behavior,
)
SUPPORTED_METHODS = {
    "proposed",
    "function_level",
}


def _save_json(
    path: Path,
    data: dict,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )


def _save_text(
    path: Path,
    text: str,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        text,
        encoding="utf-8",
    )


def _select_target_source(
    package_root: Path,
) -> Path:
    candidates = (
        collect_transformable_python_files(
            package_root
        )
    )

    if not candidates:
        raise RuntimeError(
            "NO_TRANSFORMABLE_SOURCE: "
            "package contains no Python source "
            "available for controlled analysis."
        )

    setup_py = package_root / "setup.py"

    if setup_py in candidates:
        return setup_py

    candidates.sort(
        key=lambda path: (
            -len(
                path.read_text(
                    encoding="utf-8",
                    errors="replace",
                ).splitlines()
            ),
            str(path),
        )
    )

    return candidates[0]


def _run_evaluator(
    trace_directory: Path,
    package_name: str,
    round_directory: Path,
) -> dict:
    evaluator_json = (
        round_directory
        / "dysec_result.json"
    )

    command = [
        PYTHON_EXECUTABLE,
        "-m",
        "pipeline.evaluator",
        "--trace-dir",
        str(trace_directory),
        "--package-name",
        package_name,
        "--model-dir",
        "models/rf",
        "--schema-path",
        "models/rf/Combined_schema.json",
        "--save-json",
        str(evaluator_json),
    ]

    completed = subprocess.run(
        command,
        cwd=str(
            Path(__file__).resolve().parent.parent
        ),
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )

    result = {
        "return_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "command": command,
        "success": (
            completed.returncode == 0
        ),
        "result_file": str(
            evaluator_json
        ),
    }

    if evaluator_json.exists():
        try:
            result["prediction"] = json.loads(
                evaluator_json.read_text(
                    encoding="utf-8"
                )
            )
        except json.JSONDecodeError:
            result["prediction"] = None

    return result


def _write_result(
    round_directory: Path,
    result: dict,
) -> None:
    _save_json(
        round_directory
        / "result.json",
        result,
    )


def _create_round_archive(
    generated_package: Path,
    package_name: str,
    round_number: int,
    round_directory: Path,
) -> dict:
    """
    Create the package artifact independently of local DySec
    tracing/inference.

    This artifact is intended for the separate DySec.io evaluation
    path and therefore must not depend on the local RF verdict.
    """

    archive_output = (
        round_directory
        / (
            f"{package_name}"
            f"_round_{round_number:02d}"
            f".tar.gz"
        )
    )

    create_package_archive(
        generated_package,
        archive_output,
    )

    return {
        "created": archive_output.exists(),
        "path": str(
            archive_output
        ),
        "filename": archive_output.name,
        "size_bytes": (
            archive_output.stat().st_size
            if archive_output.exists()
            else None
        ),
        "purpose": (
            "Independent package artifact "
            "for DySec.io evaluation."
        ),
    }


def run_package(
    archive_path: Path,
    method: str = "proposed",
) -> dict:
    if method not in SUPPORTED_METHODS:
        raise ValueError(
            f"Unsupported method: {method}. "
            f"Expected one of {sorted(SUPPORTED_METHODS)}."
        )
    archive_path = Path(
        archive_path
    ).resolve()

    package_name = archive_path.name

    if package_name.endswith(
        ".tar.gz"
    ):
        package_name = package_name[
            :-7
        ]

    package_output = (
        OUTPUT_DIR / package_name
    )

    if package_output.exists():
        shutil.rmtree(
            package_output
        )

    package_output.mkdir(
        parents=True,
        exist_ok=True,
    )

    original_extract = (
        package_output / "original_extract"
    )

    original_root = extract_package(
        archive_path,
        original_extract,
    )

    original_snapshot = (
        package_output / "original"
    )

    copy_package(
        original_root,
        original_snapshot,
    )

    current_package = (
        package_output / "current"
    )

    copy_package(
        original_root,
        current_package,
    )

    history: list[dict] = []

    summary = {
        "package": package_name,
        "archive": str(archive_path),
        "method": method,
        "experiment_rounds": (
            EXPERIMENT_ROUNDS
        ),
        "status": "RUNNING",
        "rounds": [],
        "evaluation_paths": {
            "local": {
                "enabled": True,
                "evaluator": (
                    "Combined RF bundle"
                ),
            },
            "dysec_io": {
                "enabled": True,
                "method": "manual upload",
            },
        },
    }

    for round_number in range(
        1,
        EXPERIMENT_ROUNDS + 1,
    ):
        round_directory = (
            package_output
            / f"round_{round_number:02d}"
        )

        round_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        result = {
            "package": package_name,
            "round": round_number,
            "method": method,
            "status": "RUNNING",
        }

        try:
            # =====================================================
            # 1. Select source to mutate
            # =====================================================

            target_source = (
                _select_target_source(
                    current_package
                )
            )

            relative_path = (
                target_source
                .relative_to(current_package)
            )

            original_source = (
                target_source.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            )

            _save_text(
                round_directory
                / "original_source.py",
                original_source,
            )

            # =====================================================
            # 2. Build progressive mutation plan
            # =====================================================

            mutation_plan = (
                build_mutation_plan(
                    original_source,
                    round_number,
                    source_path=target_source,
                )
            )

            _save_json(
                round_directory
                / "mutation_plan.json",
                mutation_plan,
            )

            # =====================================================
            # 3. Generate source variant with Qwen
            # =====================================================

            prompt = build_prompt(
                relative_path=str(
                    relative_path
                ),
                source_code=original_source,
                round_number=round_number,
                mutation_plan=mutation_plan,
                feedback_history=history,
            )

            _save_text(
                round_directory
                / "prompt.txt",
                prompt,
            )

            generation = generate_variant(
                prompt
            )

            _save_json(
                round_directory
                / "generation_metadata.json",
                {
                    "success": generation[
                        "success"
                    ],
                    "tokens": generation.get(
                        "tokens",
                        {},
                    ),
                    "response_metadata": (
                        generation.get(
                            "response_metadata",
                            {},
                        )
                    ),
                    "error": generation.get(
                        "error"
                    ),
                },
            )

            if not generation["success"]:
                result.update(
                    {
                        "status": "GENERATION_ERROR",
                        "error": generation.get(
                            "error"
                        ),
                    }
                )

                _write_result(
                    round_directory,
                    result,
                )

                summary["rounds"].append(
                    result
                )

                continue

            generated_source = (
                generation["code"]
            )

            _save_text(
                round_directory
                / "generated_code.py",
                generated_source,
            )

                   # =====================================================
            # 4. Source-change guard
            #
            # Diagnostic only.
            #
            # The guard measures how much the generated source
            # differs from the current variant, but it does not
            # reject the candidate. Candidate validity is decided
            # by diversity and behaviour validation below.
            # =====================================================

            guard = source_change_guard(
                original_source,
                generated_source,
            )

            _save_json(
                round_directory
                / "source_guard.json",
                guard,
            )

            result["source_guard"] = guard

            # =====================================================
            # 5. Diversity gate
            # =====================================================

            diversity = analyze_diversity(
                original_source,
                generated_source,
                complexity_level=(
                    mutation_plan["level"]
                ),
                profile=(
                    "proposed"
                    if method == "proposed"
                    else "function_level"
                )
            )

            diversity_data = (
                diversity.__dict__
                if hasattr(
                    diversity,
                    "__dict__",
                )
                else diversity
            )

            _save_json(
                round_directory
                / "diversity.json",
                diversity_data,
            )

            if not diversity.accepted:
                result.update(
                    {
                        "status": "DIVERSITY_REJECTED",
                        "error": (
                            "Generated variant did not "
                            "meet the diversity gate."
                        ),
                    }
                )

                _write_result(
                    round_directory,
                    result,
                )

                summary["rounds"].append(
                    result
                )

                continue

            # =====================================================
            # 6. Build generated package
            # =====================================================

            generated_package = (
                round_directory / "package"
            )

            copy_package(
                current_package,
                generated_package,
            )

            generated_target = (
                generated_package
                / relative_path
            )

            generated_target.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            generated_target.write_text(
                generated_source,
                encoding="utf-8",
            )

            # =====================================================
            # 7. Behaviour validation
            # =====================================================

            behavior = validate_behavior(
                original_snapshot,
                generated_package,
                environment_root=(
                    round_directory
                    / ".validation_environments"
                ),
            )

            _save_json(
                round_directory
                / "behavior.json",
                behavior,
            )

            if not behavior.get(
                "preserved",
                False,
            ):
                result.update(
                    {
                        "status": (
                            "BEHAVIOR_VALIDATION_FAILED"
                        ),
                        "error": (
                            "Generated package did not "
                            "preserve the required "
                            "installation/return-code "
                            "behaviour."
                        ),
                    }
                )

                _write_result(
                    round_directory,
                    result,
                )

                summary["rounds"].append(
                    result
                )

                continue

            # =====================================================
            # 8. Create DySec.io artifact
            #
            # IMPORTANT:
            # This happens BEFORE local tracing/inference.
            # Therefore a local evaluator failure does not
            # destroy the independent external-evaluation
            # artifact.
            # =====================================================

            artifact = _create_round_archive(
                generated_package,
                package_name,
                round_number,
                round_directory,
            )

            _save_json(
                round_directory
                / "artifact.json",
                artifact,
            )

            result["artifact"] = artifact

            # =====================================================
            # 9. Local dynamic tracing
            # =====================================================

            trace_directory = (
                TRACE_DIR
                / package_name
                / f"round_{round_number:02d}"
            )

            trace = trace_package(
                generated_package,
                trace_directory,
                SANDBOX_USER,
                TRACE_WINDOW,
            )

            _save_json(
                round_directory
                / "trace.json",
                trace,
            )

            if not trace.get(
                "trace_available",
                False,
            ):
                result.update(
                    {
                        "status": "TRACE_ERROR",
                        "error": (
                            "No usable trace was "
                            "produced. The DySec.io "
                            "artifact remains available "
                            "for independent evaluation."
                        ),
                    }
                )

                _write_result(
                    round_directory,
                    result,
                )

                summary["rounds"].append(
                    result
                )

                continue

            # =====================================================
            # 10. Local DySec Combined RF evaluation
            # =====================================================

            evaluation = _run_evaluator(
                trace_directory,
                package_name,
                round_directory,
            )

            # Keep local evaluation separate from artifact
            # generation and external DySec.io evaluation.
            result["local_evaluation"] = evaluation

            if not evaluation[
                "success"
            ]:
                result.update(
                    {
                        "status": "DYSEC_EVALUATION_ERROR",
                        "error": (
                            "Local DySec evaluation failed. "
                            "The generated artifact remains "
                            "available for independent "
                            "DySec.io evaluation."
                        ),
                    }
                )

                _write_result(
                    round_directory,
                    result,
                )

                summary["rounds"].append(
                    result
                )

                continue

            prediction = evaluation.get(
                "prediction"
            )

            verdict = (
                prediction.get("verdict")
                if isinstance(
                    prediction,
                    dict,
                )
                else None
            )

            result.update(
                {
                    "status": (
                        "SUCCESSFUL_EVASION"
                        if verdict == "BENIGN"
                        else "DETECTED"
                    ),
                    "local_verdict": verdict,
                }
            )

            _write_result(
                round_directory,
                result,
            )

            summary["rounds"].append(
                result
            )

            # =====================================================
            # 11. Stop if local DySec considers it benign
            #
            # Do NOT use p_malicious as a stopping criterion.
            # =====================================================

            if verdict == "BENIGN":
                summary[
                    "status"
                ] = "SUCCESSFUL_EVASION"

                summary[
                    "successful_round"
                ] = round_number

                break

            # =====================================================
            # 12. Promote only a valid, behaviour-preserving,
            #     locally detected variant to the next round.
            # =====================================================

            copy_package(
                generated_package,
                current_package,
            )

            history.append(
                {
                    "round": round_number,
                    "operations": mutation_plan[
                        "operations"
                    ],
                    "target_type": mutation_plan.get(
                        "target_type"
                    ),
                    "target_source": mutation_plan.get(
                        "target_source"
                    ),
                    "target_functions": (
                        mutation_plan[
                            "target_functions"
                        ]
                    ),
                }
            )

        except Exception as exc:
            result.update(
                {
                    "status": "PIPELINE_ERROR",
                    "error": str(exc),
                }
            )

            _write_result(
                round_directory,
                result,
            )

            summary["rounds"].append(
                result
            )

            continue

    else:
        summary["status"] = (
            "ALL_ROUNDS_EXHAUSTED"
        )

    _save_json(
        package_output / "summary.json",
        summary,
    )

    return summary