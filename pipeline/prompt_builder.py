from __future__ import annotations

from typing import Any

from pipeline.mutation_planner import (
    COMPLEXITY_LEVELS,
    get_complexity_level,
)


def _format_plan(
    mutation_plan: dict[str, Any],
) -> str:
    operations = mutation_plan.get("operations", [])
    targets = mutation_plan.get("target_functions", [])
    level = mutation_plan.get("level", 1)

    lines = [
        f"Mutation level: {level}",
        "Target functions:",
    ]

    if targets:
        lines.extend(
            f"- {name}"
            for name in targets
        )
    else:
        lines.append("- Use only the selected target.")

    lines.append("")
    lines.append("Allowed operations:")

    if operations:
        lines.extend(
            f"- {operation}"
            for operation in operations
        )
    else:
        lines.append(
            "- No predefined operation; perform only "
            "a minimal behaviour-preserving refactoring."
        )

    return "\n".join(lines)


def build_prompt(
    relative_path: str,
    source_code: str,
    round_number: int,
    mutation_plan: dict[str, Any],
    feedback_history: list[dict[str, Any]] | None = None,
) -> str:
    level = get_complexity_level(round_number)
    level_info = COMPLEXITY_LEVELS[level]

    history = feedback_history or []

    previous_text = ""

    if history:
        previous_text = (
            "\nPrevious valid transformations performed "
            "on this evolving variant:\n"
        )

        for item in history[-5:]:
            previous_text += (
                f"- Round {item.get('round')}: "
                f"{item.get('operations', [])}\n"
            )

    plan_text = _format_plan(mutation_plan)

    return f"""
You are performing a controlled source-level refactoring
experiment on a Python package.

This is mutation round {round_number} of a progressive
15-round experiment.

REFACTORING LEVEL:
{level} ({level_info["name"]})

{level_info["instruction"]}

TARGET FILE:
{relative_path}

MUTATION PLAN:
{plan_text}

SOURCE CODE:
```python
{source_code}
PRIMARY OBJECTIVE:

Create a behaviour-preserving internal refactoring of the
supplied source code.

The generated source must remain close to the original source
while implementing the specified mutation plan.

STRICT SCOPE:

Modify ONLY the supplied Python source file.

Do NOT modify package metadata.
Do NOT add package dependencies.
Do NOT introduce external libraries.
Do NOT change public APIs.
Do NOT change function signatures.
Preserve return values.
Preserve exceptions and observable behaviour.
Preserve side effects.
Preserve global state semantics.
Preserve module-level behaviour.
Do not add new functionality.
Do not remove functionality.
Do not modify unrelated functions.

SOURCE PRESERVATION:

Do NOT rewrite the whole file.
Do NOT regenerate the source from scratch.
Do NOT make broad stylistic changes.
Do NOT rename variables throughout the file.
Do NOT reformat unrelated code.
Do NOT change comments unless necessary.

Only change the smallest coherent region required.

SEMANTIC REQUIREMENT:

The package must behave equivalently for its existing inputs.

Do not inspect or target detector internals.
Do not optimize for a particular detector prediction.

OUTPUT FORMAT:

Return ONLY the complete Python source file.

Do NOT use markdown fences.
Do NOT provide explanations.
Do NOT provide analysis.

{previous_text}
""".strip()