from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FunctionTarget:
    name: str
    qualified_name: str
    lineno: int
    end_lineno: int


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
                        end_lineno=child.end_lineno,
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