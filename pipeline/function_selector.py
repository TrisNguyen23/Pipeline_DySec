from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass
class FunctionTarget:
    name: str
    qualified_name: str
    lineno: int
    end_lineno: int


@dataclass
class ClassTarget:
    name: str
    qualified_name: str
    lineno: int
    end_lineno: int


@dataclass
class ModuleBlockTarget:
    name: str
    lineno: int
    end_lineno: int
    block_type: str


@dataclass
class SourceTargets:
    functions: list[FunctionTarget]
    classes: list[ClassTarget]
    module_blocks: list[ModuleBlockTarget]


def find_functions(
    source: str,
) -> list[FunctionTarget]:

    tree = ast.parse(source)

    targets: list[FunctionTarget] = []

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

                qualified_name = (
                    f"{parent_name}.{child.name}"
                    if parent_name
                    else child.name
                )

                targets.append(
                    FunctionTarget(
                        name=child.name,
                        qualified_name=qualified_name,
                        lineno=child.lineno,
                        end_lineno=(
                            child.end_lineno
                            or child.lineno
                        ),
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

    return targets


def find_classes(
    source: str,
) -> list[ClassTarget]:

    tree = ast.parse(source)

    targets: list[ClassTarget] = []

    def visit(
        node: ast.AST,
        parent_name: str = "",  
    ) -> None:

        for child in ast.iter_child_nodes(node):

            if isinstance(
                child,
                ast.ClassDef,
            ):

                qualified_name = (
                    f"{parent_name}.{child.name}"
                    if parent_name
                    else child.name
                )

                targets.append(
                    ClassTarget(
                        name=child.name,
                        qualified_name=qualified_name,
                        lineno=child.lineno,
                        end_lineno=(
                            child.end_lineno
                            or child.lineno
                        ),
                    )
                )

                visit(
                    child,
                    qualified_name,
                )

            elif isinstance(
                child,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            ):

                function_name = (
                    f"{parent_name}.{child.name}"
                    if parent_name
                    else child.name
                )

                visit(
                    child,
                    function_name,
                )

            else:

                visit(
                    child,
                    parent_name,
                )

    visit(tree)

    return targets


def find_module_blocks(
    source: str,
) -> list[ModuleBlockTarget]:

    tree = ast.parse(source)

    targets: list[ModuleBlockTarget] = []

    block_index = 0

    for node in tree.body:

        # Import statements are normally not useful
        # standalone mutation targets.
        if isinstance(
            node,
            (
                ast.Import,
                ast.ImportFrom,
            ),
        ):
            continue

        # Function/class definitions have their own
        # target representation.
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
            ),
        ):
            continue

        end_lineno = (
            node.end_lineno
            or node.lineno
        )

        block_index += 1

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

        else:
            block_type = type(node).__name__.lower()

        targets.append(
            ModuleBlockTarget(
                name=(
                    f"module_block_{block_index}"
                ),
                lineno=node.lineno,
                end_lineno=end_lineno,
                block_type=block_type,
            )
        )

    return targets


def find_source_targets(
    source: str,
) -> SourceTargets:

    return SourceTargets(
        functions=find_functions(source),
        classes=find_classes(source),
        module_blocks=find_module_blocks(source),
    )