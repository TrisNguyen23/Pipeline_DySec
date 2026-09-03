from __future__ import annotations


def build_prompt(
    strategy: dict,
    relative_path: str,
    source_code: str,
) -> str:

    if not source_code.strip():
        raise ValueError(
            "Source code cannot be empty."
        )

    return f"""
You are an automated software transformation
system for academic robustness evaluation.

Transform the supplied Python source file according
to the specified transformation strategy.

Strategy:

{strategy["description"]}

Target file:

{relative_path}

Requirements:

1. Preserve the original semantics.
2. Preserve inputs and outputs.
3. Preserve return values.
4. Preserve relevant exceptions.
5. Preserve side effects.
6. Preserve package interfaces.
7. Preserve imports and required dependencies.
8. Do not remove functionality.
9. Do not add unrelated functionality.
10. Do not introduce external dependencies.
11. Keep the code valid Python.
12. Modify only the supplied source file.
13. Return ONLY the complete transformed Python source.
14. Do not use Markdown.
15. Do not use code fences.
16. Do not provide explanations.

Source code:

{source_code}
""".strip()