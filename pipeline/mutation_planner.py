from __future__ import annotations

import ast
from pathlib import Path


COMPLEXITY_LEVELS = {
    1: {
        "name": "minimal",
        "max_operators": 1,
        "instruction": (
            "Make one small but meaningful internal refactoring."
        ),
    },
    2: {
        "name": "low",
        "max_operators": 1,
        "instruction": (
            "Make one localized structural refactoring "
            "inside the selected function."
        ),
    },
    3: {
        "name": "moderate",
        "max_operators": 2,
        "instruction": (
            "Apply at most two compatible internal refactoring "
            "operations."
        ),
    },
    4: {
        "name": "high",
        "max_operators": 2,
        "instruction": (
            "Apply two coordinated refactorings while "
            "keeping the change localized."
        ),
    },
    5: {
        "name": "advanced",
        "max_operators": 2,
        "instruction": (
            "Apply two coordinated structural changes "
            "across closely related internal functions."
        ),
    },
}


def get_complexity_level(round_number: int) -> int:
    if round_number <= 3:
        return 1
    if round_number <= 6:
        return 2
    if round_number <= 9:
        return 3
    if round_number <= 12:
        return 4
    return 5


def _function_nodes(source_code: str) -> list[ast.AST]:
    tree = ast.parse(source_code)

    return [
        node
        for node in ast.walk(tree)
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        )
    ]


def select_target_function(
    source_code: str,
) -> str | None:
    candidates = []

    for node in _function_nodes(source_code):
        name = getattr(node, "name", "")

        if not name or name.startswith("__"):
            continue

        end_lineno = getattr(
            node,
            "end_lineno",
            node.lineno,
        )

        size = end_lineno - node.lineno + 1

        candidates.append((size, name))

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (-item[0], item[1])
    )

    return candidates[0][1]


def _module_level_summary(
    source_code: str,
) -> dict:
    tree = ast.parse(source_code)

    statements = []

    for node in tree.body:
        statements.append(
            {
                "node_type": type(node).__name__,
                "start_line": getattr(node, "lineno", None),
                "end_line": getattr(
                    node,
                    "end_lineno",
                    getattr(node, "lineno", None),
                ),
            }
        )

    return {
        "target_type": "module",
        "statement_count": len(statements),
        "statements": statements,
    }


def _is_setup_py(
    source_path: Path | None,
) -> bool:
    return (
        source_path is not None
        and source_path.name == "setup.py"
    )


def build_mutation_plan(
    source_code: str,
    round_number: int,
    source_path: Path | None = None,
) -> dict:
    level = get_complexity_level(round_number)

    target = select_target_function(source_code)

    if target is not None:
        return {
            "level": level,
            "operations": [],
            "target_type": "function",
            "target_functions": [target],
            "target_source": (
                str(source_path)
                if source_path is not None
                else None
            ),
            "reason": (
                "Function target identified for "
                "controlled source analysis."
            ),
        }

    if _is_setup_py(source_path):
        return {
            "level": level,
            "operations": [],
            "target_type": "module",
            "target_functions": [],
            "target_source": str(source_path),
            "module_summary": _module_level_summary(
                source_code
            ),
            "reason": (
                "setup.py contains no suitable function "
                "target; module-level source identified "
                "for controlled analysis."
            ),
        }

    return {
        "level": level,
        "operations": [],
        "target_type": None,
        "target_functions": [],
        "target_source": (
            str(source_path)
            if source_path is not None
            else None
        ),
        "reason": "No transformable function found.",
    }