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

    description = strategy.get(
        "description",
        "",
    ).strip()

    if not description:
        raise ValueError(
            "Strategy description cannot be empty."
        )

    return f"""
You are an automated Python source-code
transformation system for academic robustness
evaluation.

Your task is to transform ONLY the supplied
Python source file according to the specified
transformation strategy.

TRANSFORMATION STRATEGY
-----------------------
{description}

TARGET FILE
-----------
{relative_path}

STRICT REQUIREMENTS
-------------------

1. Preserve the original program behaviour.

2. Preserve the functional purpose of the code.

3. Preserve all public functions, classes, methods,
   and their interfaces.

4. Preserve function signatures unless the strategy
   explicitly requires an internal implementation
   change.

5. Preserve inputs, outputs, and return values.

6. Preserve relevant exception behaviour.

7. Preserve observable side effects.

8. Preserve required imports and dependencies.

9. Do not remove existing functionality.

10. Do not add unrelated functionality.

11. Do not introduce external dependencies.

12. Do not modify package metadata or dependency
    declarations.

13. Do not modify any file other than the supplied
    source file.

14. Do not introduce malicious payloads, persistence,
    credential theft, destructive behaviour, or
    unrelated network activity.

15. Make the smallest reasonable transformation
    required by the strategy.

16. The transformed source must remain valid Python.

17. Preserve compatibility with the surrounding
    package.

18. Return the COMPLETE transformed source file.

19. Never omit unchanged code.

20. Never use placeholders such as:
    "rest of code unchanged"
    "..."
    "same as above"

21. Do not return Markdown.

22. Do not use code fences.

23. Do not provide explanations.

24. Return ONLY the transformed Python source code.

SOURCE CODE
-----------
{source_code}
""".strip()