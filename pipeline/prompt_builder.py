def build_prompt(
    strategy: dict,
    source_code: str,
) -> str:
    """
    Build the transformation prompt for one generation round.
    """

    if not source_code.strip():
        raise ValueError(
            "Source code cannot be empty."
        )

    return f"""
You are an automated software transformation tool
for academic robustness evaluation.

Your task is to transform the supplied Python source code
while preserving its observable semantics.

Transformation strategy:

{strategy["description"]}

Requirements:

1. Preserve the original observable behavior.
2. Preserve required side effects.
3. Preserve input and output behavior.
4. Preserve return values.
5. Preserve relevant exception behavior.
6. Preserve required package interfaces.
7. Preserve required dependencies.
8. Do not remove existing functionality.
9. Do not add unrelated functionality.
10. Do not change package metadata unless explicitly required.
11. Do not introduce external dependencies.
12. The transformed program must remain valid Python.
13. Return ONLY the complete transformed Python source code.
14. Do not return Markdown.
15. Do not return ```python fences.
16. Do not explain the transformation.

Source code:

{source_code}
""".strip()