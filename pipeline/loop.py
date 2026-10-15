from __future__ import annotations

import ast
import hashlib
import json
import os
import random
import shutil
import textwrap
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

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
from pipeline.dysec_client import evaluate_with_dysec
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
    find_package_root,
)
from pipeline.platform_check import detect_platform_scope
from pipeline.prompt_builder import build_prompt
from pipeline.source_guard import source_change_guard
from pipeline.validator import validate_behavior


SUPPORTED_METHODS = set(EXPERIMENT_METHODS)

ProgressCallback = Callable[[dict[str, Any]], None]


class WindowsOnlyPackageError(Exception):
    """
    Raised when a package is identified as Windows-only during
    initialisation. The package is rejected before any mutation round
    runs, since the validation sandbox and the detector are Linux-based
    and a Windows-only package cannot be meaningfully assessed here.
    """

    def __init__(self, reason: str, evidence: str | None):
        self.reason = reason
        self.evidence = evidence
        super().__init__(reason)


def _emit_progress(
    callback: ProgressCallback | None,
    *,
    phase: str,
    message: str,
    round_number: int | None = None,
    status: str = "RUNNING",
    gate: str | None = None,
    gate_status: str | None = None,
    error: str | None = None,
    **extra: Any,
) -> None:
    """Emit live progress and code streams to the terminal and dashboard."""
    event: dict[str, Any] = {
        "phase": phase,
        "message": message,
        "round": round_number,
        "status": status,
        "timestamp": time.time(),
        **extra,
    }

    if gate is not None:
        event["gate"] = gate
    if gate_status is not None:
        event["gate_status"] = gate_status
    if error is not None:
        event["error"] = error

    print(f"[PROGRESS] {message}", flush=True)

    if callback is not None:
        try:
            callback(event)
        except Exception as exc:
            print(f"[PROGRESS] Callback warning: {exc}", flush=True)


TRANSFORMATIONS = (
    "instruction_substitution",
    "control_flow_flattening",
    "polymorphic_encryption",
    "opaque_predicates",
    "dead_code_insertion",
    "optimize",
    "harden",
    "refactor",
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
# Atomic JSON File Operations
# ============================================================


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Atomically write JSON data using a temporary file and rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f".tmp_{os.getpid()}_{time.time_ns()}")
    try:
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        temp_path.replace(path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def _read_json(path: Path) -> dict[str, Any] | None:
    """Safely read and parse JSON file, returning None on missing or corrupted files."""
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        return None
    return None


# ============================================================
# Reproducible Randomness & Target Helpers
# ============================================================


def _build_rng(package_name: str, method: str) -> random.Random:
    """Build a deterministic random generator tied to seed, package, and method."""
    seed_material = f"{EXPERIMENT_SEED}:{package_name}:{method}"
    digest = hashlib.sha256(seed_material.encode("utf-8")).digest()
    seed = int.from_bytes(digest[:8], byteorder="big", signed=False)
    return random.Random(seed)


def _target_limit(target_type: str | None) -> int | None:
    """Return maximum line budget permitted for the target structural type."""
    if target_type == "function":
        return MAX_FUNCTION_LINES
    if target_type == "class":
        return MAX_CLASS_LINES
    if target_type == "module_block":
        return MAX_MODULE_BLOCK_LINES
    return None


def _candidate_transformations(
    target_type: str,
    block_type: str | None = None,
) -> tuple[str, ...]:
    """Identify feasible transformation strategies based on target AST properties."""
    if target_type in {"function", "class"}:
        return TRANSFORMATIONS

    if target_type == "module_block":
        if block_type in {
            "if", "for", "async_for", "while", "try", "with", "async_with", "match"
        }:
            return ("control_flow_flattening", "opaque_predicates")
        if block_type in {
            "expression", "assignment", "annotated_assignment",
            "augmented_assignment", "return", "raise", "assert", "delete"
        }:
            return ("instruction_substitution", "polymorphic_encryption")

    return ()


def _history_attempted_keys(
    history: list[dict[str, Any]],
) -> set[tuple[str, str, str, int, int, str | None]]:
    """Extract unique target mutation tuples already attempted in previous rounds."""
    attempted: set[tuple[str, str, str, int, int, str | None]] = set()
    for entry in history:
        source = entry.get("target_source")
        target_type = entry.get("target_type")
        target = entry.get("target")
        start_line = entry.get("start_line")
        end_line = entry.get("end_line")
        transformation = entry.get("transformation")

        if (
            not source
            or not target_type
            or not target
            or not isinstance(start_line, int)
            or not isinstance(end_line, int)
        ):
            continue

        attempted.add(
            (
                str(source),
                str(target_type),
                str(target),
                start_line,
                end_line,
                str(transformation) if transformation else None,
            )
        )
    return attempted


# ============================================================
# Source & Structural Target Selection
# ============================================================


def _collect_python_sources(package_root: Path) -> dict[str, str]:
    """
    Read every transformable Python file in the package into a
    {relative_path: source_text} mapping, for use by the platform-scope
    check. Files that cannot be decoded as UTF-8 text are skipped; they
    are not evidence of platform scope and the existing syntax gate
    handles unreadable sources separately.
    """
    sources: dict[str, str] = {}

    for path in collect_transformable_python_files(package_root):
        try:
            relative = str(path.relative_to(package_root))
        except ValueError:
            relative = str(path)

        try:
            sources[relative] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

    return sources


def _select_random_source(package_root: Path, rng: random.Random) -> Path | None:
    """Uniformly select a transformable Python file from package root."""
    candidates = collect_transformable_python_files(package_root)
    return rng.choice(candidates) if candidates else None


def _structural_candidates_for_source(
    source_path: Path,
    package_root: Path,
) -> list[dict[str, Any]]:
    """Scan and parse Python file into viable mutation target candidates."""
    try:
        source_code = source_path.read_text(encoding="utf-8")
        source_targets = find_source_targets(source_code)
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return []

    candidates: list[dict[str, Any]] = []
    try:
        relative_path = source_path.resolve().relative_to(package_root.resolve())
    except ValueError:
        relative_path = Path(source_path.name)

    for target in source_targets.functions:
        if target.name.startswith("__"):
            continue
        start_line, end_line = target.lineno, target.end_lineno
        line_count = end_line - start_line + 1
        if end_line >= start_line and line_count <= MAX_FUNCTION_LINES:
            candidates.append({
                "source_path": source_path,
                "relative_source": str(relative_path),
                "target": target,
                "target_type": "function",
                "target_name": target.qualified_name,
                "start_line": start_line,
                "end_line": end_line,
                "target_line_count": line_count,
                "block_type": None,
            })

    for target in source_targets.classes:
        start_line, end_line = target.lineno, target.end_lineno
        line_count = end_line - start_line + 1
        if end_line >= start_line and line_count <= MAX_CLASS_LINES:
            candidates.append({
                "source_path": source_path,
                "relative_source": str(relative_path),
                "target": target,
                "target_type": "class",
                "target_name": target.qualified_name,
                "start_line": start_line,
                "end_line": end_line,
                "target_line_count": line_count,
                "block_type": None,
            })

    for target in source_targets.module_blocks:
        start_line, end_line = target.lineno, target.end_lineno
        line_count = end_line - start_line + 1
        if end_line >= start_line and line_count <= MAX_MODULE_BLOCK_LINES:
            candidates.append({
                "source_path": source_path,
                "relative_source": str(relative_path),
                "target": target,
                "target_type": "module_block",
                "target_name": target.name,
                "start_line": start_line,
                "end_line": end_line,
                "target_line_count": line_count,
                "block_type": target.block_type,
            })

    return candidates


def _select_structural_source(
    package_root: Path,
    rng: random.Random,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Select an unattempted structural target prioritizing functions and classes."""
    package_root = package_root.resolve()
    history = history or []

    source_files = collect_transformable_python_files(package_root)
    candidates: list[dict[str, Any]] = []

    for source_path in source_files:
        candidates.extend(
            _structural_candidates_for_source(source_path, package_root)
        )

    if not candidates:
        return None

    attempted = _history_attempted_keys(history)
    unattempted: list[dict[str, Any]] = []

    for candidate in candidates:
        compatible = _candidate_transformations(
            target_type=candidate["target_type"],
            block_type=candidate.get("block_type"),
        )
        if not compatible:
            continue

        candidate["compatible_transformations"] = compatible
        has_unattempted = any(
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
        if has_unattempted:
            unattempted.append(candidate)

    pool = unattempted if unattempted else candidates
    if not pool:
        return None

    pool.sort(
        key=lambda c: (
            TARGET_PRIORITY.get(c["target_type"], 99),
            c["target_line_count"],
            c["relative_source"],
            c["start_line"],
            c["target_name"],
        )
    )

    best_priority = TARGET_PRIORITY.get(pool[0]["target_type"], 99)
    best_size = pool[0]["target_line_count"]

    top_pool = [
        cand
        for cand in pool
        if TARGET_PRIORITY.get(cand["target_type"], 99) == best_priority
        and cand["target_line_count"] == best_size
    ]
    return rng.choice(top_pool)


# ============================================================
# Mutation Plan Construction
# ============================================================


def _find_function_targets(source_code: str) -> list[dict[str, Any]]:
    """Parse source string and locate non-dunder functions within budget."""
    try:
        targets = find_functions(source_code)
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
        and (target.end_lineno - target.lineno + 1) <= MAX_FUNCTION_LINES
    ]


def _select_random_function(
    source_code: str, rng: random.Random
) -> dict[str, Any] | None:
    candidates = _find_function_targets(source_code)
    return rng.choice(candidates) if candidates else None


def _select_function_level_target(
    source_code: str,
    source_path: str,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    candidates = _find_function_targets(source_code)
    if not candidates:
        return None

    history = history or []
    attempted_targets = {
        (str(entry.get("target_source")), str(entry.get("target")))
        for entry in history
        if entry.get("target_source") and entry.get("target")
    }

    for candidate in candidates:
        if (source_path, candidate["qualified_name"]) not in attempted_targets:
            return candidate

    return candidates[0]


def _build_random_plan(
    source_code: str,
    source_path: str,
    round_number: int,
    rng: random.Random,
) -> dict[str, Any]:
    target = _select_random_function(source_code, rng)
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
            "reason": "No transformable functions were found.",
        }

    return {
        "round": round_number,
        "method": "random",
        "target_type": "function",
        "target": target["qualified_name"],
        "target_source": source_path,
        "target_functions": [target],
        "start_line": target["start_line"],
        "end_line": target["end_line"],
        "transformation": rng.choice(TRANSFORMATIONS),
        "candidate_score": None,
        "candidate_features": {
            "selection": "uniform_random",
            "start_line": target["start_line"],
            "end_line": target["end_line"],
            "lines": target["end_line"] - target["start_line"] + 1,
        },
        "package_features": {},
        "reason": "Function target and transformation were selected uniformly at random.",
    }


def _build_function_level_plan(
    source_code: str,
    source_path: str,
    round_number: int,
    history: list[dict[str, Any]],
    rng: random.Random,
) -> dict[str, Any]:
    target = _select_function_level_target(source_code, source_path, history)
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
            "reason": "No transformable functions were found.",
        }

    return {
        "round": round_number,
        "method": "function_level",
        "target_type": "function",
        "target": target["qualified_name"],
        "target_source": source_path,
        "target_functions": [target],
        "start_line": target["start_line"],
        "end_line": target["end_line"],
        "transformation": rng.choice(TRANSFORMATIONS),
        "candidate_score": None,
        "candidate_features": {
            "selection": "function_level",
            "start_line": target["start_line"],
            "end_line": target["end_line"],
            "lines": target["end_line"] - target["start_line"] + 1,
        },
        "package_features": {},
        "reason": "Function target was selected using function-level structural information.",
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
    plan["method"] = "proposed_feedback" if feedback_enabled else "proposed"
    plan["feedback_enabled"] = feedback_enabled

    if feedback_enabled:
        plan["feedback_history"] = [
            {
                "round": entry.get("round"),
                "target_source": entry.get("target_source"),
                "target": entry.get("target"),
                "transformation": entry.get("transformation"),
                "dysec_verdict": entry.get("dysec_verdict"),
                "dysec_features": (entry.get("dysec") or {}).get("features"),
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
        return _build_random_plan(source_code, source_path, round_number, rng)
    if method == "function_level":
        return _build_function_level_plan(source_code, source_path, round_number, history, rng)
    if method == "proposed":
        return _build_proposed_plan(source_code, source_path, round_number, history, False)
    if method == "proposed_feedback":
        return _build_proposed_plan(source_code, source_path, round_number, history, True)

    strategy_mapping = {
        "strategy_substitution": "instruction_substitution",
        "strategy_flattening": "control_flow_flattening",
        "strategy_encryption": "polymorphic_encryption",
        "strategy_opaque": "opaque_predicates",
    }

    if method in strategy_mapping:
        plan = _build_proposed_plan(source_code, source_path, round_number, history, feedback_enabled=True)
        plan["method"] = method
        plan["transformation"] = strategy_mapping[method]
        plan["reason"] = f"Forced single-strategy evaluation: {strategy_mapping[method]}"
        return plan

    if method == "proposed_heavy":
        plan = _build_proposed_plan(source_code, source_path, round_number, history, feedback_enabled=True)
        plan["method"] = "proposed_heavy"
        plan["transformation"] = "control_flow_flattening"  # Trục chính là flattening
        plan["heavy_mode"] = True
        # NOTE: this forces control_flow_flattening with feedback-aware
        # target selection. It does NOT implement API indirection or
        # string obfuscation -- no such logic exists in this pipeline.
        # The reason string must describe only what the code does, not
        # what the method name implies, or results reported under
        # "proposed_heavy" will misstate what was actually run.
        plan["reason"] = (
            "Forced single-strategy evaluation: control_flow_flattening, "
            "with DySec-feedback-aware target ranking (same ranking as "
            "proposed_feedback)."
        )
        return plan

    raise ValueError(f"Unsupported method: {method}")


# ============================================================
# AST Target Identity Verification
# ============================================================


def _find_matching_function(
    tree: ast.AST, target_name: str, start_line: int, end_line: int
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    simple_name = target_name.rsplit(".", 1)[-1]
    matches = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == simple_name
        and getattr(node, "lineno", None) == start_line
        and getattr(node, "end_lineno", None) == end_line
    ]
    return matches[0] if len(matches) == 1 else None


def _find_matching_class(
    tree: ast.AST, target_name: str, start_line: int, end_line: int
) -> ast.ClassDef | None:
    simple_name = target_name.rsplit(".", 1)[-1]
    matches = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and node.name == simple_name
        and getattr(node, "lineno", None) == start_line
        and getattr(node, "end_lineno", None) == end_line
    ]
    return matches[0] if len(matches) == 1 else None


def _find_matching_module_block(
    source_code: str, target_name: str, start_line: int, end_line: int, block_type: str | None
) -> dict[str, Any] | None:
    try:
        source_targets = find_source_targets(source_code)
    except (SyntaxError, ValueError):
        return None

    matches = [
        target for target in source_targets.module_blocks
        if target.name == target_name
        and target.lineno == start_line
        and target.end_lineno == end_line
        and (not block_type or target.block_type == block_type)
    ]
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
    mutation_plan: dict[str, Any], source_code: str, source_path: str
) -> dict[str, Any]:
    """Verify that selected target matches actual source code AST and bounds."""
    target_type = mutation_plan.get("target_type")
    target = mutation_plan.get("target")
    planned_source = mutation_plan.get("target_source")

    if not target or not isinstance(target, str):
        return {"accepted": False, "reason": "Mutation plan target missing or invalid."}

    if planned_source is not None and str(planned_source) != str(source_path):
        return {
            "accepted": False,
            "reason": "Mutation planner selected target from another file.",
            "planned_source": str(planned_source),
            "actual_source": str(source_path),
        }

    try:
        start_line = int(mutation_plan["start_line"])
        end_line = int(mutation_plan["end_line"])
    except (KeyError, TypeError, ValueError) as exc:
        return {"accepted": False, "reason": f"Invalid line info: {exc}"}

    if start_line < 1 or end_line < start_line:
        return {"accepted": False, "reason": "Invalid line range."}

    target_line_count = end_line - start_line + 1
    limit = _target_limit(target_type)
    if limit is None:
        return {"accepted": False, "reason": f"Unsupported target type: {target_type}"}

    if target_line_count > limit:
        return {
            "accepted": False,
            "reason": "Mutation target exceeds configured structural size limit.",
            "target_line_count": target_line_count,
            "maximum_allowed_lines": limit,
        }

    try:
        tree = ast.parse(source_code)
    except SyntaxError as exc:
        return {"accepted": False, "reason": f"Source is not valid Python: {exc}"}

    candidate_features = mutation_plan.get("candidate_features") or {}
    matched_node = None
    matched_block = None

    if target_type == "function":
        matched_node = _find_matching_function(tree, target, start_line, end_line)
    elif target_type == "class":
        matched_node = _find_matching_class(tree, target, start_line, end_line)
    elif target_type == "module_block":
        matched_block = _find_matching_module_block(
            source_code, target, start_line, end_line, candidate_features.get("block_type")
        )

    if target_type in {"function", "class"} and matched_node is None:
        return {"accepted": False, "reason": "Target could not be matched uniquely against AST."}

    if target_type == "module_block" and matched_block is None:
        return {"accepted": False, "reason": "Target module block could not be matched against AST."}

    return {
        "accepted": True,
        "reason": "Target passed structural validation.",
        "target_type": target_type,
        "target": target,
        "source_path": source_path,
        "start_line": start_line,
        "end_line": end_line,
        "target_line_count": target_line_count,
        "maximum_allowed_lines": limit,
    }


# ============================================================
# Target Source Region Extraction & Reconstruction
# ============================================================


def _extract_source_region(
    source_code: str, start_line: int, end_line: int
) -> tuple[str, str, str]:
    """Slice source code into leading prefix, target block, and trailing suffix."""
    lines = source_code.splitlines(keepends=True)
    if start_line < 1 or end_line < start_line or end_line > len(lines):
        raise ValueError(f"Invalid range {start_line}-{end_line} for {len(lines)} lines")

    prefix = "".join(lines[: start_line - 1])
    target = "".join(lines[start_line - 1 : end_line])
    suffix = "".join(lines[end_line:])
    return prefix, target, suffix


def _clean_generated_target(generated_target: str) -> str:
    """Normalize line endings and strip markdown code fences."""
    generated_target = generated_target.replace("\r\n", "\n").replace("\r", "\n")
    lines = generated_target.splitlines(keepends=True)

    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    if len(lines) >= 2 and lines[0].strip().startswith("```") and lines[-1].strip() == "```":
        lines = lines[1:-1]

    return "".join(lines)


def _reconstruct_source(
    prefix: str, generated_target: str, suffix: str, target_indentation: int = 0
) -> str:
    """Safely splice generated target into prefix and suffix while enforcing indentation."""
    cleaned = _clean_generated_target(generated_target)
    if not cleaned.strip():
        raise ValueError("Generated target is empty.")

    dedented = textwrap.dedent(cleaned).strip()
    indented_target = textwrap.indent(dedented, " " * target_indentation)

    reconstructed = prefix
    if reconstructed and not reconstructed.endswith("\n"):
        reconstructed += "\n"

    reconstructed += indented_target

    if suffix:
        if not reconstructed.endswith("\n") and not suffix.startswith("\n"):
            reconstructed += "\n"
        reconstructed += suffix

    return reconstructed


# ============================================================
# Scope & Syntax Validation Gates
# ============================================================


def _validate_generated_target_scope(
    generated_target: str,
    target_type: str | None,
    candidate_features: dict[str, Any],
) -> dict[str, Any]:
    """Verify that generated code parses into exactly one target AST node type."""
    cleaned = _clean_generated_target(generated_target)
    if not cleaned.strip():
        return {"accepted": False, "reason": "Generated target is empty.", "target_type": target_type}

    try:
        tree = ast.parse(textwrap.dedent(cleaned))
    except SyntaxError as exc:
        return {"accepted": False, "reason": f"Syntax error in target: {exc}", "target_type": target_type}

    if target_type == "function":
        expected = {ast.FunctionDef, ast.AsyncFunctionDef}
    elif target_type == "class":
        expected = {ast.ClassDef}
    elif target_type == "module_block":
        expected = {
            ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try,
            ast.With, ast.AsyncWith, ast.Expr, ast.Assign, ast.AnnAssign, ast.AugAssign
        }
    else:
        return {"accepted": False, "reason": "No expected AST type.", "target_type": target_type}

    if len(tree.body) != 1:
        return {
            "accepted": False,
            "reason": "Must contain exactly one top-level target node.",
            "top_level_node_count": len(tree.body),
        }

    actual_type = type(tree.body[0])
    accepted = actual_type in expected
    return {
        "accepted": accepted,
        "reason": "Valid target structure" if accepted else "Mismatch target AST structure",
        "actual_node_type": actual_type.__name__,
        "top_level_node_count": len(tree.body),
    }


def _validate_full_source_syntax(source_code: str) -> dict[str, Any]:
    """Verify that fully reconstructed source parses as valid Python."""
    try:
        tree = ast.parse(source_code)
    except SyntaxError as exc:
        return {"accepted": False, "reason": f"Syntax error: {exc}"}

    return {"accepted": True, "top_level_nodes": len(tree.body)}


# ============================================================
# Package Artifacts & History Logging
# ============================================================


def _create_round_archive(
    round_package: Path, round_dir: Path, round_number: int
) -> Path:
    """Pack candidate variant directory into tar.gz distribution archive."""
    archive_path = round_dir / f"package_round_{round_number:02d}.tar.gz"
    return create_package_archive(package_root=round_package, archive_path=archive_path)


def _load_history(package_output: Path) -> list[dict[str, Any]]:
    """Load evaluation history list from package summary.json."""
    summary = _read_json(package_output / "summary.json")
    if not summary:
        return []
    history = summary.get("history", [])
    return [item for item in history if isinstance(item, dict)] if isinstance(history, list) else []


def _summarize_validation_history(history: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize validation outcomes across rounds."""
    counts = {
        "baseline_installation_failed": 0,
        "mutant_installation_failed": 0,
        "validation_timeout": 0,
        "validation_inconclusive": 0,
        "installation_passed": 0,
        "other_round_failures": 0,
    }

    for entry in history:
        status = str(entry.get("validation_status") or entry.get("status") or "").upper()
        if status == "BASELINE_INSTALLATION_FAILED":
            counts["baseline_installation_failed"] += 1
        elif status == "MUTANT_INSTALLATION_FAILED":
            counts["mutant_installation_failed"] += 1
        elif status == "VALIDATION_TIMEOUT":
            counts["validation_timeout"] += 1
        elif status == "VALIDATION_INCONCLUSIVE":
            counts["validation_inconclusive"] += 1
        elif status in {"INSTALLATION_PASSED", "AWAITING_DYSEC", "DETECTED", "SUCCESS"}:
            counts["installation_passed"] += 1
        elif entry.get("attempt_failed", False):
            counts["other_round_failures"] += 1

    eligible = counts["mutant_installation_failed"] + counts["installation_passed"]
    return {
        "rounds_recorded": len(history),
        "counts": counts,
        "eligible_installation_attempts": eligible,
        "installation_success_rate": (counts["installation_passed"] / eligible) if eligible else None,
    }


def _save_summary(
    package_output: Path,
    package_name: str,
    method: str,
    history: list[dict[str, Any]],
    status: str,
) -> None:
    """Persist structured summary state to disk."""
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
        "validation_metrics": _summarize_validation_history(history),
        "dysec_io": {
            "enabled": True,
            "method": "api_and_manual",
            "status": "PENDING" if status == "AWAITING_DYSEC" else status,
        },
    }
    _write_json(package_output / "summary.json", summary)


# ============================================================
# DySec Feedback & Resume Logic
# ============================================================


def _find_latest_pending_round(package_output: Path) -> tuple[int, Path] | None:
    """Find the most recent round directory awaiting external DySec evaluation."""
    if not package_output.exists():
        return None

    for round_dir in sorted(package_output.glob("round_*"), reverse=True):
        if not round_dir.is_dir():
            continue
        artifact = _read_json(round_dir / "artifact.json")
        if artifact and artifact.get("status") in {"ARTIFACT_READY", "AWAITING_DYSEC"}:
            round_number = artifact.get("round")
            if isinstance(round_number, int):
                return round_number, round_dir
    return None


def _load_dysec_feedback(round_dir: Path) -> dict[str, Any] | None:
    """Read dysec.json feedback file placed in round directory."""
    return _read_json(round_dir / "dysec.json")


def _normalise_dysec_verdict(feedback: dict[str, Any]) -> str | None:
    """Standardize DySec verdict strings into canonical categories."""
    verdict = feedback.get("verdict")
    if isinstance(verdict, str):
        v = verdict.strip().upper()
        if v in {"DETECTED", "NOT_DETECTED", "MALICIOUS", "BENIGN"}:
            return "NOT_DETECTED" if v in {"NOT_DETECTED", "BENIGN"} else "DETECTED"
    return None


def _update_history_feedback(
    history: list[dict[str, Any]], round_number: int, feedback: dict[str, Any], verdict: str
) -> None:
    """Update or append DySec evaluation feedback to history log."""
    for entry in history:
        if entry.get("round") == round_number:
            entry["dysec"] = feedback
            entry["dysec_verdict"] = verdict
            entry["status"] = "SUCCESS" if verdict == "NOT_DETECTED" else "DETECTED"
            return
    history.append({
        "round": round_number,
        "dysec": feedback,
        "dysec_verdict": verdict,
        "status": "SUCCESS" if verdict == "NOT_DETECTED" else "DETECTED",
    })


def _apply_dysec_feedback(
    package_output: Path, history: list[dict[str, Any]], method: str
) -> tuple[str, list[dict[str, Any]]]:
    """Process pending DySec verdicts and advance package state."""
    pending = _find_latest_pending_round(package_output)
    if pending is None:
        return "NO_PENDING_ROUND", history

    round_number, round_dir = pending
    feedback = _load_dysec_feedback(round_dir)
    if feedback is None:
        return "AWAITING_DYSEC", history

    verdict = _normalise_dysec_verdict(feedback)
    if verdict is None:
        return "INVALID_DYSEC_FEEDBACK", history

    result_path = round_dir / "result.json"
    result = _read_json(result_path) or {}
    result["dysec"] = feedback
    result["dysec_verdict"] = verdict
    result["status"] = "SUCCESS" if verdict == "NOT_DETECTED" else "DETECTED"

    _update_history_feedback(history, round_number, feedback, verdict)
    _write_json(result_path, result)

    next_status = "SUCCESS" if verdict == "NOT_DETECTED" else "CONTINUE"
    _save_summary(package_output, package_output.name, method, history, next_status)
    return next_status, history


# ============================================================
# Package Workspace Initialization & Error Logging
# ============================================================


def _initialise_package(
    archive_path: Path, package_output: Path, resume: bool = False
) -> tuple[Path, Path]:
    """Initialize package directories for a new run or resume."""
    original_extract = package_output / "original_extract"
    original_package = package_output / "original"
    current_package = package_output / "current"

    package_output.mkdir(parents=True, exist_ok=True)

    if not resume:
        for directory in (original_extract, original_package, current_package):
            if directory.exists():
                shutil.rmtree(directory)

    if not original_extract.exists():
        original_extract.mkdir(parents=True, exist_ok=True)
        extracted_package = extract_package(archive_path, original_extract)
    else:
        extracted_package = find_package_root(original_extract)

    # Reject Windows-only packages before any mutation round runs. This
    # is a property of the package, not of a given round, so it is
    # checked once at initialisation rather than re-checked per round.
    platform_scope = detect_platform_scope(
        extracted_package,
        _collect_python_sources(extracted_package),
    )

    if platform_scope["windows_only"]:
        raise WindowsOnlyPackageError(
            reason=platform_scope["reason"],
            evidence=platform_scope["evidence"],
        )

    if not original_package.exists():
        copy_package(extracted_package, original_package)

    if not current_package.exists():
        copy_package(extracted_package, current_package)

    return original_package, current_package


def _pipeline_error(
    package_output: Path,
    package_name: str,
    method: str,
    round_number: int,
    round_dir: Path,
    error: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Standardized handler for recording fatal pipeline exceptions."""
    result: dict[str, Any] = {
        "round": round_number,
        "method": method,
        "status": "PIPELINE_ERROR",
        "error": error,
    }
    if extra:
        result.update(extra)

    _write_json(round_dir / "result.json", result)
    history = _load_history(package_output)
    _save_summary(package_output, package_name, method, history, "PIPELINE_ERROR")

    return {
        "package": package_name,
        "method": method,
        "status": "PIPELINE_ERROR",
        "round": round_number,
        "error": error,
    }


# ============================================================
# Core Single Round Execution Pipeline
# ============================================================


def _run_single_round(
    archive_path: Path,
    method: str = "proposed",
    resume: bool = False,
    allow_pending: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Execute one end-to-end iteration of mutation, validation, and DySec evaluation."""
    if method not in SUPPORTED_METHODS:
        raise ValueError(f"Unsupported method '{method}'")

    round_start_time = time.time()
    archive_path = Path(archive_path).resolve()
    package_name = archive_path.name
    if package_name.endswith(".tar.gz"):
        package_name = package_name[:-7]
    elif package_name.endswith(".tgz"):
        package_name = package_name[:-4]

    package_output = OUTPUT_DIR / method / package_name
    package_output.mkdir(parents=True, exist_ok=True)
    history = _load_history(package_output)
    rng = _build_rng(package_name, method)

    if resume:
        feedback_status, history = _apply_dysec_feedback(package_output, history, method)
        if feedback_status in {"SUCCESS", "AWAITING_DYSEC", "INVALID_DYSEC_FEEDBACK"}:
            return {
                "package": package_name,
                "method": method,
                "status": feedback_status,
                "round": history[-1].get("round") if history else 1,
                "rounds": len(history),
                "history": history,
            }

    _initialise_package(archive_path, package_output, resume=True)
    current_package = package_output / "current"

    if not allow_pending:
        pending = _find_latest_pending_round(package_output)
        if pending is not None:
            round_num, round_dir = pending
            if _load_dysec_feedback(round_dir) is None:
                _save_summary(package_output, package_name, method, history, "AWAITING_DYSEC")
                return {
                    "package": package_name,
                    "method": method,
                    "status": "AWAITING_DYSEC",
                    "round": round_num,
                    "rounds": len(history),
                    "history": history,
                }

    round_numbers = [e.get("round") for e in history if isinstance(e.get("round"), int)]
    round_number = (max(round_numbers) + 1) if round_numbers else 1

    if round_number > EXPERIMENT_ROUNDS:
        _save_summary(package_output, package_name, method, history, "MAX_ROUNDS_REACHED")
        return {
            "package": package_name,
            "method": method,
            "status": "MAX_ROUNDS_REACHED",
            "round": round_number,
            "rounds": len(history),
            "history": history,
        }

    round_dir = package_output / f"round_{round_number:02d}"
    round_dir.mkdir(parents=True, exist_ok=True)
    _emit_progress(
        progress_callback,
        phase="SOURCE_SELECTION",
        message=f"Round {round_number}: selecting source and mutation target",
        round_number=round_number,
    )

    # 3. Source Selection Phase
    if method in {"proposed", "proposed_feedback"}:
        structural_selection = _select_structural_source(current_package, rng, history)
        if structural_selection is None:
            return _pipeline_error(
                package_output, package_name, method, round_number, round_dir,
                "No viable structural target found.",
            )
        target_source = Path(structural_selection["source_path"])
    else:
        target_source = _select_random_source(current_package, rng)
        if target_source is None:
            return _pipeline_error(
                package_output, package_name, method, round_number, round_dir,
                "No transformable Python files found.",
            )

    try:
        relative_source = target_source.resolve().relative_to(current_package.resolve())
    except ValueError:
        relative_source = Path(target_source.name)

    source_path = str(relative_source)
    try:
        source_code = target_source.read_text(encoding="utf-8")
    except Exception as exc:
        return _pipeline_error(
            package_output, package_name, method, round_number, round_dir,
            f"Unable to read target source: {exc}", extra={"target_source": source_path}
        )

    _emit_progress(
        progress_callback,
        phase="MUTATION_PLANNING",
        message=f"Round {round_number}: building and verifying mutation plan",
        round_number=round_number,
    )

    # 4. Mutation Plan Construction & Verification
    try:
        mutation_plan = _build_mutation_plan_for_method(
            method, source_code, source_path, round_number, history, rng
        )
    except Exception as exc:
        return _pipeline_error(
            package_output, package_name, method, round_number, round_dir,
            f"Mutation planner failed: {exc}", extra={"target_source": source_path}
        )

    plan_validation = _validate_mutation_plan_target(mutation_plan, source_code, source_path)
    _write_json(round_dir / "mutation_plan_target_validation.json", plan_validation)
    if not plan_validation.get("accepted", False):
        return _pipeline_error(
            package_output, package_name, method, round_number, round_dir,
            "Mutation target failed structural validation.",
            extra={"mutation_plan": mutation_plan, "validation": plan_validation}
        )

    _emit_progress(
        progress_callback,
        phase="MUTATION_PLANNING",
        message=f"Round {round_number}: mutation plan passed structural verification",
        round_number=round_number,
        gate="mutation_plan",
        gate_status="PASSED",
    )

    _write_json(round_dir / "mutation_plan.json", mutation_plan)
    start_line = int(mutation_plan["start_line"])
    end_line = int(mutation_plan["end_line"])

    source_prefix, target_source_code, source_suffix = _extract_source_region(
        source_code, start_line, end_line
    )
    first_line = target_source_code.splitlines()[0] if target_source_code.splitlines() else ""
    target_indentation = len(first_line) - len(first_line.lstrip())

    (round_dir / "target_original.py").write_text(target_source_code, encoding="utf-8")

    # Emit target_code immediately so the web UI displays the original snippet right away
    _emit_progress(
        progress_callback,
        phase="LLM_GENERATION",
        message=f"Round {round_number}: target '{mutation_plan.get('target')}' extracted, querying LLM...",
        round_number=round_number,
        target_code=target_source_code,
    )

    # 5. Prompt Construction & LLM Generation
    latest_dysec_feedback = history[-1].get("dysec") if history else None
    prompt = build_prompt(
        source_code=source_code,
        mutation_plan=mutation_plan,
        round_number=round_number,
        target_source=source_path,
        history=history,
        package_features=mutation_plan.get("package_features"),
        dysec_feedback=latest_dysec_feedback if method == "proposed_feedback" else None,
    )
    prompt += "\n\nOUTPUT CONTRACT:\nReturn ONLY the transformed code snippet without markdown fences or explanations.\n"
    (round_dir / "prompt.txt").write_text(prompt, encoding="utf-8")

    def _on_llm_chunk(chunk: str) -> None:
        _emit_progress(
            progress_callback,
            phase="LLM_GENERATION",
            message=f"Round {round_number}: streaming LLM code...",
            round_number=round_number,
            streaming_code_chunk=chunk,
        )

    t_gen_start = time.monotonic()

    try:
        try:
            generation = generate_variant(prompt, stream_callback=_on_llm_chunk)
        except TypeError:
            generation = generate_variant(prompt)
    except Exception as exc:
        llm_latency = time.monotonic() - t_gen_start
        result = {
            "round": round_number,
            "method": method,
            "status": "GENERATION_ERROR",
            "error": f"LLM generation exception: {exc}",
            "target_code": target_source_code,
            "latency": {"llm_seconds": llm_latency},
            "token_usage": None,
        }
        _write_json(round_dir / "result.json", result)
        _emit_progress(
            progress_callback,
            phase="LLM_GENERATION",
            message=f"Round {round_number}: LLM generation failed",
            round_number=round_number,
            status="FAILED",
            gate="llm_generation",
            gate_status="REJECTED",
            error=str(exc),
        )
        return {
            "package": package_name,
            "method": method,
            "status": "GENERATION_ERROR",
            "round": round_number,
            "error": str(exc),
            "target_code": target_source_code,
            "token_usage": None,
        }

    llm_latency = float(generation.get("latency_seconds") or (time.monotonic() - t_gen_start))
    generated_target = generation.get("code")
    token_usage = generation.get("tokens")

    if generated_target:
        (round_dir / "llm_output.py").write_text(generated_target, encoding="utf-8")

    llm_passed = bool(generation.get("success") and generated_target)
    _emit_progress(
        progress_callback,
        phase="LLM_GENERATION",
        message=(
            f"Round {round_number}: LLM generated candidate code"
            if llm_passed
            else f"Round {round_number}: LLM did not generate usable code"
        ),
        round_number=round_number,
        gate="llm_generation",
        gate_status="PASSED" if llm_passed else "REJECTED",
        status="PASSED" if llm_passed else "FAILED",
        error=generation.get("error"),
        generated_code=generated_target,
        token_usage=token_usage,
    )

    if not llm_passed:
        error_msg = generation.get("error", "LLM generation failed.")
        result = {
            "round": round_number,
            "method": method,
            "status": "GENERATION_ERROR",
            "error": error_msg,
            "target_code": target_source_code,
            "mutated_code": generated_target,
            "latency": {"llm_seconds": llm_latency},
            "token_usage": token_usage,
        }
        _write_json(round_dir / "result.json", result)
        return {
            "package": package_name,
            "method": method,
            "status": "GENERATION_ERROR",
            "round": round_number,
            "error": error_msg,
            "target_code": target_source_code,
            "mutated_code": generated_target,
            "token_usage": token_usage,
        }

    # ----------------------------------------------------
    # Gate 1: Target Scope Gate
    # ----------------------------------------------------
    candidate_features = mutation_plan.get("candidate_features", {})
    scope_result = _validate_generated_target_scope(
        generated_target, mutation_plan.get("target_type"), candidate_features
    )
    _write_json(round_dir / "target_scope.json", scope_result)
    _emit_progress(
        progress_callback,
        phase="VALIDATION",
        message=f"Round {round_number}: target scope {'passed' if scope_result.get('accepted') else 'rejected'}",
        round_number=round_number,
        gate="target_scope",
        gate_status="PASSED" if scope_result.get("accepted") else "REJECTED",
        error=None if scope_result.get("accepted") else str(scope_result.get("reason", "")),
    )
    if not scope_result.get("accepted", False):
        result = {
            "round": round_number,
            "method": method,
            "status": "GENERATION_SCOPE_REJECTED",
            "error": scope_result.get("reason"),
            "target_code": target_source_code,
            "mutated_code": generated_target,
            "generation_scope_pass": False,
            "token_usage": token_usage,
        }
        _write_json(round_dir / "result.json", result)
        return {"package": package_name, **result}

    # ----------------------------------------------------
    # Gate 2: Source Reconstruction Gate
    # ----------------------------------------------------
    try:
        generated_source = _reconstruct_source(
            source_prefix, generated_target, source_suffix, target_indentation
        )
    except Exception as exc:
        _emit_progress(
            progress_callback,
            phase="VALIDATION",
            message=f"Round {round_number}: source reconstruction failed: {exc}",
            round_number=round_number,
            gate="reconstruct",
            gate_status="REJECTED",
            error=str(exc),
        )
        result = {
            "round": round_number,
            "method": method,
            "status": "RECONSTRUCTION_ERROR",
            "error": str(exc),
            "target_code": target_source_code,
            "mutated_code": generated_target,
            "generation_scope_pass": True,
            "source_reconstruction": False,
            "token_usage": token_usage,
        }
        _write_json(round_dir / "result.json", result)
        return {"package": package_name, **result}

    (round_dir / "generated_source.py").write_text(generated_source, encoding="utf-8")
    _emit_progress(
        progress_callback,
        phase="VALIDATION",
        message=f"Round {round_number}: source reconstruction passed",
        round_number=round_number,
        gate="reconstruct",
        gate_status="PASSED",
    )

    # ----------------------------------------------------
    # Gate 3: Full Syntax Validation Gate
    # ----------------------------------------------------
    syntax_result = _validate_full_source_syntax(generated_source)
    _write_json(round_dir / "generated_source_syntax.json", syntax_result)
    _emit_progress(
        progress_callback,
        phase="VALIDATION",
        message=f"Round {round_number}: syntax {'passed' if syntax_result.get('accepted') else 'rejected'}",
        round_number=round_number,
        gate="syntax",
        gate_status="PASSED" if syntax_result.get("accepted") else "REJECTED",
        error=None if syntax_result.get("accepted") else str(syntax_result.get("reason", "")),
    )
    if not syntax_result.get("accepted", False):
        result = {
            "round": round_number,
            "method": method,
            "status": "SYNTAX_REJECTED",
            "error": syntax_result.get("reason"),
            "target_code": target_source_code,
            "mutated_code": generated_target,
            "generation_scope_pass": True,
            "source_reconstruction": True,
            "syntax_pass": False,
            "token_usage": token_usage,
        }
        _write_json(round_dir / "result.json", result)
        return {"package": package_name, **result}

    # ----------------------------------------------------
    # Gate 4: Source-Change Guard Gate
    # ----------------------------------------------------
    guard_result = source_change_guard(original_source=source_code, generated_source=generated_source)
    _write_json(round_dir / "source_guard.json", guard_result)
    _emit_progress(
        progress_callback,
        phase="VALIDATION",
        message=f"Round {round_number}: source guard {'passed' if guard_result.get('accepted') else 'rejected'}",
        round_number=round_number,
        gate="source_guard",
        gate_status="PASSED" if guard_result.get("accepted") else "REJECTED",
        error=None if guard_result.get("accepted") else str(guard_result.get("reason", "")),
    )
    if not guard_result.get("accepted", False):
        result = {
            "round": round_number,
            "method": method,
            "status": "SOURCE_GUARD_REJECTED",
            "error": guard_result.get("reason"),
            "target_code": target_source_code,
            "mutated_code": generated_target,
            "generation_scope_pass": True,
            "source_reconstruction": True,
            "syntax_pass": True,
            "source_guard_pass": False,
            "token_usage": token_usage,
        }
        _write_json(round_dir / "result.json", result)
        return {"package": package_name, **result}

    # ----------------------------------------------------
    # Gate 5: Code Diversity Gate
    # ----------------------------------------------------
    diversity_result = analyze_diversity(source_code, generated_source)
    _write_json(round_dir / "diversity.json", diversity_result.to_dict())
    _emit_progress(
        progress_callback,
        phase="VALIDATION",
        message=f"Round {round_number}: diversity gate {'passed' if diversity_result.accepted else 'rejected'}",
        round_number=round_number,
        gate="diversity",
        gate_status="PASSED" if diversity_result.accepted else "REJECTED",
        error=None if diversity_result.accepted else str(diversity_result.reason),
    )
    if not diversity_result.accepted:
        result = {
            "round": round_number,
            "method": method,
            "status": "DIVERSITY_REJECTED",
            "error": diversity_result.reason,
            "target_code": target_source_code,
            "mutated_code": generated_target,
            "generation_scope_pass": True,
            "source_reconstruction": True,
            "syntax_pass": True,
            "source_guard_pass": True,
            "diversity_pass": False,
            "token_usage": token_usage,
        }
        _write_json(round_dir / "result.json", result)
        return {"package": package_name, **result}

    # ----------------------------------------------------
    # Gate 6: Containerized Installation Validation Gate
    # ----------------------------------------------------
    round_package = round_dir / "package"
    copy_package(current_package, round_package)
    round_target = round_package / relative_source
    round_target.parent.mkdir(parents=True, exist_ok=True)
    round_target.write_text(generated_source, encoding="utf-8")

    if source_code == generated_source:
        result = {
            "round": round_number,
            "method": method,
            "status": "GENERATION_NO_CHANGE",
            "target_code": target_source_code,
            "mutated_code": generated_target,
            "token_usage": token_usage,
        }
        _write_json(round_dir / "result.json", result)
        return {"package": package_name, **result}

    archive = _create_round_archive(round_package, round_dir, round_number)
    if not archive.is_file() or archive.stat().st_size == 0:
        return _pipeline_error(
            package_output, package_name, method, round_number, round_dir,
            "Artifact archive was not created correctly.",
        )

    t_val_start = time.time()
    installation_result = validate_behavior(
        original_package=current_package, generated_package=round_package
    )
    val_latency = time.time() - t_val_start
    _write_json(round_dir / "installation_validation.json", installation_result)

    install_preserved = bool(installation_result.get("preserved", False))
    _emit_progress(
        progress_callback,
        phase="VALIDATION",
        message=f"Round {round_number}: docker install {'passed' if install_preserved else 'failed'}",
        round_number=round_number,
        gate="installation",
        gate_status="PASSED" if install_preserved else "REJECTED",
        error=None if install_preserved else str(installation_result.get("reason", "")),
    )

    if not install_preserved:
        validation_status = installation_result.get("status", "VALIDATION_INCONCLUSIVE")
        reason = (
            installation_result.get("reason")
            or installation_result.get("error")
            or "Validation did not establish installation success."
        )
        result = {
            "round": round_number,
            "method": method,
            "status": validation_status,
            "validation_status": validation_status,
            "failure_stage": installation_result.get("failure_stage"),
            "error": reason,
            "reason": reason,
            "target_code": target_source_code,
            "mutated_code": generated_target,
            "generation_scope_pass": True,
            "source_reconstruction": True,
            "syntax_pass": True,
            "source_guard_pass": True,
            "diversity_pass": True,
            "installation_pass": False,
            "artifact_available": True,
            "token_usage": token_usage,
        }
        _write_json(round_dir / "result.json", result)
        return {"package": package_name, **result}

    # Advance current working package with validated mutation for cumulative rounds
    copy_package(round_package, current_package)

    # 12. Automated DySec.io Evaluation & Artifact Recording
    total_round_latency = time.time() - round_start_time
    _emit_progress(
        progress_callback,
        phase="DYSEC_EVALUATION",
        message=f"Round {round_number}: submitting archive to DySec.io...",
        round_number=round_number,
    )

    dysec_eval = evaluate_with_dysec(archive)
    dysec_verdict = dysec_eval.get("verdict")
    round_status = dysec_eval.get("status", "AWAITING_DYSEC")

    if dysec_verdict:
        _write_json(round_dir / "dysec.json", dysec_eval)

    artifact = {
        "round": round_number,
        "method": method,
        "status": round_status,
        "archive": str(archive),
        "target_source": source_path,
        "start_line": start_line,
        "end_line": end_line,
        "latency": {
            "total_round_seconds": total_round_latency,
            "llm_seconds": llm_latency,
            "validation_seconds": val_latency,
        },
        "token_usage": token_usage,
    }
    _write_json(round_dir / "artifact.json", artifact)

    round_history = {
        "round": round_number,
        "method": method,
        "target_source": source_path,
        "target": mutation_plan.get("target"),
        "target_type": mutation_plan.get("target_type"),
        "start_line": start_line,
        "end_line": end_line,
        "transformation": mutation_plan.get("transformation"),
        "target_code": target_source_code,
        "mutated_code": generated_target,
        "generation_success": True,
        "generation_scope_pass": True,
        "source_reconstruction": True,
        "syntax_pass": True,
        "source_guard_pass": True,
        "diversity_pass": True,
        "installation_pass": True,
        "artifact_available": True,
        "dysec": dysec_eval.get("raw"),
        "dysec_verdict": dysec_verdict,
        "status": round_status,
        "artifact": str(archive),
        "latency_seconds": total_round_latency,
        "llm_latency_seconds": llm_latency,
        "token_usage": token_usage,
    }
    history.append(round_history)

    _write_json(round_dir / "result.json", round_history)
    _save_summary(package_output, package_name, method, history, round_status)

    return {
        "package": package_name,
        "method": method,
        "status": round_status,
        "round": round_number,
        "artifact": str(archive),
        "target_code": target_source_code,
        "mutated_code": generated_target,
        "token_usage": token_usage,
        "history": history,
    }


# ============================================================
# Multi-Round Experiment Orchestrator
# ============================================================


def _record_failed_round(
    package_output: Path,
    package_name: str,
    method: str,
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    """Record failed rounds while preserving code snippets and gate states."""
    history = _load_history(package_output)
    round_number = result.get("round")

    if not isinstance(round_number, int):
        return history

    if any(entry.get("round") == round_number for entry in history):
        return history

    status = str(result.get("status", "REJECTED")).upper()
    entry: dict[str, Any] = {
        "round": round_number,
        "method": method,
        "status": status,
        "error": result.get("error", "Unknown gate failure"),
        "attempt_failed": True,
    }

    for key in (
        "validation_status",
        "failure_stage",
        "reason",
        "validation_method",
        "target_code",
        "mutated_code",
        "generation_scope_pass",
        "source_reconstruction",
        "syntax_pass",
        "source_guard_pass",
        "diversity_pass",
        "installation_pass",
        "artifact_available",
        "token_usage",
    ):
        if key in result:
            entry[key] = result[key]

    history.append(entry)
    _save_summary(package_output, package_name, method, history, "CONTINUE")
    return history


def _run_package_once(
    archive_path: Path,
    method: str = "proposed",
    resume: bool = False,
    allow_pending: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Execute iterative search rounds for a package across the experiment budget."""
    if method not in SUPPORTED_METHODS:
        raise ValueError(f"Unsupported method '{method}'.")

    archive_path = Path(archive_path).resolve()
    package_name = archive_path.name
    if package_name.endswith(".tar.gz"):
        package_name = package_name[:-7]
    elif package_name.endswith(".tgz"):
        package_name = package_name[:-4]

    package_output = OUTPUT_DIR / method / package_name
    package_output.parent.mkdir(parents=True, exist_ok=True)

    if not resume and package_output.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_output = package_output.with_name(f"{package_name}_previous_{timestamp}")
        shutil.move(str(package_output), str(backup_output))
        print(f"Archived previous run: {backup_output}")

    package_output.mkdir(parents=True, exist_ok=True)
    history = _load_history(package_output)

    if resume:
        status, history = _apply_dysec_feedback(package_output, history, method)
        if status in {"SUCCESS", "AWAITING_DYSEC", "INVALID_DYSEC_FEEDBACK"}:
            return {
                "package": package_name,
                "method": method,
                "status": status,
                "rounds": len(history),
                "history": history,
            }
    else:
        try:
            _initialise_package(archive_path, package_output, resume=False)
        except WindowsOnlyPackageError as exc:
            history = [
                {
                    "round": None,
                    "status": "REJECTED_WINDOWS_ONLY",
                    "failure_stage": "package_initialisation",
                    "reason": exc.reason,
                    "evidence": exc.evidence,
                }
            ]
            _save_summary(
                package_output,
                package_name,
                method,
                history,
                "REJECTED_WINDOWS_ONLY",
            )
            return {
                "package": package_name,
                "method": method,
                "status": "REJECTED_WINDOWS_ONLY",
                "rounds": 0,
                "history": history,
                "reason": exc.reason,
            }

    results: list[dict[str, Any]] = []

    for round_index in range(1, EXPERIMENT_ROUNDS + 1):
        history = _load_history(package_output)
        completed_rounds = {e.get("round") for e in history if isinstance(e.get("round"), int)}

        if len(completed_rounds) >= EXPERIMENT_ROUNDS:
            break

        latest_pending = _find_latest_pending_round(package_output)
        if latest_pending is not None and not resume:
            print(f"[{package_name}] Round {latest_pending[0]} is AWAITING_DYSEC.")
            break

        print(f"[{package_name}] Starting Round {round_index:02d}/{EXPERIMENT_ROUNDS:02d}...")
        result = _run_single_round(
            archive_path=archive_path,
            method=method,
            resume=False,
            allow_pending=allow_pending,
            progress_callback=progress_callback,
        )
        results.append(result)
        status = result.get("status", "UNKNOWN")

        _emit_progress(
            progress_callback,
            phase="ROUND_COMPLETED",
            message=f"Round {round_index}/{EXPERIMENT_ROUNDS} finished with status: {status}",
            round_number=result.get("round", round_index),
            status=status,
            error=str(result["error"]) if result.get("error") else None,
        )

        # Only record as a failed gate attempt if it did not pass all internal gates
        # Trong vòng lặp for round_index in range(...) của _run_package_once:
        if status not in {"AWAITING_DYSEC", "SUCCESS", "DETECTED"}:
            history = _record_failed_round(package_output, package_name, method, result)
        else:
            history = _load_history(package_output)

        _emit_progress(
            progress_callback,
            phase="ROUND_COMPLETED",
            message=f"Round {round_index}/{EXPERIMENT_ROUNDS} finished with status: {status}",
            round_number=result.get("round", round_index),
            status=status,
            history=history, 
            error=str(result["error"]) if result.get("error") else None,
        )

        print(f"[{package_name}] round {round_index:02d}/{EXPERIMENT_ROUNDS}: {status}")

        # Stop loop if evasion succeeded or waiting for manual DySec upload
        if status in {"AWAITING_DYSEC", "SUCCESS"}:
            break

    history = _load_history(package_output)
    if any(e.get("status") == "SUCCESS" for e in history):
        final_status = "SUCCESS"
    elif any(e.get("status") == "AWAITING_DYSEC" for e in history):
        final_status = "AWAITING_DYSEC"
    elif len(history) >= EXPERIMENT_ROUNDS:
        final_status = "MAX_ROUNDS_REACHED"
    else:
        final_status = "CONTINUE"

    _save_summary(package_output, package_name, method, history, final_status)

    return {
        "package": package_name,
        "method": method,
        "status": final_status,
        "rounds": len(history),
        "history": history,
        "results": results,
    }


def run_package(
    archive_path: Path,
    method: str = "proposed",
    resume: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Execute the multi-round mutation pipeline and report live progress."""
    return _run_package_once(
        archive_path=archive_path,
        method=method,
        resume=resume,
        allow_pending=True,
        progress_callback=progress_callback,
    )