from __future__ import annotations

import ast
import hashlib
import json
import random
import textwrap
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
from pipeline.function_selector import (
    find_functions,
    find_source_targets,
)
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

TRANSFORMATIONS = (
    "internal_function_refactoring",
    "control_flow_refactoring",
    "expression_refactoring",
)

MAX_FUNCTION_LINES = 80
MAX_CLASS_LINES = 120
MAX_MODULE_BLOCK_LINES = 40

TARGET_PRIORITY = {
    "function": 0,
    "class": 1,
    "module_block": 2,
}


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
# Target compatibility helpers
# ============================================================


def _target_limit(
    target_type: str | None,
) -> int | None:

    if target_type == "function":
        return MAX_FUNCTION_LINES

    if target_type == "class":
        return MAX_CLASS_LINES

    if target_type == "module_block":
        return MAX_MODULE_BLOCK_LINES

    return None


def _module_block_node_type(
    block_type: str | None,
) -> type[ast.AST] | None:

    mapping: dict[str, type[ast.AST]] = {
        "if": ast.If,
        "for": ast.For,
        "async_for": ast.AsyncFor,
        "while": ast.While,
        "try": ast.Try,
        "with": ast.With,
        "async_with": ast.AsyncWith,
        "expression": ast.Expr,
        "assignment": ast.Assign,
        "annotated_assignment": ast.AnnAssign,
        "augmented_assignment": ast.AugAssign,
        "return": ast.Return,
    }

    if block_type == "match":
        match_type = getattr(ast, "Match", None)
        if match_type is not None:
            return match_type

    return mapping.get(block_type)


def _candidate_transformations(
    target_type: str,
    block_type: str | None = None,
) -> tuple[str, ...]:

    if target_type in {
        "function",
        "class",
    }:
        return TRANSFORMATIONS

    if target_type == "module_block":

        if block_type in {
            "if",
            "for",
            "async_for",
            "while",
            "try",
            "with",
            "async_with",
            "match",
        }:
            return (
                "control_flow_refactoring",
            )

        if block_type in {
            "expression",
            "assignment",
            "annotated_assignment",
            "augmented_assignment",
            "return",
            "raise",
            "assert",
            "delete",
        }:
            return (
                "expression_refactoring",
            )

    return ()


def _history_attempted_keys(
    history: list[dict[str, Any]],
) -> set[tuple[str, str, str, int, int, str | None]]:

    attempted: set[
        tuple[str, str, str, int, int, str | None]
    ] = set()

    for entry in history:

        source = entry.get("target_source")
        target_type = entry.get("target_type")
        target = entry.get("target")
        start_line = entry.get("start_line")
        end_line = entry.get("end_line")
        transformation = entry.get("transformation")

        if not source:
            continue

        if not target_type:
            continue

        if not target:
            continue

        if not isinstance(start_line, int):
            continue

        if not isinstance(end_line, int):
            continue

        attempted.add(
            (
                str(source),
                str(target_type),
                str(target),
                start_line,
                end_line,
                (
                    str(transformation)
                    if transformation
                    else None
                ),
            )
        )

    return attempted


# ============================================================
# Source selection
# ============================================================


def _select_random_source(
    package_root: Path,
    rng: random.Random,
) -> Path | None:

    candidates = collect_transformable_python_files(
        package_root
    )

    if not candidates:
        return None

    return rng.choice(candidates)


def _structural_candidates_for_source(
    source_path: Path,
    package_root: Path,
) -> list[dict[str, Any]]:

    try:
        source_code = source_path.read_text(
            encoding="utf-8"
        )

        source_targets = find_source_targets(
            source_code
        )

    except (
        OSError,
        SyntaxError,
        UnicodeDecodeError,
        ValueError,
    ):
        return []

    candidates: list[dict[str, Any]] = []

    try:
        relative_path = source_path.resolve().relative_to(
            package_root.resolve()
        )
    except ValueError:
        relative_path = Path(source_path.name)

    # --------------------------------------------------------
    # Functions
    #
    # mutation_planner.py deliberately excludes dunder methods.
    # Keep the same rule here so source selection and planner
    # cannot disagree about the candidate family.
    # --------------------------------------------------------

    for target in source_targets.functions:

        if target.name.startswith("__"):
            continue

        start_line = target.lineno
        end_line = target.end_lineno

        if end_line < start_line:
            continue

        line_count = end_line - start_line + 1

        if line_count > MAX_FUNCTION_LINES:
            continue

        candidates.append(
            {
                "source_path": source_path,
                "relative_source": str(relative_path),
                "target": target,
                "target_type": "function",
                "target_name": target.qualified_name,
                "start_line": start_line,
                "end_line": end_line,
                "target_line_count": line_count,
                "block_type": None,
            }
        )

    # --------------------------------------------------------
    # Classes
    # --------------------------------------------------------

    for target in source_targets.classes:

        start_line = target.lineno
        end_line = target.end_lineno

        if end_line < start_line:
            continue

        line_count = end_line - start_line + 1

        if line_count > MAX_CLASS_LINES:
            continue

        candidates.append(
            {
                "source_path": source_path,
                "relative_source": str(relative_path),
                "target": target,
                "target_type": "class",
                "target_name": target.qualified_name,
                "start_line": start_line,
                "end_line": end_line,
                "target_line_count": line_count,
                "block_type": None,
            }
        )

    # --------------------------------------------------------
    # Top-level module blocks
    # --------------------------------------------------------

    for target in source_targets.module_blocks:

        start_line = target.lineno
        end_line = target.end_lineno

        if end_line < start_line:
            continue

        line_count = end_line - start_line + 1

        if line_count > MAX_MODULE_BLOCK_LINES:
            continue

        candidates.append(
            {
                "source_path": source_path,
                "relative_source": str(relative_path),
                "target": target,
                "target_type": "module_block",
                "target_name": target.name,
                "start_line": start_line,
                "end_line": end_line,
                "target_line_count": line_count,
                "block_type": target.block_type,
            }
        )

    return candidates


def _select_structural_source(
    package_root: Path,
    rng: random.Random,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """
    Select a viable structural target before LLM generation.

    Selection order:
        1. function
        2. class
        3. module block

    Within the same structural class:
        1. smaller target
        2. source path
        3. start line

    A small reproducible random tie-break is used among candidates
    with the same priority and size.

    Importantly, this function only selects targets that the
    mutation planner can reasonably support.
    """

    package_root = package_root.resolve()
    history = history or []

    source_files = collect_transformable_python_files(
        package_root
    )

    candidates: list[dict[str, Any]] = []

    for source_path in source_files:
        candidates.extend(
            _structural_candidates_for_source(
                source_path=source_path,
                package_root=package_root,
            )
        )

    if not candidates:
        return None

    attempted = _history_attempted_keys(
        history
    )

    # --------------------------------------------------------
    # Prefer candidates for which at least one compatible
    # transformation has not been attempted.
    # --------------------------------------------------------

    unattempted: list[dict[str, Any]] = []

    for candidate in candidates:

        compatible = _candidate_transformations(
            target_type=candidate["target_type"],
            block_type=candidate.get("block_type"),
        )

        if not compatible:
            continue

        candidate["compatible_transformations"] = (
            compatible
        )

        has_unattempted_transformation = any(
            (
                candidate["relative_source"],
                candidate["target_type"],
                candidate["target_name"],
                candidate["start_line"],
                candidate["end_line"],
                transformation,
            )
            not in attempted
            for transformation in compatible
        )

        if has_unattempted_transformation:
            unattempted.append(candidate)

    pool = unattempted if unattempted else candidates

    if not pool:
        return None

    pool.sort(
        key=lambda candidate: (
            TARGET_PRIORITY.get(
                candidate["target_type"],
                99,
            ),
            candidate["target_line_count"],
            candidate["relative_source"],
            candidate["start_line"],
            candidate["target_name"],
        )
    )

    best_priority = TARGET_PRIORITY.get(
        pool[0]["target_type"],
        99,
    )

    best_size = pool[0]["target_line_count"]

    top_pool = [
        candidate
        for candidate in pool
        if (
            TARGET_PRIORITY.get(
                candidate["target_type"],
                99,
            )
            == best_priority
            and candidate["target_line_count"]
            == best_size
        )
    ]

    return rng.choice(top_pool)


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
        and (
            target.end_lineno - target.lineno + 1
        ) <= MAX_FUNCTION_LINES
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

    transformation = rng.choice(
        TRANSFORMATIONS
    )

    return {
        "round": round_number,
        "method": "random",
        "target_type": "function",
        "target": target["qualified_name"],
        "target_source": source_path,
        "target_functions": [target],
        "start_line": target["start_line"],
        "end_line": target["end_line"],
        "transformation": transformation,
        "candidate_score": None,
        "candidate_features": {
            "selection": "uniform_random",
            "start_line": target["start_line"],
            "end_line": target["end_line"],
            "lines": (
                target["end_line"]
                - target["start_line"]
                + 1
            ),
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

    transformation = rng.choice(
        TRANSFORMATIONS
    )

    return {
        "round": round_number,
        "method": "function_level",
        "target_type": "function",
        "target": target["qualified_name"],
        "target_source": source_path,
        "target_functions": [target],
        "start_line": target["start_line"],
        "end_line": target["end_line"],
        "transformation": transformation,
        "candidate_score": None,
        "candidate_features": {
            "selection": "function_level",
            "start_line": target["start_line"],
            "end_line": target["end_line"],
            "lines": (
                target["end_line"]
                - target["start_line"]
                + 1
            ),
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

    plan = build_mutation_plan(
        source_code=source_code,
        round_number=round_number,
        source_path=source_path,
        history=history,
        feedback_mode=feedback_enabled,
    )

    plan["method"] = (
        "proposed_feedback"
        if feedback_enabled
        else "proposed"
    )

    plan["feedback_enabled"] = feedback_enabled

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
# AST target identity validation
# ============================================================


def _qualified_ast_name(
    node: ast.AST,
    tree: ast.AST,
) -> str | None:
    """
    Return a best-effort qualified name for a function/class.

    This helper is intentionally conservative. Line range and
    node type remain the primary identity checks.
    """

    del tree

    name = getattr(
        node,
        "name",
        None,
    )

    if isinstance(name, str):
        return name

    return None


def _find_matching_function(
    tree: ast.AST,
    target_name: str,
    start_line: int,
    end_line: int,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:

    simple_name = (
        target_name.rsplit(".", 1)[-1]
    )

    matches = []

    for node in ast.walk(tree):

        if not isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        ):
            continue

        if node.name != simple_name:
            continue

        node_start = getattr(
            node,
            "lineno",
            None,
        )

        node_end = getattr(
            node,
            "end_lineno",
            None,
        )

        if node_start != start_line:
            continue

        if node_end != end_line:
            continue

        matches.append(node)

    if len(matches) == 1:
        return matches[0]

    return None


def _find_matching_class(
    tree: ast.AST,
    target_name: str,
    start_line: int,
    end_line: int,
) -> ast.ClassDef | None:

    simple_name = (
        target_name.rsplit(".", 1)[-1]
    )

    matches = []

    for node in ast.walk(tree):

        if not isinstance(
            node,
            ast.ClassDef,
        ):
            continue

        if node.name != simple_name:
            continue

        node_start = getattr(
            node,
            "lineno",
            None,
        )

        node_end = getattr(
            node,
            "end_lineno",
            None,
        )

        if node_start != start_line:
            continue

        if node_end != end_line:
            continue

        matches.append(node)

    if len(matches) == 1:
        return matches[0]

    return None


def _find_matching_module_block(
    source_code: str,
    target_name: str,
    start_line: int,
    end_line: int,
    block_type: str | None,
) -> dict[str, Any] | None:

    try:
        source_targets = find_source_targets(
            source_code
        )
    except (
        SyntaxError,
        ValueError,
    ):
        return None

    matches = []

    for target in source_targets.module_blocks:

        if target.name != target_name:
            continue

        if target.lineno != start_line:
            continue

        if target.end_lineno != end_line:
            continue

        if (
            block_type
            and target.block_type != block_type
        ):
            continue

        matches.append(target)

    if len(matches) != 1:
        return None

    target = matches[0]

    return {
        "name": target.name,
        "block_type": target.block_type,
        "start_line": target.lineno,
        "end_line": target.end_lineno,
    }


def _validate_mutation_plan_target(
    mutation_plan: dict[str, Any],
    source_code: str,
    source_path: str,
) -> dict[str, Any]:
    """
    Hard structural gate before LLM generation.

    This validation checks both:
        1. size constraints;
        2. identity of the planner target against the actual
           AST of the source file.

    The second check is important because source selection and
    mutation planning are separate components. Without this gate,
    the planner could return a different target than the source
    selector intended.
    """

    target_type = mutation_plan.get(
        "target_type"
    )

    target = mutation_plan.get(
        "target"
    )

    planned_source = mutation_plan.get(
        "target_source"
    )

    if not target:
        return {
            "accepted": False,
            "reason": (
                "Mutation plan does not contain "
                "a target."
            ),
        }

    if not isinstance(
        target,
        str,
    ):
        return {
            "accepted": False,
            "reason": (
                "Mutation plan target must be a string."
            ),
        }

    if planned_source is not None:
        if str(planned_source) != str(source_path):
            return {
                "accepted": False,
                "reason": (
                    "Mutation planner selected a target "
                    "from a different source file."
                ),
                "planned_source": str(planned_source),
                "actual_source": str(source_path),
            }

    try:
        start_line = int(
            mutation_plan["start_line"]
        )
        end_line = int(
            mutation_plan["end_line"]
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ) as exc:

        return {
            "accepted": False,
            "reason": (
                "Mutation plan contains invalid "
                f"line information: {exc}"
            ),
        }

    if start_line < 1 or end_line < start_line:

        return {
            "accepted": False,
            "reason": (
                "Mutation plan contains an invalid "
                "line range."
            ),
            "start_line": start_line,
            "end_line": end_line,
        }

    target_line_count = (
        end_line - start_line + 1
    )

    limit = _target_limit(
        target_type
    )

    if limit is None:

        return {
            "accepted": False,
            "reason": (
                "Mutation plan contains an unsupported "
                f"target type: {target_type}"
            ),
            "target_type": target_type,
        }

    if target_line_count > limit:

        return {
            "accepted": False,
            "reason": (
                "Mutation target exceeds the configured "
                "structural size limit."
            ),
            "target_type": target_type,
            "target": target,
            "start_line": start_line,
            "end_line": end_line,
            "target_line_count": target_line_count,
            "maximum_allowed_lines": limit,
        }

    try:
        tree = ast.parse(
            source_code
        )
    except SyntaxError as exc:
        return {
            "accepted": False,
            "reason": (
                "Target source is not valid Python: "
                f"{exc}"
            ),
        }

    candidate_features = mutation_plan.get(
        "candidate_features",
        {},
    )

    if not isinstance(
        candidate_features,
        dict,
    ):
        candidate_features = {}

    matched_node: ast.AST | None = None
    matched_block: dict[str, Any] | None = None

    if target_type == "function":

        matched_node = _find_matching_function(
            tree=tree,
            target_name=target,
            start_line=start_line,
            end_line=end_line,
        )

    elif target_type == "class":

        matched_node = _find_matching_class(
            tree=tree,
            target_name=target,
            start_line=start_line,
            end_line=end_line,
        )

    elif target_type == "module_block":

        matched_block = _find_matching_module_block(
            source_code=source_code,
            target_name=target,
            start_line=start_line,
            end_line=end_line,
            block_type=candidate_features.get(
                "block_type"
            ),
        )

    if target_type in {
        "function",
        "class",
    } and matched_node is None:

        return {
            "accepted": False,
            "reason": (
                "Mutation planner target could not be "
                "matched uniquely against the actual AST "
                "of the selected source file."
            ),
            "target_type": target_type,
            "target": target,
            "start_line": start_line,
            "end_line": end_line,
            "source_path": source_path,
        }

    if (
        target_type == "module_block"
        and matched_block is None
    ):

        return {
            "accepted": False,
            "reason": (
                "Mutation planner module block could not "
                "be matched uniquely against the actual "
                "source AST."
            ),
            "target_type": target_type,
            "target": target,
            "start_line": start_line,
            "end_line": end_line,
            "source_path": source_path,
            "expected_block_type": candidate_features.get(
                "block_type"
            ),
        }

    actual_block_type = (
        matched_block.get("block_type")
        if matched_block
        else None
    )

    if (
        target_type == "module_block"
        and candidate_features.get("block_type")
        and candidate_features.get("block_type")
        != actual_block_type
    ):

        return {
            "accepted": False,
            "reason": (
                "Mutation planner block type does not "
                "match the actual source AST."
            ),
            "target_type": target_type,
            "target": target,
            "planned_block_type": candidate_features.get(
                "block_type"
            ),
            "actual_block_type": actual_block_type,
        }

    return {
        "accepted": True,
        "reason": (
            "Mutation target passed structural size "
            "and AST identity validation."
        ),
        "target_type": target_type,
        "target": target,
        "source_path": source_path,
        "start_line": start_line,
        "end_line": end_line,
        "target_line_count": target_line_count,
        "maximum_allowed_lines": limit,
        "matched_ast_node": (
            type(matched_node).__name__
            if matched_node is not None
            else None
        ),
        "matched_block_type": actual_block_type,
    }


# ============================================================
# Target source extraction / reconstruction
# ============================================================


def _extract_source_region(
    source_code: str,
    start_line: int,
    end_line: int,
) -> tuple[str, str, str]:

    lines = source_code.splitlines(
        keepends=True
    )

    if start_line < 1:
        raise ValueError(
            f"Invalid start_line: {start_line}"
        )

    if end_line < start_line:
        raise ValueError(
            f"Invalid source range: "
            f"{start_line}-{end_line}"
        )

    if end_line > len(lines):
        raise ValueError(
            f"Source range "
            f"{start_line}-{end_line} "
            f"exceeds source length "
            f"{len(lines)}."
        )

    prefix = "".join(
        lines[: start_line - 1]
    )

    target = "".join(
        lines[start_line - 1 : end_line]
    )

    suffix = "".join(
        lines[end_line:]
    )

    return (
        prefix,
        target,
        suffix,
    )


def _clean_generated_target(
    generated_target: str,
) -> str:

    generated_target = generated_target.replace(
        "\r\n",
        "\n",
    )

    generated_target = generated_target.replace(
        "\r",
        "\n",
    )

    lines = generated_target.splitlines(
        keepends=True
    )

    # Remove blank transport-level lines only.
    while lines and not lines[0].strip():
        lines.pop(0)

    while lines and not lines[-1].strip():
        lines.pop()

    # If the model returned a complete Markdown code fence,
    # remove only the fence itself. Do not strip indentation.
    if (
        len(lines) >= 2
        and lines[0].strip().startswith("```")
        and lines[-1].strip() == "```"
    ):
        lines = lines[1:-1]

    return "".join(lines)


def _reconstruct_source(
    prefix: str,
    generated_target: str,
    suffix: str,
) -> str:

    generated_target = _clean_generated_target(
        generated_target
    )

    if not generated_target.strip():
        raise ValueError(
            "Generated target is empty."
        )

    return (
        prefix
        + generated_target
        + suffix
    )


# ============================================================
# Target-scope validation
# ============================================================


def _expected_target_node_type(
    target_type: str | None,
    candidate_features: dict[str, Any],
) -> set[type[ast.AST]]:

    if target_type == "function":
        return {
            ast.FunctionDef,
            ast.AsyncFunctionDef,
        }

    if target_type == "class":
        return {
            ast.ClassDef,
        }

    if target_type == "module_block":

        block_type = str(
            candidate_features.get(
                "block_type",
                ""
            )
        )

        mapping: dict[
            str,
            type[ast.AST],
        ] = {
            "if": ast.If,
            "for": ast.For,
            "async_for": ast.AsyncFor,
            "while": ast.While,
            "try": ast.Try,
            "with": ast.With,
            "async_with": ast.AsyncWith,
            "expression": ast.Expr,
            "assignment": ast.Assign,
            "annotated_assignment": ast.AnnAssign,
            "augmented_assignment": ast.AugAssign,
            "return": ast.Return,
        }

        if block_type == "match":
            match_type = getattr(
                ast,
                "Match",
                None,
            )
            if match_type is not None:
                return {match_type}

        expected = mapping.get(
            block_type
        )

        if expected is not None:
            return {expected}

        return {
            ast.If,
            ast.For,
            ast.AsyncFor,
            ast.While,
            ast.Try,
            ast.With,
            ast.AsyncWith,
            ast.Expr,
            ast.Assign,
            ast.AnnAssign,
            ast.AugAssign,
        }

    return set()


def _validate_generated_target_scope(
    generated_target: str,
    target_type: str | None,
    candidate_features: dict[str, Any],
) -> dict[str, Any]:

    cleaned = _clean_generated_target(
        generated_target
    )

    if not cleaned.strip():
        return {
            "accepted": False,
            "reason": "Generated target is empty.",
            "target_type": target_type,
        }

    validation_source = textwrap.dedent(
        cleaned
    )

    try:
        tree = ast.parse(
            validation_source
        )

    except SyntaxError as exc:

        return {
            "accepted": False,
            "reason": (
                "Generated target could not be "
                f"parsed as Python: {exc}"
            ),
            "target_type": target_type,
        }

    expected_types = _expected_target_node_type(
        target_type=target_type,
        candidate_features=candidate_features,
    )

    top_level_types = [
        type(node).__name__
        for node in tree.body
    ]

    if not expected_types:

        return {
            "accepted": False,
            "reason": (
                "No expected AST target type is "
                "defined for the mutation plan."
            ),
            "target_type": target_type,
            "top_level_node_types": top_level_types,
        }

    if len(tree.body) != 1:

        return {
            "accepted": False,
            "reason": (
                "Generated target must contain exactly "
                "one top-level target node."
            ),
            "target_type": target_type,
            "top_level_node_types": top_level_types,
            "top_level_node_count": len(tree.body),
        }

    actual_type = type(
        tree.body[0]
    )

    accepted = actual_type in expected_types

    return {
        "accepted": accepted,
        "reason": (
            "Generated target matches the expected "
            "target AST structure."
            if accepted
            else (
                "Generated target does not match "
                "the expected target AST structure."
            )
        ),
        "target_type": target_type,
        "expected_node_types": sorted(
            node_type.__name__
            for node_type in expected_types
        ),
        "actual_node_type": actual_type.__name__,
        "top_level_node_types": top_level_types,
        "top_level_node_count": len(tree.body),
        "generated_target_line_count": len(
            cleaned.splitlines()
        ),
    }


# ============================================================
# Full-source syntax validation
# ============================================================


def _validate_full_source_syntax(
    source_code: str,
) -> dict[str, Any]:

    try:
        tree = ast.parse(
            source_code
        )

    except SyntaxError as exc:

        return {
            "accepted": False,
            "reason": (
                "Reconstructed source failed "
                f"Python syntax validation: {exc}"
            ),
        }

    return {
        "accepted": True,
        "reason": (
            "Reconstructed source is syntactically valid."
        ),
        "top_level_nodes": len(
            tree.body
        ),
    }


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
        / (
            f"package_round_"
            f"{round_number:02d}.tar.gz"
        )
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

    if not isinstance(
        history,
        list,
    ):
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
            "feedback_role": (
                "observational_only"
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
        _read_json(
            result_path
        )
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
# Result helper
# ============================================================


def _pipeline_error(
    package_output: Path,
    package_name: str,
    method: str,
    round_number: int,
    round_dir: Path,
    error: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:

    result: dict[str, Any] = {
        "round": round_number,
        "method": method,
        "status": "PIPELINE_ERROR",
        "error": error,
    }

    if extra:
        result.update(extra)

    _write_json(
        round_dir / "result.json",
        result,
    )

    _save_summary(
        package_output=package_output,
        package_name=package_name,
        method=method,
        history=_load_history(package_output),
        status="PIPELINE_ERROR",
    )

    return {
        "package": package_name,
        "method": method,
        "status": "PIPELINE_ERROR",
        "round": round_number,
        "error": error,
    }


# ============================================================
# Main experiment
# ============================================================


def _run_single_round(
    archive_path: Path,
    method: str = "proposed",
    resume: bool = False,
    allow_pending: bool = False,
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

        (
            feedback_status,
            history,
        ) = _apply_dysec_feedback(
            package_output=package_output,
            history=history,
            method=method,
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

    # --------------------------------------------------------
    # Initialise package.
    # --------------------------------------------------------

    (
        _original_package,
        current_package,
    ) = _initialise_package(
        archive_path=archive_path,
        package_output=package_output,
    )

    # --------------------------------------------------------
    # Do not create another round while DySec is pending unless
    # the multi-round runner explicitly allows it.
    # --------------------------------------------------------

    if not allow_pending:

        pending = _find_latest_pending_round(
            package_output
        )

        if pending is not None:

            (
                round_number,
                round_dir,
            ) = pending

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
    # Select source.
    # --------------------------------------------------------

    structural_selection: dict[str, Any] | None = None

    if method in {
        "proposed",
        "proposed_feedback",
    }:

        structural_selection = _select_structural_source(
            package_root=current_package,
            rng=rng,
            history=history,
        )

        if structural_selection is None:

            return _pipeline_error(
                package_output=package_output,
                package_name=package_name,
                method=method,
                round_number=round_number,
                round_dir=round_dir,
                error=(
                    "No viable structural mutation target "
                    "was found within the configured target "
                    "size limits."
                ),
            )

        target_source = Path(
            structural_selection["source_path"]
        )

    else:

        target_source = _select_random_source(
            current_package,
            rng,
        )

        if target_source is None:

            return _pipeline_error(
                package_output=package_output,
                package_name=package_name,
                method=method,
                round_number=round_number,
                round_dir=round_dir,
                error=(
                    "No transformable Python source "
                    "files were found."
                ),
            )

    # --------------------------------------------------------
    # IMPORTANT FIX:
    #
    # Resolve relative path and read source for BOTH proposed
    # and non-proposed methods.
    #
    # Previously this code existed only inside the non-proposed
    # branch, which caused:
    #
    #   cannot access local variable 'source_code'
    #
    # for proposed/proposed_feedback.
    # --------------------------------------------------------

    try:

        relative_source = target_source.relative_to(
            current_package
        )

    except ValueError:

        relative_source = Path(
            target_source.name
        )

    source_path = str(
        relative_source
    )

    try:

        source_code = target_source.read_text(
            encoding="utf-8"
        )

    except (
        OSError,
        UnicodeDecodeError,
    ) as exc:

        return _pipeline_error(
            package_output=package_output,
            package_name=package_name,
            method=method,
            round_number=round_number,
            round_dir=round_dir,
            error=(
                "Unable to read target source: "
                f"{exc}"
            ),
            extra={
                "target_source": source_path,
            },
        )

    # --------------------------------------------------------
    # Save source-selection metadata for proposed methods.
    # --------------------------------------------------------

    if structural_selection is not None:

        _write_json(
            round_dir / "structural_selection.json",
            {
                key: (
                    str(value)
                    if isinstance(
                        value,
                        Path,
                    )
                    else value
                )
                for key, value in structural_selection.items()
                if key != "target"
            },
        )

    # --------------------------------------------------------
    # Build mutation plan.
    # --------------------------------------------------------

    try:

        mutation_plan = _build_mutation_plan_for_method(
            method=method,
            source_code=source_code,
            source_path=source_path,
            round_number=round_number,
            history=history,
            rng=rng,
        )

    except Exception as exc:

        return _pipeline_error(
            package_output=package_output,
            package_name=package_name,
            method=method,
            round_number=round_number,
            round_dir=round_dir,
            error=(
                "Mutation planner failed: "
                f"{type(exc).__name__}: {exc}"
            ),
            extra={
                "target_source": source_path,
            },
        )

    # --------------------------------------------------------
    # Hard structural safety gate.
    #
    # This happens BEFORE LLM generation.
    # --------------------------------------------------------

    plan_target_validation = (
        _validate_mutation_plan_target(
            mutation_plan=mutation_plan,
            source_code=source_code,
            source_path=source_path,
        )
    )

    _write_json(
        round_dir / "mutation_plan_target_validation.json",
        plan_target_validation,
    )

    if not plan_target_validation.get(
        "accepted",
        False,
    ):

        return _pipeline_error(
            package_output=package_output,
            package_name=package_name,
            method=method,
            round_number=round_number,
            round_dir=round_dir,
            error=(
                "Mutation planner selected a target "
                "that failed structural validation."
            ),
            extra={
                "target_source": source_path,
                "mutation_plan": mutation_plan,
                "mutation_plan_target_validation": (
                    plan_target_validation
                ),
            },
        )

    _write_json(
        round_dir / "mutation_plan.json",
        mutation_plan,
    )

    # --------------------------------------------------------
    # Validate target line information.
    # --------------------------------------------------------

    try:

        start_line = int(
            mutation_plan["start_line"]
        )

        end_line = int(
            mutation_plan["end_line"]
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ) as exc:

        return _pipeline_error(
            package_output=package_output,
            package_name=package_name,
            method=method,
            round_number=round_number,
            round_dir=round_dir,
            error=(
                "Mutation plan does not contain "
                "valid start_line/end_line values: "
                f"{exc}"
            ),
            extra={
                "target_source": source_path,
                "mutation_plan": mutation_plan,
            },
        )

    # --------------------------------------------------------
    # Extract exact target source.
    # --------------------------------------------------------

    try:

        (
            source_prefix,
            target_source_code,
            source_suffix,
        ) = _extract_source_region(
            source_code=source_code,
            start_line=start_line,
            end_line=end_line,
        )

    except ValueError as exc:

        return _pipeline_error(
            package_output=package_output,
            package_name=package_name,
            method=method,
            round_number=round_number,
            round_dir=round_dir,
            error=(
                "Unable to extract mutation target: "
                f"{exc}"
            ),
            extra={
                "target_source": source_path,
                "mutation_plan": mutation_plan,
            },
        )

    # --------------------------------------------------------
    # Save original target.
    # --------------------------------------------------------

    (
        round_dir / "target_original.py"
    ).write_text(
        target_source_code,
        encoding="utf-8",
    )

    target_metadata = {
        "target_source": source_path,
        "target_type": mutation_plan.get(
            "target_type"
        ),
        "target": mutation_plan.get(
            "target"
        ),
        "start_line": start_line,
        "end_line": end_line,
        "target_line_count": len(
            target_source_code.splitlines()
        ),
        "prefix_line_count": len(
            source_prefix.splitlines()
        ),
        "suffix_line_count": len(
            source_suffix.splitlines()
        ),
        "full_source_line_count": len(
            source_code.splitlines()
        ),
    }

    _write_json(
        round_dir / "target_metadata.json",
        target_metadata,
    )

    # --------------------------------------------------------
    # Build prompt.
    # --------------------------------------------------------

    prompt = build_prompt(
        source_code=source_code,
        mutation_plan=mutation_plan,
        round_number=round_number,
        target_source=source_path,
        history=history,
        package_features=mutation_plan.get(
            "package_features"
        ),
        dysec_feedback=None,
    )

    prompt += """

OUTPUT CONTRACT

Return ONLY the transformed target region identified by the
mutation plan.

Do NOT return:
- the complete source file,
- imports outside the target,
- package metadata outside the target,
- explanations,
- Markdown fences,
- comments explaining your answer.

The returned text will be inserted between the original prefix
and suffix automatically.

Preserve the Python indentation level required by the original
target location.

The output MUST parse as exactly one Python AST node of the
same structural category as the target.
"""

    (
        round_dir / "prompt.txt"
    ).write_text(
        prompt,
        encoding="utf-8",
    )

    # --------------------------------------------------------
    # Generation.
    # --------------------------------------------------------

    try:

        generation = generate_variant(
            prompt
        )

    except Exception as exc:

        return _pipeline_error(
            package_output=package_output,
            package_name=package_name,
            method=method,
            round_number=round_number,
            round_dir=round_dir,
            error=(
                "LLM generation raised an exception: "
                f"{type(exc).__name__}: {exc}"
            ),
            extra={
                "target_source": source_path,
                "mutation_plan": mutation_plan,
            },
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
        "generation_unit": "target_region",
        "target_type": mutation_plan.get(
            "target_type"
        ),
        "target": mutation_plan.get(
            "target"
        ),
        "start_line": start_line,
        "end_line": end_line,
    }

    _write_json(
        round_dir / "generation_metadata.json",
        generation_metadata,
    )

    generated_target = generation.get(
        "code"
    )

    if (
        not generation.get("success")
        or not generated_target
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

    # --------------------------------------------------------
    # Save raw generation.
    # --------------------------------------------------------

    (
        round_dir / "generated_code.py"
    ).write_text(
        generated_target,
        encoding="utf-8",
    )

    # --------------------------------------------------------
    # Target scope validation.
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

    scope_result = _validate_generated_target_scope(
        generated_target=generated_target,
        target_type=mutation_plan.get(
            "target_type"
        ),
        candidate_features=candidate_features,
    )

    _write_json(
        round_dir / "target_scope.json",
        scope_result,
    )

    if not scope_result.get(
        "accepted",
        False,
    ):

        error = (
            "Generated output did not satisfy "
            "the target-region scope contract."
        )

        result = {
            "round": round_number,
            "method": method,
            "status": "GENERATION_SCOPE_REJECTED",
            "target_source": source_path,
            "target_type": mutation_plan.get(
                "target_type"
            ),
            "target": mutation_plan.get(
                "target"
            ),
            "mutation_plan": mutation_plan,
            "target_scope": scope_result,
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
            status="GENERATION_SCOPE_REJECTED",
        )

        return {
            "package": package_name,
            "method": method,
            "status": "GENERATION_SCOPE_REJECTED",
            "round": round_number,
            "error": error,
        }

    # --------------------------------------------------------
    # Reconstruct complete source.
    # --------------------------------------------------------

    try:

        generated_source = _reconstruct_source(
            prefix=source_prefix,
            generated_target=generated_target,
            suffix=source_suffix,
        )

    except ValueError as exc:

        error = (
            "Source reconstruction failed: "
            f"{exc}"
        )

        result = {
            "round": round_number,
            "method": method,
            "status": "RECONSTRUCTION_ERROR",
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
            status="RECONSTRUCTION_ERROR",
        )

        return {
            "package": package_name,
            "method": method,
            "status": "RECONSTRUCTION_ERROR",
            "round": round_number,
            "error": error,
        }

    (
        round_dir / "generated_source.py"
    ).write_text(
        generated_source,
        encoding="utf-8",
    )

    # --------------------------------------------------------
    # Full-source syntax validation.
    # --------------------------------------------------------

    syntax_result = _validate_full_source_syntax(
        generated_source
    )

    _write_json(
        round_dir / "generated_source_syntax.json",
        syntax_result,
    )

    if not syntax_result.get(
        "accepted",
        False,
    ):

        error = (
            "Reconstructed source failed "
            "Python syntax validation."
        )

        result = {
            "round": round_number,
            "method": method,
            "status": "SYNTAX_REJECTED",
            "target_source": source_path,
            "mutation_plan": mutation_plan,
            "syntax": syntax_result,
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
            status="SYNTAX_REJECTED",
        )

        return {
            "package": package_name,
            "method": method,
            "status": "SYNTAX_REJECTED",
            "round": round_number,
            "error": error,
        }

    # --------------------------------------------------------
    # Source guard.
    # --------------------------------------------------------

    guard_result = source_change_guard(
        original_source=source_code,
        generated_source=generated_source,
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
            "Reconstructed source failed "
            "the source-change guard."
        )

        result = {
            "round": round_number,
            "method": method,
            "status": "SOURCE_GUARD_REJECTED",
            "target_source": source_path,
            "mutation_plan": mutation_plan,
            "target_scope": scope_result,
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
        generated_source,
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
            "Reconstructed source did not pass "
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
        round_package
        / relative_source
    )

    round_target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    round_target.write_text(
        generated_source,
        encoding="utf-8",
    )

    # --------------------------------------------------------
    # Installation validation.
    # --------------------------------------------------------

    installation_result = validate_behavior(
        original_package=current_package,
        generated_package=round_package,
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
            "installation_validation": installation_result,
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
        "target_type": mutation_plan.get(
            "target_type"
        ),
        "target": mutation_plan.get(
            "target"
        ),
        "start_line": start_line,
        "end_line": end_line,
        "mutation_plan": mutation_plan,
        "artifacts": {
            "target_original": str(
                round_dir / "target_original.py"
            ),
            "generated_target": str(
                round_dir / "generated_code.py"
            ),
            "generated_source": str(
                round_dir / "generated_source.py"
            ),
            "target_scope": str(
                round_dir / "target_scope.json"
            ),
            "source_guard": str(
                round_dir / "source_guard.json"
            ),
            "diversity": str(
                round_dir / "diversity.json"
            ),
        },
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
        "start_line": start_line,
        "end_line": end_line,
        "transformation": mutation_plan.get(
            "transformation"
        ),
        "candidate_score": mutation_plan.get(
            "candidate_score"
        ),
        "candidate_features": candidate_features,
        "generation_success": True,
        "generation_unit": "target_region",
        "generation_scope_pass": True,
        "source_reconstruction": True,
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
        "generated_target": str(
            round_dir / "generated_code.py"
        ),
        "generated_source": str(
            round_dir / "generated_source.py"
        ),
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
        "target_type": mutation_plan.get(
            "target_type"
        ),
        "start_line": start_line,
        "end_line": end_line,
        "transformation": mutation_plan.get(
            "transformation"
        ),
        "mutation_plan": mutation_plan,
        "generation": {
            "unit": "target_region",
            "target_line_count": len(
                target_source_code.splitlines()
            ),
            "generated_target_line_count": len(
                _clean_generated_target(
                    generated_target
                ).splitlines()
            ),
            "full_source_line_count": len(
                generated_source.splitlines()
            ),
        },
        "target_scope": scope_result,
        "syntax": syntax_result,
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


# ============================================================
# Multi-round experiment runner
# ============================================================


def _record_failed_round(
    package_output: Path,
    package_name: str,
    method: str,
    result: dict[str, Any],
) -> list[dict[str, Any]]:

    history = _load_history(
        package_output
    )

    round_number = result.get(
        "round"
    )

    if not isinstance(
        round_number,
        int,
    ):
        return history

    existing_rounds = {
        entry.get("round")
        for entry in history
        if isinstance(entry, dict)
        and isinstance(entry.get("round"), int)
    }

    if round_number in existing_rounds:
        return history

    status = result.get(
        "status",
        "UNKNOWN",
    )

    entry: dict[str, Any] = {
        "round": round_number,
        "method": method,
        "status": status,
        "attempt_failed": True,
    }

    for key in (
        "target_source",
        "target",
        "target_type",
        "start_line",
        "end_line",
        "transformation",
        "error",
    ):
        if key in result:
            entry[key] = result[key]

    # Preserve useful planner diagnostics when present.
    if "mutation_plan" in result:
        entry["mutation_plan"] = result[
            "mutation_plan"
        ]

    if "mutation_plan_target_validation" in result:
        entry["mutation_plan_target_validation"] = (
            result[
                "mutation_plan_target_validation"
            ]
        )

    history.append(
        entry
    )

    _save_summary(
        package_output=package_output,
        package_name=package_name,
        method=method,
        history=history,
        status="CONTINUE",
    )

    return history


def _run_package_once(
    archive_path: Path,
    method: str = "proposed",
    resume: bool = False,
    allow_pending: bool = True,
) -> dict[str, Any]:

    if method not in SUPPORTED_METHODS:
        raise ValueError(
            f"Unsupported method '{method}'. "
            f"Supported methods: {sorted(SUPPORTED_METHODS)}"
        )

    archive_path = Path(
        archive_path
    ).resolve()

    if not archive_path.exists():
        raise FileNotFoundError(
            f"Package archive does not exist: {archive_path}"
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

    # --------------------------------------------------------
    # Optional resume handling.
    # --------------------------------------------------------

    if resume:

        feedback_status, history = (
            _apply_dysec_feedback(
                package_output=package_output,
                history=history,
                method=method,
            )
        )

        if feedback_status == "INVALID_DYSEC_FEEDBACK":

            _save_summary(
                package_output=package_output,
                package_name=package_name,
                method=method,
                history=history,
                status=feedback_status,
            )

            return {
                "package": package_name,
                "method": method,
                "status": feedback_status,
                "rounds": len(history),
                "history": history,
            }

    round_numbers = {
        entry.get("round")
        for entry in history
        if isinstance(entry, dict)
        and isinstance(entry.get("round"), int)
    }

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
            "rounds": len(round_numbers),
            "history": history,
        }

    results: list[dict[str, Any]] = []

    for round_number in range(
        start_round,
        EXPERIMENT_ROUNDS + 1,
    ):

        current_history = _load_history(
            package_output
        )

        current_rounds = {
            entry.get("round")
            for entry in current_history
            if isinstance(entry, dict)
            and isinstance(entry.get("round"), int)
        }

        expected_round = (
            max(current_rounds) + 1
            if current_rounds
            else 1
        )

        if expected_round != round_number:
            round_number = expected_round

        result = _run_single_round(
            archive_path=archive_path,
            method=method,
            resume=False,
            allow_pending=allow_pending,
        )

        results.append(
            result
        )

        status = result.get(
            "status",
            "UNKNOWN",
        )

        history = _load_history(
            package_output
        )

        if status not in {
            "AWAITING_DYSEC",
            "SUCCESS",
            "DETECTED",
            "MAX_ROUNDS_REACHED",
        }:

            history = _record_failed_round(
                package_output=package_output,
                package_name=package_name,
                method=method,
                result=result,
            )

        print(
            f"[{package_name}] round "
            f"{round_number:02d}/"
            f"{EXPERIMENT_ROUNDS}: {status}"
        )

        if not isinstance(
            result.get("round"),
            int,
        ):
            break

    history = _load_history(
        package_output
    )

    completed_rounds = {
        entry.get("round")
        for entry in history
        if isinstance(entry, dict)
        and isinstance(entry.get("round"), int)
    }

    final_status = (
        "MAX_ROUNDS_REACHED"
        if len(completed_rounds) >= EXPERIMENT_ROUNDS
        else "STOPPED_EARLY"
    )

    _save_summary(
        package_output=package_output,
        package_name=package_name,
        method=method,
        history=history,
        status=final_status,
    )

    return {
        "package": package_name,
        "method": method,
        "status": final_status,
        "rounds": len(completed_rounds),
        "history": history,
        "results": results,
    }


def run_package(
    archive_path: Path,
    method: str = "proposed",
    resume: bool = False,
) -> dict[str, Any]:
    """Public entry point for the multi-round experiment."""

    return _run_package_once(
        archive_path=archive_path,
        method=method,
        resume=resume,
        allow_pending=True,
    )