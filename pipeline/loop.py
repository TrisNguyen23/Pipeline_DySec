from __future__ import annotations

import hashlib
import json
import random
import shutil
from pathlib import Path
from typing import Any

from config.settings import (
    EXPERIMENT_METHODS,
    EXPERIMENT_NAME,
    EXPERIMENT_ROUNDS,
    EXPERIMENT_SEED,
    OUTPUT_DIR,
    PROMPT_VERSION,
    VALIDATION_TYPE,
)

from pipeline.diversity_checker import analyze_diversity
from pipeline.function_selector import find_functions
from pipeline.generator import generate_variant
from pipeline.mutation_planner import build_mutation_plan
from pipeline.package_loader import (
    collect_transformable_python_files,
    copy_package,
    create_package_archive,
    extract_package,
)
from pipeline.prompt_builder import build_prompt
from pipeline.source_guard import source_change_guard
from pipeline.validator import validate_behavior


SUPPORTED_METHODS = set(EXPERIMENT_METHODS)


# ============================================================
# JSON helpers
# ============================================================


def _write_json(
    path: Path,
    data: dict[str, Any],
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False,
        )


def _read_json(
    path: Path,
) -> dict[str, Any] | None:

    if not path.exists():
        return None

    try:
        with path.open(
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        if isinstance(data, dict):
            return data

    except (
        OSError,
        json.JSONDecodeError,
    ):
        return None

    return None


# ============================================================
# Reproducible randomness
# ============================================================


def _build_rng(
    package_name: str,
    method: str,
) -> random.Random:

    seed_material = (
        f"{EXPERIMENT_SEED}:"
        f"{package_name}:"
        f"{method}"
    )

    digest = hashlib.sha256(
        seed_material.encode("utf-8")
    ).digest()

    seed = int.from_bytes(
        digest[:8],
        byteorder="big",
        signed=False,
    )

    return random.Random(seed)


# ============================================================
# Source selection
# ============================================================


def _select_random_source(
    package_root: Path,
    rng: random.Random,
) -> Path | None:

    candidates = (
        collect_transformable_python_files(
            package_root
        )
    )

    if not candidates:
        return None

    return rng.choice(candidates)


def _select_structural_source(
    package_root: Path,
    history: list[dict[str, Any]] | None = None,
) -> Path | None:
    """
    Select a source file containing functions.

    This selector deliberately uses only local source structure.
    It does not use the package-aware candidate score.
    """

    candidates = (
        collect_transformable_python_files(
            package_root
        )
    )

    if not candidates:
        return None

    history = history or []

    attempted_sources = {
        str(entry.get("target_source"))
        for entry in history
        if entry.get("target_source")
    }

    scored: list[tuple[int, int, str, Path]] = []

    for path in candidates:

        try:
            source = path.read_text(
                encoding="utf-8"
            )

            targets = find_functions(
                source
            )

        except (
            OSError,
            UnicodeDecodeError,
            SyntaxError,
        ):
            continue

        function_count = len(
            targets
        )

        line_count = len(
            source.splitlines()
        )

        relative = str(
            path.relative_to(
                package_root
            )
        )

        scored.append(
            (
                function_count,
                line_count,
                relative,
                path,
            )
        )

    if not scored:
        return None

    # Deterministic structural ordering.
    scored.sort(
        key=lambda item: (
            -item[0],
            -item[1],
            item[2],
        )
    )

    for _, _, relative, path in scored:
        if relative not in attempted_sources:
            return path

    return scored[0][3]


# ============================================================
# Function target helpers
# ============================================================


def _find_function_targets(
    source_code: str,
) -> list[dict[str, Any]]:

    try:
        targets = find_functions(
            source_code
        )
    except SyntaxError:
        return []

    return [
        {
            "name": target.name,
            "qualified_name": target.qualified_name,
            "start_line": target.lineno,
            "end_line": target.end_lineno,
        }
        for target in targets
        if not target.name.startswith("__")
    ]


def _select_random_function(
    source_code: str,
    rng: random.Random,
) -> dict[str, Any] | None:

    candidates = _find_function_targets(
        source_code
    )

    if not candidates:
        return None

    return rng.choice(candidates)


def _select_function_level_target(
    source_code: str,
    source_path: str,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:

    candidates = _find_function_targets(
        source_code
    )

    if not candidates:
        return None

    history = history or []

    attempted_targets = {
        (
            str(entry.get("target_source")),
            str(entry.get("target")),
        )
        for entry in history
        if entry.get("target_source")
        and entry.get("target")
    }

    for candidate in candidates:

        key = (
            source_path,
            candidate["qualified_name"],
        )

        if key not in attempted_targets:
            return candidate

    return candidates[0]


# ============================================================
# Mutation-plan builders
# ============================================================


def _build_random_plan(
    source_code: str,
    source_path: str,
    round_number: int,
    rng: random.Random,
) -> dict[str, Any]:

    target = _select_random_function(
        source_code,
        rng,
    )

    if target is None:
        return {
            "round": round_number,
            "method": "random",
            "target_type": None,
            "target": None,
            "target_source": source_path,
            "transformation": None,
            "candidate_score": None,
            "candidate_features": {},
            "package_features": {},
            "reason": (
                "No transformable functions "
                "were found."
            ),
        }

    transformations = (
        "internal_function_refactoring",
        "control_flow_refactoring",
        "expression_refactoring",
    )

    transformation = rng.choice(
        transformations
    )

    return {
        "round": round_number,
        "method": "random",
        "target_type": "function",
        "target": target["qualified_name"],
        "target_source": source_path,
        "target_functions": [target],
        "transformation": transformation,
        "candidate_score": None,
        "candidate_features": {
            "selection": "uniform_random",
            "start_line": target["start_line"],
            "end_line": target["end_line"],
        },
        "package_features": {},
        "reason": (
            "Function target and transformation "
            "were selected uniformly at random."
        ),
    }


def _build_function_level_plan(
    source_code: str,
    source_path: str,
    round_number: int,
    history: list[dict[str, Any]],
    rng: random.Random,
) -> dict[str, Any]:

    target = _select_function_level_target(
        source_code=source_code,
        source_path=source_path,
        history=history,
    )

    if target is None:
        return {
            "round": round_number,
            "method": "function_level",
            "target_type": None,
            "target": None,
            "target_source": source_path,
            "transformation": None,
            "candidate_score": None,
            "candidate_features": {},
            "package_features": {},
            "reason": (
                "No transformable functions "
                "were found."
            ),
        }

    # Use the same transformation space as the random baseline.
    transformations = (
        "internal_function_refactoring",
        "control_flow_refactoring",
        "expression_refactoring",
    )

    transformation = rng.choice(
        transformations
    )

    return {
        "round": round_number,
        "method": "function_level",
        "target_type": "function",
        "target": target["qualified_name"],
        "target_source": source_path,
        "target_functions": [target],
        "transformation": transformation,
        "candidate_score": None,
        "candidate_features": {
            "selection": "function_level",
            "start_line": target["start_line"],
            "end_line": target["end_line"],
        },
        "package_features": {},
        "reason": (
            "Function target was selected using "
            "function-level structural information."
        ),
    }


def _build_proposed_plan(
    source_code: str,
    source_path: str,
    round_number: int,
    history: list[dict[str, Any]],
    feedback_enabled: bool,
) -> dict[str, Any]:
    """
    Delegate package-aware planning to mutation_planner.py.

    DySec feedback is recorded as experimental context.
    It is not used here to automatically optimize detector evasion.
    """

    plan = build_mutation_plan(
        source_code=source_code,
        round_number=round_number,
        source_path=source_path,
        history=history,
    )

    plan["method"] = (
        "proposed_feedback"
        if feedback_enabled
        else "proposed"
    )

    plan["feedback_enabled"] = (
        feedback_enabled
    )

    if feedback_enabled:

        plan["feedback_history"] = [
            {
                "round": entry.get("round"),
                "target_source": entry.get(
                    "target_source"
                ),
                "target": entry.get(
                    "target"
                ),
                "transformation": entry.get(
                    "transformation"
                ),
                "dysec_verdict": entry.get(
                    "dysec_verdict"
                ),
            }
            for entry in history
        ]

    return plan


def _build_mutation_plan_for_method(
    method: str,
    source_code: str,
    source_path: str,
    round_number: int,
    history: list[dict[str, Any]],
    rng: random.Random,
) -> dict[str, Any]:

    if method == "random":
        return _build_random_plan(
            source_code=source_code,
            source_path=source_path,
            round_number=round_number,
            rng=rng,
        )

    if method == "function_level":
        return _build_function_level_plan(
            source_code=source_code,
            source_path=source_path,
            round_number=round_number,
            history=history,
            rng=rng,
        )

    if method == "proposed":
        return _build_proposed_plan(
            source_code=source_code,
            source_path=source_path,
            round_number=round_number,
            history=history,
            feedback_enabled=False,
        )

    if method == "proposed_feedback":
        return _build_proposed_plan(
            source_code=source_code,
            source_path=source_path,
            round_number=round_number,
            history=history,
            feedback_enabled=True,
        )

    raise ValueError(
        f"Unsupported method: {method}"
    )


# ============================================================
# Archive
# ============================================================


def _create_round_archive(
    round_package: Path,
    round_dir: Path,
    round_number: int,
) -> Path:

    archive_path = (
        round_dir
        / f"package_round_{round_number:02d}.tar.gz"
    )

    return create_package_archive(
        package_root=round_package,
        archive_path=archive_path,
    )


# ============================================================
# History
# ============================================================


def _load_history(
    package_output: Path,
) -> list[dict[str, Any]]:

    summary = _read_json(
        package_output / "summary.json"
    )

    if not summary:
        return []

    history = summary.get(
        "history",
        [],
    )

    if not isinstance(history, list):
        return []

    return [
        item
        for item in history
        if isinstance(item, dict)
    ]


def _save_summary(
    package_output: Path,
    package_name: str,
    method: str,
    history: list[dict[str, Any]],
    status: str,
) -> None:

    summary = {
        "experiment": {
            "name": EXPERIMENT_NAME,
            "method": method,
            "seed": EXPERIMENT_SEED,
            "prompt_version": PROMPT_VERSION,
            "validation_type": VALIDATION_TYPE,
        },
        "package": package_name,
        "max_rounds": EXPERIMENT_ROUNDS,
        "status": status,
        "history": history,
        "dysec_io": {
            "enabled": True,
            "method": "manual upload",
            "status": (
                "PENDING"
                if status == "AWAITING_DYSEC"
                else status
            ),
        },
    }

    _write_json(
        package_output / "summary.json",
        summary,
    )


# ============================================================
# DySec feedback
# ============================================================


def _find_latest_pending_round(
    package_output: Path,
) -> tuple[int, Path] | None:

    if not package_output.exists():
        return None

    round_dirs = sorted(
        package_output.glob("round_*"),
        reverse=True,
    )

    for round_dir in round_dirs:

        if not round_dir.is_dir():
            continue

        artifact_path = (
            round_dir / "artifact.json"
        )

        if not artifact_path.exists():
            continue

        artifact = _read_json(
            artifact_path
        )

        if not artifact:
            continue

        status = artifact.get(
            "status"
        )

        if status not in {
            "ARTIFACT_READY",
            "AWAITING_DYSEC",
        }:
            continue

        round_number = artifact.get(
            "round"
        )

        if isinstance(
            round_number,
            int,
        ):
            return (
                round_number,
                round_dir,
            )

    return None


def _load_dysec_feedback(
    round_dir: Path,
) -> dict[str, Any] | None:

    return _read_json(
        round_dir / "dysec.json"
    )


def _normalise_dysec_verdict(
    feedback: dict[str, Any],
) -> str | None:

    verdict = feedback.get(
        "verdict"
    )

    if not isinstance(
        verdict,
        str,
    ):
        return None

    verdict = verdict.strip().upper()

    if verdict in {
        "DETECTED",
        "NOT_DETECTED",
    }:
        return verdict

    return None


def _promote_round_package(
    round_package: Path,
    current_package: Path,
) -> None:

    if current_package.exists():
        shutil.rmtree(
            current_package
        )

    shutil.copytree(
        round_package,
        current_package,
    )


def _update_history_feedback(
    history: list[dict[str, Any]],
    round_number: int,
    feedback: dict[str, Any],
    verdict: str,
) -> None:

    for entry in history:

        if entry.get("round") != round_number:
            continue

        entry["dysec"] = feedback
        entry["dysec_verdict"] = verdict
        entry["status"] = verdict
        return

    history.append(
        {
            "round": round_number,
            "dysec": feedback,
            "dysec_verdict": verdict,
            "status": verdict,
        }
    )


def _apply_dysec_feedback(
    package_output: Path,
    history: list[dict[str, Any]],
    method: str,
) -> tuple[str, list[dict[str, Any]]]:

    pending = _find_latest_pending_round(
        package_output
    )

    if pending is None:
        return (
            "NO_PENDING_ROUND",
            history,
        )

    round_number, round_dir = pending

    feedback = _load_dysec_feedback(
        round_dir
    )

    if feedback is None:
        return (
            "AWAITING_DYSEC",
            history,
        )

    verdict = _normalise_dysec_verdict(
        feedback
    )

    if verdict is None:
        return (
            "INVALID_DYSEC_FEEDBACK",
            history,
        )

    result_path = (
        round_dir / "result.json"
    )

    result = (
        _read_json(result_path)
        or {}
    )

    result["dysec"] = feedback
    result["dysec_verdict"] = verdict

    _update_history_feedback(
        history=history,
        round_number=round_number,
        feedback=feedback,
        verdict=verdict,
    )

    if verdict == "NOT_DETECTED":

        result["status"] = "SUCCESS"

        _write_json(
            result_path,
            result,
        )

        _save_summary(
            package_output=package_output,
            package_name=package_output.name,
            method=method,
            history=history,
            status="SUCCESS",
        )

        return (
            "SUCCESS",
            history,
        )

    # DETECTED:
    # Preserve the generated package as the current trajectory
    # for the next experimental round.
    round_package = (
        round_dir / "package"
    )

    current_package = (
        package_output / "current"
    )

    if not round_package.exists():
        result["status"] = "PIPELINE_ERROR"
        result["error"] = (
            "Round package is missing; "
            "cannot continue."
        )

        _write_json(
            result_path,
            result,
        )

        _save_summary(
            package_output=package_output,
            package_name=package_output.name,
            method=method,
            history=history,
            status="PIPELINE_ERROR",
        )

        return (
            "PIPELINE_ERROR",
            history,
        )

    _promote_round_package(
        round_package=round_package,
        current_package=current_package,
    )

    result["status"] = "DETECTED"

    _write_json(
        result_path,
        result,
    )

    _save_summary(
        package_output=package_output,
        package_name=package_output.name,
        method=method,
        history=history,
        status="CONTINUE",
    )

    return (
        "CONTINUE",
        history,
    )


# ============================================================
# Experiment initialization
# ============================================================


def _initialise_package(
    archive_path: Path,
    package_output: Path,
) -> tuple[Path, Path]:

    original_extract = (
        package_output
        / "original_extract"
    )

    original_package = (
        package_output
        / "original"
    )

    current_package = (
        package_output
        / "current"
    )

    if not original_extract.exists():

        original_extract.mkdir(
            parents=True,
            exist_ok=True,
        )

        extract_package(
            archive_path,
            original_extract,
        )

    if not original_package.exists():

        copy_package(
            original_extract,
            original_package,
        )

    if not current_package.exists():

        copy_package(
            original_extract,
            current_package,
        )

    return (
        original_package,
        current_package,
    )


# ============================================================
# Main experiment
# ============================================================


def run_package(
    archive_path: Path,
    method: str = "proposed",
    resume: bool = False,
) -> dict[str, Any]:

    if method not in SUPPORTED_METHODS:
        raise ValueError(
            f"Unsupported method '{method}'. "
            f"Supported methods: "
            f"{sorted(SUPPORTED_METHODS)}"
        )

    archive_path = Path(
        archive_path
    ).resolve()

    if not archive_path.exists():
        raise FileNotFoundError(
            f"Package archive does not exist: "
            f"{archive_path}"
        )

    package_name = archive_path.name

    if package_name.endswith(".tar.gz"):
        package_name = package_name[:-7]

    elif package_name.endswith(".tgz"):
        package_name = package_name[:-4]

    package_output = (
        OUTPUT_DIR
        / method
        / package_name
    )

    package_output.mkdir(
        parents=True,
        exist_ok=True,
    )

    history = _load_history(
        package_output
    )

    rng = _build_rng(
        package_name=package_name,
        method=method,
    )

    # --------------------------------------------------------
    # Resume pending DySec evaluation.
    # --------------------------------------------------------

    if resume:

        feedback_status, history = (
            _apply_dysec_feedback(
                package_output=package_output,
                history=history,
                method=method,
            )
        )

        if feedback_status == "SUCCESS":
            return {
                "package": package_name,
                "method": method,
                "status": "SUCCESS",
                "rounds": len(history),
                "history": history,
            }

        if feedback_status == "AWAITING_DYSEC":
            return {
                "package": package_name,
                "method": method,
                "status": "AWAITING_DYSEC",
                "rounds": len(history),
                "history": history,
            }

        if feedback_status == "INVALID_DYSEC_FEEDBACK":
            return {
                "package": package_name,
                "method": method,
                "status": "INVALID_DYSEC_FEEDBACK",
                "rounds": len(history),
                "history": history,
            }

        if feedback_status == "PIPELINE_ERROR":
            return {
                "package": package_name,
                "method": method,
                "status": "PIPELINE_ERROR",
                "rounds": len(history),
                "history": history,
            }

    # --------------------------------------------------------
    # Initialise original/current package.
    # --------------------------------------------------------

    _, current_package = _initialise_package(
        archive_path=archive_path,
        package_output=package_output,
    )

    # --------------------------------------------------------
    # Never create another round while DySec is pending.
    # --------------------------------------------------------

    pending = _find_latest_pending_round(
        package_output
    )

    if pending is not None:

        round_number, round_dir = pending

        if _load_dysec_feedback(
            round_dir
        ) is None:

            _save_summary(
                package_output=package_output,
                package_name=package_name,
                method=method,
                history=history,
                status="AWAITING_DYSEC",
            )

            return {
                "package": package_name,
                "method": method,
                "status": "AWAITING_DYSEC",
                "round": round_number,
                "rounds": len(history),
                "history": history,
            }

    # --------------------------------------------------------
    # Determine next round.
    # --------------------------------------------------------

    round_numbers = [
        entry.get("round")
        for entry in history
        if isinstance(
            entry.get("round"),
            int,
        )
    ]

    start_round = (
        max(round_numbers) + 1
        if round_numbers
        else 1
    )

    if start_round > EXPERIMENT_ROUNDS:
        _save_summary(
            package_output=package_output,
            package_name=package_name,
            method=method,
            history=history,
            status="MAX_ROUNDS_REACHED",
        )

        return {
            "package": package_name,
            "method": method,
            "status": "MAX_ROUNDS_REACHED",
            "rounds": len(history),
            "history": history,
        }

    # --------------------------------------------------------
    # Main round.
    #
    # One invocation produces one artifact and pauses for
    # manual DySec evaluation.
    # --------------------------------------------------------

    round_number = start_round

    round_dir = (
        package_output
        / f"round_{round_number:02d}"
    )

    round_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Select target source.
    # --------------------------------------------------------

    if method == "random":

        target_source = _select_random_source(
            current_package,
            rng,
        )

    else:

        target_source = _select_structural_source(
            current_package,
            history=history,
        )

    if target_source is None:

        error = (
            "No transformable Python source "
            "files were found."
        )

        result = {
            "round": round_number,
            "method": method,
            "status": "PIPELINE_ERROR",
            "error": error,
        }

        _write_json(
            round_dir / "result.json",
            result,
        )

        _save_summary(
            package_output=package_output,
            package_name=package_name,
            method=method,
            history=history,
            status="PIPELINE_ERROR",
        )

        return {
            "package": package_name,
            "method": method,
            "status": "PIPELINE_ERROR",
            "error": error,
        }

    try:

        relative_source = (
            target_source.relative_to(
                current_package
            )
        )

    except ValueError:

        relative_source = Path(
            target_source.name
        )

    source_path = str(
        relative_source
    )

    # --------------------------------------------------------
    # Read source.
    # --------------------------------------------------------

    try:

        source_code = target_source.read_text(
            encoding="utf-8"
        )

    except (
        OSError,
        UnicodeDecodeError,
    ) as exc:

        error = (
            "Unable to read target source: "
            f"{exc}"
        )

        result = {
            "round": round_number,
            "method": method,
            "status": "PIPELINE_ERROR",
            "target_source": source_path,
            "error": error,
        }

        _write_json(
            round_dir / "result.json",
            result,
        )

        _save_summary(
            package_output=package_output,
            package_name=package_name,
            method=method,
            history=history,
            status="PIPELINE_ERROR",
        )

        return {
            "package": package_name,
            "method": method,
            "status": "PIPELINE_ERROR",
            "error": error,
        }

    # --------------------------------------------------------
    # Build mutation plan.
    # --------------------------------------------------------

    mutation_plan = (
        _build_mutation_plan_for_method(
            method=method,
            source_code=source_code,
            source_path=source_path,
            round_number=round_number,
            history=history,
            rng=rng,
        )
    )

    if not mutation_plan.get("target"):

        error = (
            "Mutation planner could not find "
            "a suitable mutation target."
        )

        result = {
            "round": round_number,
            "method": method,
            "status": "PIPELINE_ERROR",
            "target_source": source_path,
            "mutation_plan": mutation_plan,
            "error": error,
        }

        _write_json(
            round_dir / "result.json",
            result,
        )

        _save_summary(
            package_output=package_output,
            package_name=package_name,
            method=method,
            history=history,
            status="PIPELINE_ERROR",
        )

        return {
            "package": package_name,
            "method": method,
            "status": "PIPELINE_ERROR",
            "error": error,
        }

    _write_json(
        round_dir / "mutation_plan.json",
        mutation_plan,
    )

    # --------------------------------------------------------
    # Build prompt.
    # --------------------------------------------------------

    latest_feedback = None

    if history:

        candidate_feedback = history[-1].get(
            "dysec"
        )

        if isinstance(
            candidate_feedback,
            dict,
        ):
            latest_feedback = (
                candidate_feedback
            )

    prompt = build_prompt(
        source_code=source_code,
        mutation_plan=mutation_plan,
        round_number=round_number,
        target_source=source_path,
        history=history,
        package_features=mutation_plan.get(
            "package_features"
        ),
        dysec_feedback=(
            latest_feedback
            if method == "proposed_feedback"
            else None
        ),
    )

    (
        round_dir / "prompt.txt"
    ).write_text(
        prompt,
        encoding="utf-8",
    )

    # --------------------------------------------------------
    # Generation.
    # --------------------------------------------------------

    generation = generate_variant(
        prompt
    )
    response_metadata = (
        generation.get(
            "response_metadata"
        )
        or {}
    )

    generation_metadata = {
        "model": response_metadata.get(
            "model"
        ),
        "temperature": response_metadata.get(
            "temperature"
        ),
        "elapsed_seconds": response_metadata.get(
            "elapsed_seconds"
        ),
        "created_at": response_metadata.get(
            "created_at"
        ),
        "done": response_metadata.get(
            "done"
        ),
        "prompt_eval_count": response_metadata.get(
            "prompt_eval_count"
        ),
        "eval_count": response_metadata.get(
            "eval_count"
        ),
    }

    _write_json(
        round_dir / "generation_metadata.json",
        generation_metadata,
    )

    generated_code = generation.get(
        "code"
    )

    if (
        not generation.get("success")
        or not generated_code
    ):

        error = generation.get(
            "error",
            "LLM generation failed.",
        )

        result = {
            "round": round_number,
            "method": method,
            "status": "GENERATION_ERROR",
            "target_source": source_path,
            "mutation_plan": mutation_plan,
            "error": error,
        }

        _write_json(
            round_dir / "result.json",
            result,
        )

        _save_summary(
            package_output=package_output,
            package_name=package_name,
            method=method,
            history=history,
            status="GENERATION_ERROR",
        )

        return {
            "package": package_name,
            "method": method,
            "status": "GENERATION_ERROR",
            "round": round_number,
            "error": error,
        }

    (
        round_dir / "generated_code.py"
    ).write_text(
        generated_code,
        encoding="utf-8",
    )

    # --------------------------------------------------------
    # Source guard.
    # --------------------------------------------------------

    guard_result = source_change_guard(
        original_source=source_code,
        generated_source=generated_code,
    )

    _write_json(
        round_dir / "source_guard.json",
        guard_result,
    )

    if not guard_result.get(
        "accepted",
        False,
    ):

        error = (
            "Generated source failed "
            "the source-change guard."
        )

        result = {
            "round": round_number,
            "method": method,
            "status": "SOURCE_GUARD_REJECTED",
            "target_source": source_path,
            "mutation_plan": mutation_plan,
            "source_guard": guard_result,
            "error": error,
        }

        _write_json(
            round_dir / "result.json",
            result,
        )

        _save_summary(
            package_output=package_output,
            package_name=package_name,
            method=method,
            history=history,
            status="SOURCE_GUARD_REJECTED",
        )

        return {
            "package": package_name,
            "method": method,
            "status": "SOURCE_GUARD_REJECTED",
            "round": round_number,
            "error": error,
        }

    # --------------------------------------------------------
    # Diversity gate.
    # --------------------------------------------------------

    diversity_result = analyze_diversity(
        source_code,
        generated_code,
    )

    _write_json(
        round_dir / "diversity.json",
        diversity_result,
    )

    if not diversity_result.get(
        "accepted",
        False,
    ):

        error = (
            "Generated source did not pass "
            "the diversity gate."
        )

        result = {
            "round": round_number,
            "method": method,
            "status": "DIVERSITY_REJECTED",
            "target_source": source_path,
            "mutation_plan": mutation_plan,
            "diversity": diversity_result,
            "error": error,
        }

        _write_json(
            round_dir / "result.json",
            result,
        )

        _save_summary(
            package_output=package_output,
            package_name=package_name,
            method=method,
            history=history,
            status="DIVERSITY_REJECTED",
        )

        return {
            "package": package_name,
            "method": method,
            "status": "DIVERSITY_REJECTED",
            "round": round_number,
            "error": error,
        }

    # --------------------------------------------------------
    # Build candidate package.
    # --------------------------------------------------------

    round_package = (
        round_dir / "package"
    )

    copy_package(
        current_package,
        round_package,
    )

    round_target = (
        round_package / relative_source
    )

    round_target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    round_target.write_text(
        generated_code,
        encoding="utf-8",
    )

    # --------------------------------------------------------
    # Installation validation.
    #
    # IMPORTANT:
    # This is NOT semantic behavior equivalence.
    # --------------------------------------------------------

    installation_result = (
        validate_behavior(
            original_package=current_package,
            generated_package=round_package,
        )
    )

    _write_json(
        round_dir / "installation_validation.json",
        installation_result,
    )

    if not installation_result.get(
        "preserved",
        False,
    ):

        error = (
            "Generated package failed "
            "installation validation."
        )

        result = {
            "round": round_number,
            "method": method,
            "status": "INSTALLATION_REJECTED",
            "target_source": source_path,
            "mutation_plan": mutation_plan,
            "installation_validation": (
                installation_result
            ),
            "error": error,
        }

        _write_json(
            round_dir / "result.json",
            result,
        )

        _save_summary(
            package_output=package_output,
            package_name=package_name,
            method=method,
            history=history,
            status="INSTALLATION_REJECTED",
        )

        return {
            "package": package_name,
            "method": method,
            "status": "INSTALLATION_REJECTED",
            "round": round_number,
            "error": error,
        }

    # --------------------------------------------------------
    # Create DySec artifact.
    # --------------------------------------------------------

    archive = _create_round_archive(
        round_package=round_package,
        round_dir=round_dir,
        round_number=round_number,
    )

    artifact = {
        "round": round_number,
        "method": method,
        "status": "AWAITING_DYSEC",
        "archive": str(archive),
        "target_source": source_path,
        "mutation_plan": mutation_plan,
        "validation": {
            "type": VALIDATION_TYPE,
            "status": "PASS",
        },
        "evaluation": {
            "provider": "DySec.io",
            "method": "manual upload",
            "status": "PENDING",
        },
    }

    _write_json(
        round_dir / "artifact.json",
        artifact,
    )

    # --------------------------------------------------------
    # Round history.
    # --------------------------------------------------------

    candidate_features = (
        mutation_plan.get(
            "candidate_features",
            {},
        )
    )

    if not isinstance(
        candidate_features,
        dict,
    ):
        candidate_features = {}

    round_history = {
        "round": round_number,
        "method": method,
        "target_source": source_path,
        "target": mutation_plan.get(
            "target"
        ),
        "target_type": mutation_plan.get(
            "target_type"
        ),
        "start_line": mutation_plan.get(
            "start_line"
        ),
        "end_line": mutation_plan.get(
            "end_line"
        ),
        "transformation": mutation_plan.get(
            "transformation"
        ),
        "candidate_score": mutation_plan.get(
            "candidate_score"
        ),
        "generation_success": True,
        "source_guard_pass": True,
        "source_guard_token_similarity": (
            guard_result.get(
                "token_similarity"
            )
        ),
        "source_guard_ast_similarity": (
            guard_result.get(
                "ast_similarity"
            )
        ),
        "diversity_pass": True,
        "installation_pass": True,
        "dysec_verdict": None,
        "status": "AWAITING_DYSEC",
        "artifact": str(archive),
    }

    history.append(
        round_history
    )

    # --------------------------------------------------------
    # Result.
    # --------------------------------------------------------

    result = {
        "round": round_number,
        "method": method,
        "status": "AWAITING_DYSEC",
        "target_source": source_path,
        "target": mutation_plan.get(
            "target"
        ),
        "transformation": mutation_plan.get(
            "transformation"
        ),
        "mutation_plan": mutation_plan,
        "validation": {
            "type": VALIDATION_TYPE,
            "status": "PASS",
        },
        "external_evaluation": {
            "provider": "DySec.io",
            "status": "PENDING",
        },
        "artifact": str(archive),
    }

    _write_json(
        round_dir / "result.json",
        result,
    )

    _save_summary(
        package_output=package_output,
        package_name=package_name,
        method=method,
        history=history,
        status="AWAITING_DYSEC",
    )

    return {
        "package": package_name,
        "method": method,
        "status": "AWAITING_DYSEC",
        "round": round_number,
        "artifact": str(archive),
        "history": history,
    }