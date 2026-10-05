from __future__ import annotations

import ast
from typing import Any


# ---------------------------------------------------------------------------
# Mutation configuration
# ---------------------------------------------------------------------------
#
# These are operational limits for reliable LLM-based mutation.
# They are NOT claimed as universal limits from the literature.
#

MAX_FUNCTION_LINES = 80
MAX_CLASS_LINES = 120
MAX_MODULE_BLOCK_LINES = 40


# Target-level transformation compatibility.
TRANSFORMATIONS = (
    "internal_function_refactoring",
    "control_flow_refactoring",
    "expression_refactoring",
)

TRANSFORMATIONS_BY_TARGET = {
    "function": (
        "internal_function_refactoring",
        "control_flow_refactoring",
        "expression_refactoring",
    ),
    "class": (
        "internal_function_refactoring",
        "control_flow_refactoring",
        "expression_refactoring",
    ),
}


# Module-level transformations are more restrictive because module blocks
# are executable top-level statements and are usually more fragile than
# function-level targets.
TRANSFORMATIONS_BY_MODULE_BLOCK = {
    # Control-flow structures.
    "if": (
        "control_flow_refactoring",
    ),
    "for": (
        "control_flow_refactoring",
    ),
    "while": (
        "control_flow_refactoring",
    ),
    "try": (
        "control_flow_refactoring",
    ),
    "with": (
        "control_flow_refactoring",
    ),
    "match": (
        "control_flow_refactoring",
    ),

    # Expression-like structures.
    "expression": (
        "expression_refactoring",
    ),
    "assignment": (
        "expression_refactoring",
    ),
    "annotated_assignment": (
        "expression_refactoring",
    ),
    "augmented_assignment": (
        "expression_refactoring",
    ),

    # These are deliberately conservative.
    #
    # A return/raise/assert/delete at module scope is unusual and should
    # not automatically receive an incompatible transformation.
    "return": (
        "expression_refactoring",
    ),
    "raise": (
        "expression_refactoring",
    ),
    "assert": (
        "expression_refactoring",
    ),
    "delete": (
        "expression_refactoring",
    ),
}


# Lower value = higher priority.
#
# Function-level mutation is preferred because it gives the LLM a
# self-contained semantic unit.
TARGET_PRIORITY = {
    "function": 0,
    "class": 1,
    "module_block": 2,
}


# ---------------------------------------------------------------------------
# AST parsing
# ---------------------------------------------------------------------------


def _parse_python(
    source_code: str,
) -> ast.AST:
    """
    Parse Python source code into an AST.

    SyntaxError is intentionally propagated so callers can distinguish
    invalid Python source from valid source with no mutation targets.
    """

    return ast.parse(source_code)


# ---------------------------------------------------------------------------
# Function analysis
# ---------------------------------------------------------------------------


def _function_features(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, Any]:
    """
    Extract structural features from a function or async function.
    """

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
        isinstance(
            item,
            ast.Call,
        )
        for item in ast.walk(node)
    )

    statements = sum(
        isinstance(
            item,
            ast.stmt,
        )
        for item in ast.walk(node)
    )

    end_line = (
        node.end_lineno
        or node.lineno
    )

    return {
        "name": node.name,
        "start_line": node.lineno,
        "end_line": end_line,
        "lines": (
            end_line
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
    """
    Extract all functions and async functions from the source tree.

    Nested functions are included because they are valid structural
    mutation targets.

    Dunder methods are excluded from the primary candidate pool.
    """

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


# ---------------------------------------------------------------------------
# Class analysis
# ---------------------------------------------------------------------------


def _class_features(
    node: ast.ClassDef,
) -> dict[str, Any]:
    """
    Extract structural features from a class definition.
    """

    methods = sum(
        isinstance(
            item,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
        for item in node.body
    )

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
        isinstance(
            item,
            ast.Call,
        )
        for item in ast.walk(node)
    )

    statements = sum(
        isinstance(
            item,
            ast.stmt,
        )
        for item in ast.walk(node)
    )

    end_line = (
        node.end_lineno
        or node.lineno
    )

    return {
        "name": node.name,
        "start_line": node.lineno,
        "end_line": end_line,
        "lines": (
            end_line
            - node.lineno
            + 1
        ),
        "methods": methods,
        "branches": branches,
        "loops": loops,
        "calls": calls,
        "statements": statements,
    }


def _extract_classes(
    tree: ast.AST,
) -> list[dict[str, Any]]:
    """
    Extract all class definitions from the source tree.

    Nested classes are included.
    """

    classes: list[dict[str, Any]] = []

    for node in ast.walk(tree):

        if not isinstance(
            node,
            ast.ClassDef,
        ):
            continue

        classes.append(
            _class_features(node)
        )

    return classes


# ---------------------------------------------------------------------------
# Module-level block analysis
# ---------------------------------------------------------------------------


def _module_block_features(
    node: ast.stmt,
    index: int,
) -> dict[str, Any]:
    """
    Extract structural features from a top-level executable statement.
    """

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
        isinstance(
            item,
            ast.Call,
        )
        for item in ast.walk(node)
    )

    statements = sum(
        isinstance(
            item,
            ast.stmt,
        )
        for item in ast.walk(node)
    )

    end_line = (
        node.end_lineno
        or node.lineno
    )

    if isinstance(node, ast.If):
        block_type = "if"

    elif isinstance(
        node,
        (
            ast.For,
            ast.AsyncFor,
        ),
    ):
        block_type = "for"

    elif isinstance(node, ast.While):
        block_type = "while"

    elif isinstance(node, ast.Try):
        block_type = "try"

    elif isinstance(
        node,
        (
            ast.With,
            ast.AsyncWith,
        ),
    ):
        block_type = "with"

    elif isinstance(node, ast.Match):
        block_type = "match"

    elif isinstance(node, ast.Assign):
        block_type = "assignment"

    elif isinstance(node, ast.AnnAssign):
        block_type = "annotated_assignment"

    elif isinstance(node, ast.AugAssign):
        block_type = "augmented_assignment"

    elif isinstance(node, ast.Expr):
        block_type = "expression"

    elif isinstance(node, ast.Return):
        block_type = "return"

    elif isinstance(node, ast.Raise):
        block_type = "raise"

    elif isinstance(node, ast.Assert):
        block_type = "assert"

    elif isinstance(node, ast.Delete):
        block_type = "delete"

    else:
        block_type = type(node).__name__.lower()

    return {
        "name": f"module_block_{index}",
        "block_type": block_type,
        "start_line": node.lineno,
        "end_line": end_line,
        "lines": (
            end_line
            - node.lineno
            + 1
        ),
        "branches": branches,
        "loops": loops,
        "calls": calls,
        "statements": statements,
    }


def _extract_module_blocks(
    tree: ast.AST,
) -> list[dict[str, Any]]:
    """
    Extract executable top-level statements.

    Imports, functions, and classes are excluded because they already
    have dedicated structural target representations.
    """

    blocks: list[dict[str, Any]] = []

    index = 0

    for node in tree.body:

        if isinstance(
            node,
            (
                ast.Import,
                ast.ImportFrom,
            ),
        ):
            continue

        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
            ),
        ):
            continue

        index += 1

        blocks.append(
            _module_block_features(
                node,
                index,
            )
        )

    return blocks


# ---------------------------------------------------------------------------
# Import and entry-point analysis
# ---------------------------------------------------------------------------


def _extract_imports(
    tree: ast.AST,
) -> list[str]:
    """
    Extract imported module names.
    """

    imports: list[str] = []

    for node in ast.walk(tree):

        if isinstance(node, ast.Import):

            for alias in node.names:
                imports.append(
                    alias.name
                )

        elif isinstance(
            node,
            ast.ImportFrom,
        ):

            module = node.module or ""

            imports.append(module)

    return sorted(
        set(imports)
    )


def _extract_entry_points(
    tree: ast.AST,
) -> list[str]:
    """
    Identify common module entry-point patterns.
    """

    entry_points: list[str] = []

    for node in tree.body:

        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        ) and node.name == "main":

            entry_points.append(
                "main"
            )

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


# ---------------------------------------------------------------------------
# Source-level analysis
# ---------------------------------------------------------------------------


def analyze_source(
    source_code: str,
    source_path: str | None = None,
) -> dict[str, Any]:
    """
    Analyze a Python source file and return its structural inventory.
    """

    tree = _parse_python(
        source_code
    )

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

        "module_blocks": _extract_module_blocks(
            tree
        ),

        "imports": _extract_imports(
            tree
        ),

        "entry_points": _extract_entry_points(
            tree
        ),
    }


# ---------------------------------------------------------------------------
# Candidate suitability
# ---------------------------------------------------------------------------


def _candidate_score(
    features: dict[str, Any],
) -> int:
    """
    Compute a structural suitability score.

    This score rewards meaningful structural content, but deliberately
    avoids treating very large targets as automatically better targets.
    """

    score = 0

    statements = int(
        features.get(
            "statements",
            0,
        )
    )

    branches = int(
        features.get(
            "branches",
            0,
        )
    )

    loops = int(
        features.get(
            "loops",
            0,
        )
    )

    calls = int(
        features.get(
            "calls",
            0,
        )
    )

    lines = int(
        features.get(
            "lines",
            0,
        )
    )

    # Structural richness.
    if statements >= 4:
        score += 2

    if branches > 0:
        score += 2

    if loops > 0:
        score += 2

    if calls > 0:
        score += 1

    if lines >= 5:
        score += 1

    # Moderate size is useful, but excessive size should not be rewarded.
    if lines <= 20:
        score += 1

    elif lines <= 40:
        score += 0

    elif lines <= 80:
        score -= 1

    else:
        score -= 3

    return score


def _is_mutation_suitable(
    candidate: dict[str, Any],
) -> bool:
    """
    Decide whether a candidate is operationally suitable for one-shot
    LLM mutation.

    These limits are engineering heuristics intended to reduce generation
    failures and scope violations.
    """

    target_type = str(
        candidate.get(
            "target_type",
            "",
        )
    )

    features = candidate.get(
        "features",
        {},
    )

    lines = int(
        features.get(
            "lines",
            0,
        )
    )

    if lines <= 0:
        return False

    if target_type == "function":
        return lines <= MAX_FUNCTION_LINES

    if target_type == "class":
        return lines <= MAX_CLASS_LINES

    if target_type == "module_block":
        return lines <= MAX_MODULE_BLOCK_LINES

    return False


# ---------------------------------------------------------------------------
# Candidate construction
# ---------------------------------------------------------------------------


def _make_candidate(
    target_type: str,
    target: str,
    features: dict[str, Any],
) -> dict[str, Any]:
    """
    Construct a normalized mutation candidate.
    """

    return {
        "target_type": target_type,
        "target": target,
        "score": _candidate_score(
            features
        ),
        "features": features,
    }


def _build_candidates(
    analysis: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Build mutation candidates from supported source structures.

    Priority:
        1. functions
        2. classes
        3. small module-level executable blocks

    Large module-level blocks are intentionally excluded.
    """

    candidates: list[
        dict[str, Any]
    ] = []

    # --------------------------------------------------
    # Function candidates
    # --------------------------------------------------

    for function in analysis.get(
        "functions",
        [],
    ):

        candidate = _make_candidate(
            target_type="function",
            target=str(
                function["name"]
            ),
            features=function,
        )

        if _is_mutation_suitable(
            candidate
        ):
            candidates.append(
                candidate
            )

    # --------------------------------------------------
    # Class candidates
    # --------------------------------------------------

    for cls in analysis.get(
        "classes",
        [],
    ):

        candidate = _make_candidate(
            target_type="class",
            target=str(
                cls["name"]
            ),
            features=cls,
        )

        if _is_mutation_suitable(
            candidate
        ):
            candidates.append(
                candidate
            )

    # --------------------------------------------------
    # Module-level candidates
    # --------------------------------------------------

    for block in analysis.get(
        "module_blocks",
        [],
    ):

        candidate = _make_candidate(
            target_type="module_block",
            target=str(
                block["name"]
            ),
            features=block,
        )

        if _is_mutation_suitable(
            candidate
        ):
            candidates.append(
                candidate
            )

    return candidates


# ---------------------------------------------------------------------------
# Transformation compatibility
# ---------------------------------------------------------------------------


def _transformations_for_candidate(
    candidate: dict[str, Any],
) -> tuple[str, ...]:
    """
    Return transformations semantically compatible with the candidate.
    """

    target_type = str(
        candidate.get(
            "target_type",
            "",
        )
    )

    if target_type != "module_block":
        return TRANSFORMATIONS_BY_TARGET.get(
            target_type,
            (),
        )

    features = candidate.get(
        "features",
        {},
    )

    block_type = str(
        features.get(
            "block_type",
            "",
        )
    )

    return TRANSFORMATIONS_BY_MODULE_BLOCK.get(
        block_type,
        (),
    )


# ---------------------------------------------------------------------------
# History handling
# ---------------------------------------------------------------------------


def _history_key(
    target_source: str | None,
    target: str | None,
    transformation: str | None,
) -> tuple[str, str, str]:
    """
    Build a stable key for a target/transformation combination.
    """

    return (
        str(
            target_source
            or ""
        ),
        str(
            target
            or ""
        ),
        str(
            transformation
            or ""
        ),
    )


def _attempted_keys(
    history: list[dict[str, Any]] | None,
) -> set[
    tuple[str, str, str]
]:
    """
    Collect target/transformation combinations already attempted.

    Invalid/unknown history entries are ignored because they cannot
    identify a concrete mutation target.
    """

    keys: set[
        tuple[str, str, str]
    ] = set()

    for entry in history or []:

        target_source = entry.get(
            "target_source"
        )

        target = entry.get(
            "target"
        )

        transformation = entry.get(
            "transformation"
        )

        # Do not turn incomplete "unknown" history into a real key.
        if not target:
            continue

        if not transformation:
            continue

        keys.add(
            _history_key(
                target_source,
                target,
                transformation,
            )
        )

    return keys


# ---------------------------------------------------------------------------
# Transformation selection
# ---------------------------------------------------------------------------


def _choose_transformation(
    round_number: int,
    used_keys: set[
        tuple[str, str, str]
    ],
    target_source: str,
    target: str,
    candidate: dict[str, Any],
) -> str:
    """
    Select a deterministic compatible transformation while avoiding
    combinations already attempted for the same source and target.
    """

    transformations = (
        _transformations_for_candidate(
            candidate
        )
    )

    if not transformations:
        raise ValueError(
            "No compatible transformation "
            f"for target {target!r}."
        )

    start = (
        round_number - 1
    ) % len(transformations)

    for offset in range(
        len(transformations)
    ):

        transformation = transformations[
            (
                start
                + offset
            )
            % len(transformations)
        ]

        key = _history_key(
            target_source,
            target,
            transformation,
        )

        if key not in used_keys:
            return transformation

    # Every compatible transformation for this target has already been
    # attempted. This is only a fallback for the planner's deterministic
    # cycle.
    return transformations[start]


# ---------------------------------------------------------------------------
# Candidate ranking
# ---------------------------------------------------------------------------


def _rank_candidates(
    candidates: list[dict[str, Any]],
    history: list[dict[str, Any]] | None,
    target_source: str,
) -> list[dict[str, Any]]:
    """
    Rank candidates using mutation suitability rather than raw complexity.

    Ranking priority:
        1. target type priority
        2. suitability score
        3. smaller target size
        4. number of remaining compatible transformations
        5. stable target name
    """

    attempted = _attempted_keys(
        history
    )

    ranked: list[
        tuple[
            tuple[
                int,
                int,
                int,
                int,
                str,
            ],
            dict[str, Any],
        ]
    ] = []

    for candidate in candidates:

        target = str(
            candidate["target"]
        )

        compatible_transformations = (
            _transformations_for_candidate(
                candidate
            )
        )

        possible = []

        for transformation in (
            compatible_transformations
        ):

            key = _history_key(
                target_source,
                target,
                transformation,
            )

            if key not in attempted:
                possible.append(
                    transformation
                )

        # Every compatible transformation was already attempted.
        if not possible:
            continue

        target_type = str(
            candidate.get(
                "target_type",
                "",
            )
        )

        features = candidate.get(
            "features",
            {},
        )

        lines = int(
            features.get(
                "lines",
                0,
            )
        )

        score = int(
            candidate.get(
                "score",
                0,
            )
        )

        priority = TARGET_PRIORITY.get(
            target_type,
            99,
        )

        ranking_key = (
            priority,
            -score,
            lines,
            -len(possible),
            target,
        )

        ranked.append(
            (
                ranking_key,
                candidate,
            )
        )

    ranked.sort(
        key=lambda item: item[0]
    )

    return [
        candidate
        for _, candidate
        in ranked
    ]


# ---------------------------------------------------------------------------
# Mutation plan construction
# ---------------------------------------------------------------------------


def build_mutation_plan(
    source_code: str,
    round_number: int,
    source_path: str | None = None,
    history: list[dict[str, Any]] | None = None,
    feedback_mode: bool = False,
) -> dict[str, Any]:
    """
    Build a deterministic package-aware mutation plan.

    The planner does not use detector feedback to optimize detector
    evasion. Feedback mode is retained as experiment metadata so the
    same planner interface can be used across experimental conditions.
    """

    analysis = analyze_source(
        source_code,
        source_path,
    )

    # Build only operationally suitable candidates.
    candidates = _build_candidates(
        analysis
    )

    if not candidates:
        raise ValueError(
            "No mutation-suitable structural "
            "targets were found in source file."
        )

    ranked = _rank_candidates(
        candidates,
        history,
        source_path or "",
    )

    # If every compatible target/transformation combination has been
    # attempted, start a deterministic new cycle.
    if not ranked:

        ranked = sorted(
            candidates,
            key=lambda candidate: (
                TARGET_PRIORITY.get(
                    str(
                        candidate.get(
                            "target_type",
                            "",
                        )
                    ),
                    99,
                ),
                -int(
                    candidate.get(
                        "score",
                        0,
                    )
                ),
                int(
                    candidate.get(
                        "features",
                        {},
                    ).get(
                        "lines",
                        0,
                    )
                ),
                str(
                    candidate.get(
                        "target",
                        "",
                    )
                ),
            ),
        )

    selected = ranked[0]

    target = str(
        selected["target"]
    )

    target_type = str(
        selected["target_type"]
    )

    attempted = _attempted_keys(
        history
    )

    transformation = _choose_transformation(
        round_number=round_number,
        used_keys=attempted,
        target_source=source_path or "",
        target=target,
        candidate=selected,
    )

    target_features = selected[
        "features"
    ]

    target_functions: list[str] = []

    if target_type == "function":
        target_functions = [
            target
        ]

    # Helpful planner metadata for debugging and experiment auditing.
    compatible_transformations = (
        _transformations_for_candidate(
            selected
        )
    )

    return {
        "round": round_number,

        "target_type": target_type,

        "target": target,

        "target_functions": (
            target_functions
        ),

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

        "candidate_features": (
            target_features
        ),

        "compatible_transformations": (
            list(
                compatible_transformations
            )
        ),

        "package_features": analysis,

        "feedback_mode": feedback_mode,

        "reason": (
            "Selected using mutation-suitability "
            "ranking with target-size constraints "
            "and transformation compatibility."
        ),
    }