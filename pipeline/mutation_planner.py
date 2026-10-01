from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


TRANSFORMATIONS = (
    "internal_function_refactoring",
    "control_flow_refactoring",
    "expression_refactoring",
)


def _parse_python(
    source_code: str,
) -> ast.AST:
    return ast.parse(source_code)


def _function_features(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, Any]:

    branches = sum(
        isinstance(
            item,
            (
                ast.If,
                ast.IfExp,
                ast.Match,
            ),
        )
        for item in ast.walk(node)
    )

    loops = sum(
        isinstance(
            item,
            (
                ast.For,
                ast.AsyncFor,
                ast.While,
            ),
        )
        for item in ast.walk(node)
    )

    calls = sum(
        isinstance(item, ast.Call)
        for item in ast.walk(node)
    )

    statements = sum(
        isinstance(item, ast.stmt)
        for item in ast.walk(node)
    )

    return {
        "name": node.name,
        "start_line": node.lineno,
        "end_line": node.end_lineno or node.lineno,
        "lines": (
            (node.end_lineno or node.lineno)
            - node.lineno
            + 1
        ),
        "branches": branches,
        "loops": loops,
        "calls": calls,
        "statements": statements,
        "is_async": isinstance(
            node,
            ast.AsyncFunctionDef,
        ),
    }


def _extract_functions(
    tree: ast.AST,
) -> list[dict[str, Any]]:

    functions: list[dict[str, Any]] = []

    for node in ast.walk(tree):

        if not isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        ):
            continue

        if node.name.startswith("__"):
            continue

        functions.append(
            _function_features(node)
        )

    return functions


def _extract_classes(
    tree: ast.AST,
) -> list[dict[str, Any]]:

    classes: list[dict[str, Any]] = []

    for node in ast.walk(tree):

        if isinstance(node, ast.ClassDef):
            classes.append(
                {
                    "name": node.name,
                    "start_line": node.lineno,
                    "end_line": (
                        node.end_lineno
                        or node.lineno
                    ),
                }
            )

    return classes


def _extract_imports(
    tree: ast.AST,
) -> list[str]:

    imports: list[str] = []

    for node in ast.walk(tree):

        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""

            imports.append(module)

    return sorted(set(imports))


def _extract_entry_points(
    tree: ast.AST,
) -> list[str]:

    entry_points: list[str] = []

    for node in tree.body:

        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        ) and node.name == "main":
            entry_points.append("main")

        if isinstance(node, ast.If):

            test = node.test

            if isinstance(
                test,
                ast.Compare,
            ):
                entry_points.append(
                    "__main__ guard"
                )

    return entry_points


def analyze_source(
    source_code: str,
    source_path: str | None = None,
) -> dict[str, Any]:

    tree = _parse_python(source_code)

    return {
        "source_path": source_path,
        "line_count": len(
            source_code.splitlines()
        ),
        "top_level_statements": len(
            tree.body
        ),
        "functions": _extract_functions(
            tree
        ),
        "classes": _extract_classes(
            tree
        ),
        "imports": _extract_imports(
            tree
        ),
        "entry_points": _extract_entry_points(
            tree
        ),
    }


def _candidate_score(
    function: dict[str, Any],
) -> int:

    score = 0

    if function["statements"] >= 4:
        score += 2

    if function["branches"] > 0:
        score += 2

    if function["loops"] > 0:
        score += 2

    if function["calls"] > 0:
        score += 1

    if function["lines"] >= 5:
        score += 1

    return score


def _build_candidates(
    analysis: dict[str, Any],
) -> list[dict[str, Any]]:

    candidates: list[dict[str, Any]] = []

    for function in analysis["functions"]:

        candidates.append(
            {
                "target_type": "function",
                "target": function["name"],
                "score": _candidate_score(
                    function
                ),
                "features": function,
            }
        )

    return candidates


def _history_key(
    target_source: str | None,
    target: str | None,
    transformation: str | None,
) -> tuple[str, str, str]:

    return (
        str(target_source or ""),
        str(target or ""),
        str(transformation or ""),
    )


def _attempted_keys(
    history: list[dict[str, Any]] | None,
) -> set[tuple[str, str, str]]:

    keys: set[
        tuple[str, str, str]
    ] = set()

    for entry in history or []:

        keys.add(
            _history_key(
                entry.get("target_source"),
                entry.get("target"),
                entry.get("transformation"),
            )
        )

    return keys


# def _feedback_rejected_keys(
#     history: list[dict[str, Any]] | None,
# ) -> set[tuple[str, str, str]]:

#     rejected: set[
#         tuple[str, str, str]
#     ] = set()

#     for entry in history or []:

#         dysec = entry.get("dysec") or {}

#         verdict = str(
#             dysec.get("verdict", "")
#         ).upper()

#         if verdict != "DETECTED":
#             continue

#         rejected.add(
#             _history_key(
#                 entry.get("target_source"),
#                 entry.get("target"),
#                 entry.get("transformation"),
#             )
#         )

#     return rejected


def _choose_transformation(
    round_number: int,
    used_keys: set[tuple[str, str, str]],
    target_source: str,
    target: str,
) -> str:

    start = (
        round_number - 1
    ) % len(TRANSFORMATIONS)

    for offset in range(
        len(TRANSFORMATIONS)
    ):

        transformation = TRANSFORMATIONS[
            (start + offset)
            % len(TRANSFORMATIONS)
        ]

        key = _history_key(
            target_source,
            target,
            transformation,
        )

        if key not in used_keys:
            return transformation

    return TRANSFORMATIONS[start]


def _rank_candidates(
    candidates: list[dict[str, Any]],
    history: list[dict[str, Any]] | None,
    target_source: str,
) -> list[dict[str, Any]]:

    attempted = _attempted_keys(
        history
    )

    ranked: list[
        tuple[
            tuple[int, int, str],
            dict[str, Any],
        ]
    ] = []

    for candidate in candidates:

        target = candidate["target"]

        possible = []

        for transformation in TRANSFORMATIONS:

            key = _history_key(
                target_source,
                target,
                transformation,
            )

            if key not in attempted:
                possible.append(
                    transformation
                )

        if not possible:
            continue

        score = int(
            candidate["score"]
        )

        ranked.append(
            (
                (
                    -score,
                    -len(possible),
                    target,
                ),
                candidate,
            )
        )

    ranked.sort(
        key=lambda item: item[0]
    )

    return [
        candidate
        for _, candidate in ranked
    ]


def build_mutation_plan(
    source_code: str,
    round_number: int,
    source_path: str | None = None,
    history: list[dict[str, Any]] | None = None,
    feedback_mode: bool = False,
) -> dict[str, Any]:

    analysis = analyze_source(
        source_code,
        source_path,
    )

    candidates = _build_candidates(
        analysis
    )

    if not candidates:
        raise ValueError(
            "No transformable functions "
            "were found in source file."
        )

    ranked = _rank_candidates(
        candidates,
        history,
        source_path or "",
    )

    # If every target/transformation combination
    # has been attempted, allow a fresh cycle.
    if not ranked:
        ranked = sorted(
            candidates,
            key=lambda candidate: (
                -candidate["score"],
                candidate["target"],
            ),
        )

    selected = ranked[0]

    target = selected["target"]

    attempted = _attempted_keys(
        history
    )

    transformation = _choose_transformation(
        round_number,
        attempted,
        source_path or "",
        target,
    )

    # if feedback_mode:

    #     rejected = _feedback_rejected_keys(
    #         history
    #     )

    #     rejected_same_target = {
    #         key
    #         for key in rejected
    #         if key[0] == (source_path or "")
    #         and key[1] == target
    #     }

    #     for candidate_transformation in (
    #         TRANSFORMATIONS
    #     ):

    #         key = _history_key(
    #             source_path,
    #             target,
    #             candidate_transformation,
    #         )

    #         if (
    #             key not in attempted
    #             and key not in rejected_same_target
    #         ):
    #             transformation = (
    #                 candidate_transformation
    #             )
    #             break

    target_features = selected[
        "features"
    ]

    return {
        "round": round_number,
        "target_type": selected[
            "target_type"
        ],
        "target": target,
        "target_functions": [
            target
        ],
        "target_source": source_path,
        "start_line": target_features[
            "start_line"
        ],
        "end_line": target_features[
            "end_line"
        ],
        "transformation": transformation,
        "candidate_score": selected[
            "score"
        ],
        "candidate_features": target_features,
        "package_features": analysis,
        "feedback_mode": feedback_mode,
        "reason": (
            "Selected using heuristic "
            "package-aware function scoring."
        ),
    }