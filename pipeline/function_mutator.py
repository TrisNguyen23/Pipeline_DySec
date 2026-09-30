from __future__ import annotations

import ast
import textwrap


def extract_function(
    source: str,
    qualified_name: str,
) -> str:

    tree = ast.parse(source)

    target = None

    def visit(
        node: ast.AST,
        parent_name: str = "",
    ) -> None:
        nonlocal target

        for child in ast.iter_child_nodes(node):

            if isinstance(
                child,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            ):
                name = (
                    f"{parent_name}.{child.name}"
                    if parent_name
                    else child.name
                )

                if name == qualified_name:
                    target = child
                    return

                visit(
                    child,
                    name,
                )

            elif isinstance(
                child,
                ast.ClassDef,
            ):
                name = (
                    f"{parent_name}.{child.name}"
                    if parent_name
                    else child.name
                )

                visit(
                    child,
                    name,
                )

            else:
                visit(
                    child,
                    parent_name,
                )

    visit(tree)

    if target is None:
        raise ValueError(
            f"Function not found: {qualified_name}"
        )

    segment = ast.get_source_segment(
        source,
        target,
    )

    if segment is None:
        raise ValueError(
            f"Unable to extract function: "
            f"{qualified_name}"
        )

    return segment


def replace_function(
    source: str,
    qualified_name: str,
    replacement: str,
) -> str:

    tree = ast.parse(source)

    target = None

    def visit(
        node: ast.AST,
        parent_name: str = "",
    ) -> None:
        nonlocal target

        for child in ast.iter_child_nodes(node):

            if isinstance(
                child,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            ):
                name = (
                    f"{parent_name}.{child.name}"
                    if parent_name
                    else child.name
                )

                if name == qualified_name:
                    target = child
                    return

                visit(
                    child,
                    name,
                )

            elif isinstance(
                child,
                ast.ClassDef,
            ):
                name = (
                    f"{parent_name}.{child.name}"
                    if parent_name
                    else child.name
                )

                visit(
                    child,
                    name,
                )

            else:
                visit(
                    child,
                    parent_name,
                )

    visit(tree)

    if target is None:
        raise ValueError(
            f"Function not found: {qualified_name}"
        )

    lines = source.splitlines(
        keepends=True
    )

    start = target.lineno - 1
    end = target.end_lineno

    indentation = (
        len(lines[start])
        - len(lines[start].lstrip())
    )

    replacement_lines = (
        textwrap.dedent(
            replacement
        )
        .splitlines(
            keepends=True
        )
    )

    replacement_lines = [
        (
            " " * indentation + line
            if line.strip()
            else line
        )
        for line in replacement_lines
    ]

    lines[start:end] = replacement_lines

    return "".join(lines)