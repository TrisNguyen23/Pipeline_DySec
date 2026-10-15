from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# ============================================================
# Load Nemasha's transformations.json
# ============================================================

def _load_transformation_catalog() -> dict[str, dict[str, Any]]:
    """Load transformation definitions from transformations.json."""
    search_paths = (
        Path(__file__).resolve().parent / "transformations.json",
        Path(__file__).resolve().parent.parent / "transformations.json",
    )
    catalog: dict[str, dict[str, Any]] = {}

    for path in search_paths:
        if not path.is_file():
            continue
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and item.get("id"):
                        catalog[str(item["id"])] = item
                break
        except (OSError, json.JSONDecodeError):
            continue

    return catalog


TRANSFORMATION_CATALOG = _load_transformation_catalog()

# Fallback and Python-specific tactical guidance mapped to Nemasha's IDs
TRANSFORMATION_INSTRUCTIONS: dict[str, str] = {
    "instruction_substitution": (
        "Transform the target code by substituting standard system APIs "
        "(e.g., file I/O, process management, network communication) with "
        "custom wrappers, indirect dispatch (getattr/builtins), or alternative "
        "standard-library equivalents to mask behavioral and call signatures "
        "while preserving exact runtime functionality."
    ),
    "dead_code_insertion": (
        "Analyze the control flow and insert realistic dead-code segments and "
        "benign computations that do not alter the runtime outcome. Increase "
        "cyclomatic complexity with unreachable branches or no-op helper logic."
    ),
    "control_flow_flattening": (
        "Transform the control flow structure by flattening nested loops and "
        "conditional statements into a state-based dispatcher (e.g., a loop "
        "over a state variable or dictionary-based dispatch table) while "
        "preserving exact execution order and side effects."
    ),
    "polymorphic_encryption": (
        "Obfuscate sensitive string literals, paths, commands, and constants "
        "using inline encoding/decoding routines (e.g., XOR, byte-array "
        "reconstruction, or base64/zlib layers) resolved dynamically at runtime."
    ),
    "opaque_predicates": (
        "Introduce opaque predicates—conditions that appear dynamic (e.g., "
        "mathematical identities or object property checks) but deterministically "
        "evaluate to a known boolean state—to obscure the true execution path."
    ),
    "api_interception": (
        "Wrap critical OS, subprocess, socket, or file interactions inside "
        "indirection helpers or context managers that mediate the calls without "
        "changing the observable behavior."
    ),
    "runtime_protection": (
        "Add lightweight runtime state validation and environment checks around "
        "the core logic while keeping execution completely non-interactive and "
        "preserving the original behavior."
    ),
    "optimize": (
        "Restructure algorithmic flow, buffer handling, and I/O operations "
        "using alternative Python idioms (comprehensions, generators, memoryviews) "
        "without changing external behavior."
    ),
    "harden": (
        "Wrap operations with defensive validation, exception handling, and "
        "sanitized path/process wrappers while preserving the exact intended behavior."
    ),
    "refactor": (
        "Refactor internal variable names, helper structures, and expressions "
        "for structural diversity while preserving public interfaces and behavior."
    ),
    # Legacy aliases for backward compatibility
    "internal_function_refactoring": (
        "Substitute direct API calls with indirect wrappers and refactor internal "
        "structure while preserving the public signature and behavior."
    ),
    "control_flow_refactoring": (
        "Restructure control flow using state variables, guard clauses, or "
        "opaque predicates while preserving exact semantics."
    ),
    "expression_refactoring": (
        "Obfuscate constants and refactor expressions using dynamic evaluation "
        "and indirect attribute lookups while preserving values and side effects."
    ),
}

DEFAULT_TRANSFORMATION_INSTRUCTION = (
    "Apply a structural, behavior-preserving transformation (API indirection, "
    "control-flow restructuring, or constant obfuscation) within the target scope."
)


def _resolve_transformation_instruction(transformation_id: str) -> str:
    """Combine Nemasha's JSON instruction with Python-specific tactical guidance."""
    entry = TRANSFORMATION_CATALOG.get(transformation_id)
    tactical = TRANSFORMATION_INSTRUCTIONS.get(
        transformation_id, DEFAULT_TRANSFORMATION_INSTRUCTION
    )
    if entry and entry.get("instruction"):
        label = entry.get("label", transformation_id)
        desc = entry.get("description", "")
        json_inst = entry["instruction"]
        return (
            f"Strategy: {label} ({transformation_id})\n"
            f"Objective: {desc}\n"
            f"Core Directive: {json_inst}\n"
            f"Python Tactical Guidance: {tactical}"
        )
    return tactical


# ============================================================
# Formatting helpers
# ============================================================

def _json_text(value: Any) -> str:
    """Serialize structured data deterministically."""
    try:
        return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return "{}"


def _code_fence(source: str) -> str:
    """Return a Markdown fence longer than any backtick run in source."""
    longest_run = 0
    current_run = 0
    for char in source:
        if char == "`":
            current_run += 1
            longest_run = max(longest_run, current_run)
        else:
            current_run = 0
    return "`" * max(3, longest_run + 1)


def _format_history(history: list[dict[str, Any]] | None) -> str:
    """Summarize previous attempts and their outcomes."""
    if not history:
        return "No previous mutation attempts are recorded."

    entries: list[dict[str, Any]] = []
    for item in history[-6:]:
        if not isinstance(item, dict):
            continue
        entries.append({
            "round": item.get("round"),
            "target": item.get("target"),
            "transformation": item.get("transformation"),
            "status": item.get("status"),
            "dysec_verdict": item.get("dysec_verdict"),
            "error": item.get("error"),
        })
    return _json_text(entries)


def _format_dysec_feedback(dysec_feedback: dict[str, Any] | None) -> str:
    """Format DySec detector feedback to guide adaptive mutation."""
    if not dysec_feedback:
        return "No prior detector feedback for this package."

    verdict = dysec_feedback.get("verdict", "DETECTED")
    score = dysec_feedback.get("score")
    features = dysec_feedback.get("features") or {}

    guidance = (
        "The previous variant was still DETECTED by the dynamic behavior monitor. "
        "You MUST alter the structural and runtime footprint of the target by: "
        "(1) replacing direct high-profile API calls with indirect lookups or "
        "alternative stdlib mechanisms, (2) splitting or batching I/O and process "
        "operations, and (3) encoding string literals and command arguments."
    )
    return _json_text({
        "previous_verdict": verdict,
        "detection_score": score,
        "observed_features": features,
        "adaptive_guidance": guidance,
    })


def _extract_target_region(
    source_code: str,
    mutation_plan: dict[str, Any],
    context_lines: int = 8,
) -> str:
    """Extract the planned target and nearby context for the prompt."""
    start = mutation_plan.get("start_line")
    end = mutation_plan.get("end_line")
    if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
        return "Target region unavailable."

    lines = source_code.splitlines()
    if end > len(lines):
        return "Target region exceeds source length."

    left = max(1, start - context_lines)
    right = min(len(lines), end + context_lines)
    return "\n".join(
        f"{line_no:5d} | {lines[line_no - 1]}"
        for line_no in range(left, right + 1)
    )


# ============================================================
# Main prompt builder
# ============================================================

def build_prompt(
    source_code: str,
    mutation_plan: dict[str, Any],
    round_number: int,
    target_source: str,
    history: list[dict[str, Any]] | None = None,
    package_features: dict[str, Any] | None = None,
    dysec_feedback: dict[str, Any] | None = None,
) -> str:
    """Build a strategy-driven prompt using Nemasha's transformation catalog."""
    target_type = str(mutation_plan.get("target_type", "function"))
    target = str(mutation_plan.get("target", "unknown"))
    start_line = mutation_plan.get("start_line", "unknown")
    end_line = mutation_plan.get("end_line", "unknown")
    transformation = str(mutation_plan.get("transformation", "instruction_substitution"))

    strategy_block = _resolve_transformation_instruction(transformation)
    history_text = _format_history(history)
    dysec_text = _format_dysec_feedback(dysec_feedback)
    target_region = _extract_target_region(source_code, mutation_plan)

    fence = _code_fence(source_code)
    target_fence = _code_fence(target_region)

    return f"""
SYSTEM ROLE
You are an expert Python systems programmer specializing in adversarial code
transformation, structural obfuscation, and behavior-preserving refactoring.
You follow exact structural constraints and output only valid Python code.

TASK INTRODUCTION
Below you are provided a Python source file and a specific target AST node
(`{target}` of type `{target_type}` at lines {start_line}-{end_line} in `{target_source}`).
Transform ONLY this target node into a structurally distinct variant using the
specified transformation strategy while preserving 100% of its functional semantics.

TRANSFORMATION STRATEGY (Round {round_number})
{strategy_block}

ADAPTIVE DETECTOR FEEDBACK
{dysec_text}

PREVIOUS ROUND HISTORY
{history_text}

PRESERVATION AND VALIDATION CONSTRAINTS
1. Signature & Scope: Preserve the exact function/class name (`{target}`), parameter
   signature, decorators, and return contract so callers in the rest of the package
   do not break.
2. Top-Level Node Rule: Your output MUST parse as a single top-level `{target_type}`
   AST node. Any helper functions, dispatch tables, or decoding lambdas MUST be
   nested inside `{target}` (not placed at module scope).
3. Dependency Rule: Use ONLY modules already imported in the file or built-in Python
   functions (`__import__`, `getattr`, `bytes`, `int.from_bytes`, etc.). Do NOT add
   external third-party library dependencies.
4. Diversity Requirement: Make substantive structural changes (e.g., state-machine
   dispatch, indirect API resolution, encoded literals, or opaque predicates) so the
   AST and token stream differ meaningfully from the original target.
5. Syntax & Install Safety: Ensure the transformed target is 100% syntactically valid
   Python 3 and does not hang or raise unhandled exceptions during package installation.

TARGET REGION WITH CONTEXT (Line numbers are for reference only — do not output them)
{target_fence}text
{target_region}
{target_fence}

FULL SOURCE FILE CONTEXT
{fence}python
{source_code}
{fence}

OUTPUT CONTRACT
Return ONLY the complete replacement code for `{target}` ({target_type}).
- Do NOT wrap the code in Markdown fences (no ```python).
- Do NOT include line numbers, comments explaining the evasion, or prose.
- Do NOT return the entire file—only the transformed `{target}` node.
""".strip()