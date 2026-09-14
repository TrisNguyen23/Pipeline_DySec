from __future__ import annotations

"""
Prompt construction for progressive, behavior-preserving
Python source transformation.

The transformation becomes progressively more substantial
over five rounds while preserving the externally observable
behaviour of the original program.
"""

from typing import Optional


COMPLEXITY_LEVELS = {
    1: {
        "name": "Light Refactoring",
        "instructions": """
Apply relatively light source-level refactoring.

Allowed transformations include:
- Rename local variables where safe.
- Extract small helper functions.
- Simplify or reorganise expressions.
- Improve local code organisation.
- Replace equivalent Python constructs.

Do not substantially redesign the program architecture.
The resulting implementation should remain recognisably
similar to the original implementation.
""",
    },

    2: {
        "name": "Structural Refactoring",
        "instructions": """
Apply a moderate structural refactoring.

In addition to the previous level:
- Split larger functions into multiple cohesive helpers.
- Merge trivial helper functions where appropriate.
- Reorganise related operations into logical components.
- Change data-flow between internal helper functions.
- Introduce lightweight abstractions where they improve structure.
- Change the organisation of classes, functions, or internal
  data structures when behaviour remains equivalent.

Avoid superficial changes such as comments or meaningless
renaming as the primary transformation.
""",
    },

    3: {
        "name": "Control-Flow Refactoring",
        "instructions": """
Perform a substantial control-flow refactoring.

In addition to the previous levels:
- Restructure conditional logic while preserving semantics.
- Replace equivalent control-flow patterns where appropriate.
- Introduce or remove intermediate helper functions.
- Change the order of independent internal computations when
  this is demonstrably behaviour-preserving.
- Introduce clearer intermediate states or dispatch logic.
- Move logic between functions when the observable behaviour
  remains unchanged.

The generated implementation should be meaningfully different
from the input rather than being a collection of cosmetic edits.
""",
    },

    4: {
        "name": "Implementation Redesign",
        "instructions": """
Perform a major internal implementation redesign.

The implementation should differ substantially from the
original source structure.

Consider:
- Alternative internal algorithms with equivalent results.
- Different data representations.
- Different decomposition of responsibilities.
- Multiple layers of helper functions.
- Alternative but equivalent Python mechanisms.
- Reorganisation of the execution flow.
- Moving responsibilities between components.

Preserve all required externally observable behaviour.
Do not introduce unnecessary functionality unrelated to the
original program.
""",
    },

    5: {
        "name": "High-Complexity Redesign",
        "instructions": """
Perform the strongest behavior-preserving transformation in
this experiment.

Produce a substantially redesigned implementation rather
than a cosmetic refactor.

The generated implementation may use:
- A significantly different internal architecture.
- Multiple layers of abstraction.
- Alternative data representations.
- Different control-flow organisation.
- Additional cohesive helper functions.
- Alternative equivalent implementation techniques.
- More distributed internal responsibilities.

The transformation should result in a genuinely different
implementation while preserving the original externally
observable behaviour.

Do not add meaningless dead code merely to increase line count.
Additional code should have a legitimate role in the
implementation.
""",
    },
}


def _get_complexity_level(round_number: Optional[int]) -> dict:
    """Return the progressive transformation level for a round."""
    if round_number is None:
        round_number = 1

    try:
        round_number = int(round_number)
    except (TypeError, ValueError):
        round_number = 1

    round_number = max(1, min(round_number, 5))

    return COMPLEXITY_LEVELS[round_number]


def build_prompt(
    strategy: dict,
    relative_path: str,
    source_code: str,
    round_number: int = 1,
    previous_verdict: str | None = None,
    feedback_history: list[dict] | None = None,
) -> str:
    """
    Build a progressive behavior-preserving transformation prompt.

    Args:
        strategy:
            Strategy definition from config/strategies.py.

        relative_path:
            Relative path of the target Python source file.

        source_code:
            Current source code to transform.

        round_number:
            Current transformation round (1-5).

        previous_verdict:
            Result of the previous DySec evaluation, if available.

        feedback_history:
            Previous round results within the current strategy.

    Returns:
        A complete prompt for the LLM.
    """

    if not source_code.strip():
        raise ValueError("Source code cannot be empty.")

    description = strategy.get("description", "").strip()

    if not description:
        raise ValueError("Strategy description cannot be empty.")

    level = _get_complexity_level(round_number)

    feedback_section = ""

    if previous_verdict:
        feedback_section = f"""
PREVIOUS EVALUATION
-------------------
The previous generated implementation received the following
evaluation result:

{previous_verdict}

Generate a new implementation rather than simply repeating
the previous transformation.

The new version should make a meaningful additional change
consistent with the current transformation level.
""".strip()

    history_section = ""

    if feedback_history:
        history_lines = []

        for item in feedback_history:
            round_id = item.get("round", "?")
            verdict = item.get("verdict", "UNKNOWN")

            history_lines.append(
                f"- Round {round_id}: {verdict}"
            )

        history_section = f"""
PREVIOUS ROUND HISTORY
----------------------
{chr(10).join(history_lines)}
""".strip()

    return f"""
You are an automated Python source-code transformation
system for academic software robustness evaluation.

Your task is to transform ONLY the supplied Python source
file according to the specified transformation strategy and
progressive complexity level.

The most important requirement is preservation of the
original externally observable behaviour.

TRANSFORMATION STRATEGY
-----------------------
{description}

PROGRESSIVE COMPLEXITY LEVEL
----------------------------
Round: {round_number}
Level: {level["name"]}

{level["instructions"].strip()}

TARGET FILE
-----------
{relative_path}

BEHAVIOUR PRESERVATION
----------------------
The transformed implementation must preserve the original
program's required externally observable behaviour.

In particular:

1. Preserve the program's intended functionality.
2. Preserve required inputs and outputs.
3. Preserve relevant return values.
4. Preserve required exceptions and error behaviour.
5. Preserve required file, network, process, and system
   interactions when they are part of the original behaviour.
6. Do not remove required functionality.
7. Do not introduce unrelated functionality.
8. Do not intentionally alter behaviour merely to make the
   source code appear different.
9. Do not use meaningless dead code solely to increase the
   number of lines.
10. Keep the resulting file valid, executable Python.

PROGRESSIVE TRANSFORMATION
--------------------------
This is round {round_number} of a progressive transformation.

The implementation should be more substantially transformed
than an earlier round when possible.

However, complexity alone is not the objective. Every
additional abstraction, helper, restructuring, or
implementation change should have a legitimate role in
implementing the original functionality.

{feedback_section}

{history_section}

OUTPUT REQUIREMENTS
-------------------
Return ONLY the complete transformed Python source code.

Do not return:
- Markdown code fences.
- Explanations.
- Comments outside the Python source.
- Analysis of the transformation.
- Any text before or after the Python source.

SOURCE CODE
-----------
{source_code}
""".strip()