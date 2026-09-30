from __future__ import annotations

import ast
import hashlib
import io
import tokenize
from collections import Counter
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Any


MIN_CHANGED_FUNCTIONS = {
    1: 1,
    2: 1,
    3: 2,
    4: 2,
    5: 2,
}

MIN_STRUCTURAL_SCORE = {
    1: 0.10,
    2: 0.20,
    3: 0.35,
    4: 0.50,
    5: 0.60,
}


@dataclass
class FunctionInfo:
    qualified_name: str
    lineno: int
    end_lineno: int
    ast_nodes: int
    source_hash: str


@dataclass
class ComplexityMetrics:
    lines: int
    ast_nodes: int
    functions: int
    classes: int
    loops: int
    conditionals: int
    try_blocks: int
    comprehensions: int
    calls: int
    assignments: int
    returns: int


@dataclass
class DiversityResult:
    accepted: bool
    reason: str

    exact_match: bool

    source_similarity: float
    token_similarity: float
    normalized_similarity: float

    changed_functions: int
    added_functions: int
    removed_functions: int

    original_metrics: dict[str, Any]
    variant_metrics: dict[str, Any]

    ast_node_delta: int
    ast_node_ratio: float

    structural_score: float

    original_hash: str
    variant_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256(text: str) -> str:
    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


def _safe_ratio(
    numerator: float,
    denominator: float,
) -> float:
    if denominator == 0:
        return 0.0

    return numerator / denominator


def _count_lines(source: str) -> int:
    if not source.strip():
        return 0

    return len(source.splitlines())


def _parse_source(source: str) -> ast.AST:
    return ast.parse(source)


def _function_source(
    source: str,
    node: ast.AST,
) -> str:
    segment = ast.get_source_segment(
        source,
        node,
    )

    if segment is not None:
        return segment

    return ast.dump(
        node,
        include_attributes=False,
    )


def _iter_functions(
    tree: ast.AST,
    source: str,
) -> list[FunctionInfo]:

    results: list[FunctionInfo] = []

    def visit(
        node: ast.AST,
        parent_name: str = "",
    ) -> None:

        for child in ast.iter_child_nodes(node):

            if isinstance(
                child,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            ):
                if parent_name:
                    qualified_name = (
                        f"{parent_name}.{child.name}"
                    )
                else:
                    qualified_name = child.name

                segment = _function_source(
                    source,
                    child,
                )

                results.append(
                    FunctionInfo(
                        qualified_name=qualified_name,
                        lineno=getattr(
                            child,
                            "lineno",
                            0,
                        ),
                        end_lineno=getattr(
                            child,
                            "end_lineno",
                            getattr(
                                child,
                                "lineno",
                                0,
                            ),
                        ),
                        ast_nodes=sum(
                            1
                            for _ in ast.walk(child)
                        ),
                        source_hash=_sha256(segment),
                    )
                )

                visit(
                    child,
                    qualified_name,
                )

            elif isinstance(
                child,
                ast.ClassDef,
            ):
                class_name = (
                    f"{parent_name}.{child.name}"
                    if parent_name
                    else child.name
                )

                visit(
                    child,
                    class_name,
                )

            else:
                visit(
                    child,
                    parent_name,
                )

    visit(tree)

    return results


class _ComplexityVisitor(ast.NodeVisitor):

    def __init__(self) -> None:
        self.functions = 0
        self.classes = 0
        self.loops = 0
        self.conditionals = 0
        self.try_blocks = 0
        self.comprehensions = 0
        self.calls = 0
        self.assignments = 0
        self.returns = 0

    def visit_FunctionDef(self, node):
        self.functions += 1
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self.functions += 1
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self.classes += 1
        self.generic_visit(node)

    def visit_For(self, node):
        self.loops += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node):
        self.loops += 1
        self.generic_visit(node)

    def visit_While(self, node):
        self.loops += 1
        self.generic_visit(node)

    def visit_If(self, node):
        self.conditionals += 1
        self.generic_visit(node)

    def visit_Try(self, node):
        self.try_blocks += 1
        self.generic_visit(node)

    def visit_Call(self, node):
        self.calls += 1
        self.generic_visit(node)

    def visit_Assign(self, node):
        self.assignments += 1
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        self.assignments += 1
        self.generic_visit(node)

    def visit_Return(self, node):
        self.returns += 1
        self.generic_visit(node)

    def visit_ListComp(self, node):
        self.comprehensions += 1
        self.generic_visit(node)

    def visit_SetComp(self, node):
        self.comprehensions += 1
        self.generic_visit(node)

    def visit_DictComp(self, node):
        self.comprehensions += 1
        self.generic_visit(node)

    def visit_GeneratorExp(self, node):
        self.comprehensions += 1
        self.generic_visit(node)


def calculate_complexity(
    source: str,
) -> ComplexityMetrics:

    tree = _parse_source(source)

    visitor = _ComplexityVisitor()
    visitor.visit(tree)

    return ComplexityMetrics(
        lines=_count_lines(source),
        ast_nodes=sum(
            1
            for _ in ast.walk(tree)
        ),
        functions=visitor.functions,
        classes=visitor.classes,
        loops=visitor.loops,
        conditionals=visitor.conditionals,
        try_blocks=visitor.try_blocks,
        comprehensions=visitor.comprehensions,
        calls=visitor.calls,
        assignments=visitor.assignments,
        returns=visitor.returns,
    )


def _tokenize_source(
    source: str,
) -> list[str]:

    tokens: list[str] = []

    try:
        generated = tokenize.generate_tokens(
            io.StringIO(source).readline
        )

        for token in generated:
            token_type = token.type
            token_string = token.string

            if token_type in (
                tokenize.ENCODING,
                tokenize.ENDMARKER,
                tokenize.NL,
                tokenize.NEWLINE,
                tokenize.INDENT,
                tokenize.DEDENT,
                tokenize.COMMENT,
            ):
                continue

            if token_type == tokenize.NAME:
                tokens.append("<NAME>")

            elif token_type == tokenize.STRING:
                tokens.append("<STRING>")

            elif token_type == tokenize.NUMBER:
                tokens.append("<NUMBER>")

            else:
                tokens.append(token_string)

    except (tokenize.TokenError, IndentationError):
        return []

    return tokens


def _token_similarity(
    original: str,
    variant: str,
) -> float:

    original_tokens = _tokenize_source(original)
    variant_tokens = _tokenize_source(variant)

    if not original_tokens and not variant_tokens:
        return 1.0

    if not original_tokens or not variant_tokens:
        return 0.0

    return SequenceMatcher(
        None,
        original_tokens,
        variant_tokens,
        autojunk=False,
    ).ratio()


class _NormalizeNames(ast.NodeTransformer):

    def visit_Name(self, node):
        node.id = "<NAME>"
        return node

    def visit_arg(self, node):
        node.arg = "<ARG>"
        return node


def _normalized_ast(
    source: str,
) -> str:

    tree = _parse_source(source)

    tree = _NormalizeNames().visit(tree)

    ast.fix_missing_locations(tree)

    return ast.dump(
        tree,
        annotate_fields=True,
        include_attributes=False,
    )


def _normalized_similarity(
    original: str,
    variant: str,
) -> float:

    original_ast = _normalized_ast(original)
    variant_ast = _normalized_ast(variant)

    return SequenceMatcher(
        None,
        original_ast,
        variant_ast,
        autojunk=False,
    ).ratio()


def _function_map(
    source: str,
) -> dict[str, FunctionInfo]:

    tree = _parse_source(source)

    functions = _iter_functions(
        tree,
        source,
    )

    return {
        function.qualified_name: function
        for function in functions
    }


def _compare_functions(
    original: str,
    variant: str,
) -> tuple[int, int, int]:

    original_functions = _function_map(original)
    variant_functions = _function_map(variant)

    original_names = set(original_functions)
    variant_names = set(variant_functions)

    added = variant_names - original_names
    removed = original_names - variant_names

    common = original_names & variant_names

    changed = sum(
        1
        for name in common
        if (
            original_functions[name].source_hash
            != variant_functions[name].source_hash
        )
    )

    changed += len(added)
    changed += len(removed)

    return (
        changed,
        len(added),
        len(removed),
    )


def _calculate_structural_score(
    original_metrics: ComplexityMetrics,
    variant_metrics: ComplexityMetrics,
    changed_functions: int,
    normalized_similarity: float,
) -> float:

    node_difference = abs(
        variant_metrics.ast_nodes
        - original_metrics.ast_nodes
    )

    node_ratio = _safe_ratio(
        node_difference,
        max(
            original_metrics.ast_nodes,
            1,
        ),
    )

    function_difference = abs(
        variant_metrics.functions
        - original_metrics.functions
    )

    function_ratio = _safe_ratio(
        function_difference,
        max(
            original_metrics.functions,
            1,
        ),
    )

    control_original = (
        original_metrics.loops
        + original_metrics.conditionals
        + original_metrics.try_blocks
    )

    control_variant = (
        variant_metrics.loops
        + variant_metrics.conditionals
        + variant_metrics.try_blocks
    )

    control_difference = abs(
        control_variant - control_original
    )

    control_ratio = _safe_ratio(
        control_difference,
        max(control_original, 1),
    )

    changed_function_ratio = _safe_ratio(
        changed_functions,
        max(
            original_metrics.functions,
            variant_metrics.functions,
            1,
        ),
    )

    structural_difference = (
        1.0 - normalized_similarity
    )

    score = (
        0.40 * structural_difference
        + 0.25 * min(node_ratio, 1.0)
        + 0.20 * min(changed_function_ratio, 1.0)
        + 0.10 * min(function_ratio, 1.0)
        + 0.05 * min(control_ratio, 1.0)
    )

    return round(
        min(max(score, 0.0), 1.0),
        4,
    )


def analyze_diversity(
    original_source: str,
    variant_source: str,
    complexity_level: int = 1,
) -> DiversityResult:

    if not original_source.strip():
        raise ValueError(
            "Original source cannot be empty."
        )

    if not variant_source.strip():
        raise ValueError(
            "Variant source cannot be empty."
        )

    complexity_level = max(
        1,
        min(int(complexity_level), 5),
    )

    original_hash = _sha256(
        original_source
    )

    variant_hash = _sha256(
        variant_source
    )

    exact_match = (
        original_hash == variant_hash
    )

    original_metrics = calculate_complexity(
        original_source
    )

    variant_metrics = calculate_complexity(
        variant_source
    )

    (
        changed_functions,
        added_functions,
        removed_functions,
    ) = _compare_functions(
        original_source,
        variant_source,
    )

    source_similarity = SequenceMatcher(
        None,
        original_source,
        variant_source,
        autojunk=False,
    ).ratio()

    token_similarity = _token_similarity(
        original_source,
        variant_source,
    )

    normalized_similarity = _normalized_similarity(
        original_source,
        variant_source,
    )

    ast_node_delta = (
        variant_metrics.ast_nodes
        - original_metrics.ast_nodes
    )

    ast_node_ratio = _safe_ratio(
        abs(ast_node_delta),
        max(
            original_metrics.ast_nodes,
            1,
        ),
    )

    structural_score = _calculate_structural_score(
        original_metrics,
        variant_metrics,
        changed_functions,
        normalized_similarity,
    )

    minimum_changed_functions = (
        MIN_CHANGED_FUNCTIONS[
            complexity_level
        ]
    )

    minimum_structural_score = (
        MIN_STRUCTURAL_SCORE[
            complexity_level
        ]
    )

    if exact_match:
        accepted = False
        reason = (
            "Variant is identical to the "
            "original source."
        )

    elif (
        changed_functions == 0
        and normalized_similarity >= 0.99
    ):
        accepted = False
        reason = (
            "Variant appears to contain only "
            "cosmetic or identifier-level changes."
        )

    elif changed_functions < minimum_changed_functions:
        accepted = False
        reason = (
            f"Only {changed_functions} meaningful "
            f"function-level changes detected; "
            f"level {complexity_level} requires "
            f"at least {minimum_changed_functions}."
        )

    elif structural_score < minimum_structural_score:
        accepted = False
        reason = (
            f"Structural diversity score "
            f"{structural_score:.3f} is below the "
            f"level-{complexity_level} threshold "
            f"{minimum_structural_score:.3f}."
        )

    else:
        accepted = True
        reason = (
            "Variant satisfies the structural "
            f"diversity requirements for level "
            f"{complexity_level}."
        )

    return DiversityResult(
        accepted=accepted,
        reason=reason,
        exact_match=exact_match,
        source_similarity=round(
            source_similarity,
            4,
        ),
        token_similarity=round(
            token_similarity,
            4,
        ),
        normalized_similarity=round(
            normalized_similarity,
            4,
        ),
        changed_functions=changed_functions,
        added_functions=added_functions,
        removed_functions=removed_functions,
        original_metrics=asdict(
            original_metrics
        ),
        variant_metrics=asdict(
            variant_metrics
        ),
        ast_node_delta=ast_node_delta,
        ast_node_ratio=round(
            ast_node_ratio,
            4,
        ),
        structural_score=structural_score,
        original_hash=original_hash,
        variant_hash=variant_hash,
    )


def is_sufficiently_different(
    original_source: str,
    variant_source: str,
    complexity_level: int = 1,
) -> bool:

    return analyze_diversity(
        original_source,
        variant_source,
        complexity_level,
    ).accepted


def diversity_report(
    original_source: str,
    variant_source: str,
    complexity_level: int = 1,
) -> dict[str, Any]:

    return analyze_diversity(
        original_source,
        variant_source,
        complexity_level,
    ).to_dict()