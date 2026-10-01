from __future__ import annotations

import json
from typing import Any


def _format_plan(
    mutation_plan: dict[str, Any],
) -> str:

    target_type = mutation_plan.get(
        "target_type",
        "unknown",
    )

    target = mutation_plan.get(
        "target",
        "unknown",
    )

    target_source = mutation_plan.get(
        "target_source",
        "unknown",
    )

    transformation = mutation_plan.get(
        "transformation",
        "unknown",
    )

    reason = mutation_plan.get(
        "reason",
        "",
    )

    candidate_score = mutation_plan.get(
        "candidate_score"
    )

    candidate_features = mutation_plan.get(
        "candidate_features",
        {},
    )

    lines = [
        f"Target type: {target_type}",
        f"Target: {target}",
        f"Target source: {target_source}",
        f"Requested transformation: {transformation}",
    ]

    if candidate_score is not None:
        lines.append(
            f"Candidate suitability score: "
            f"{candidate_score}"
        )

    if candidate_features:
        lines.append(
            "Candidate features:\n"
            + json.dumps(
                candidate_features,
                indent=2,
                sort_keys=True,
            )
        )

    if reason:
        lines.append(
            f"Planner rationale: {reason}"
        )

    return "\n".join(lines)


def _format_package_features(
    package_features: dict[str, Any] | None,
) -> str:

    if not package_features:
        return (
            "No package-level analysis "
            "is available."
        )

    return json.dumps(
        package_features,
        indent=2,
        sort_keys=True,
    )


def _format_history(
    history: list[dict[str, Any]] | None,
) -> str:

    if not history:
        return (
            "No previous mutation attempts."
        )

    lines: list[str] = []

    for entry in history:

        round_number = entry.get(
            "round",
            "?",
        )

        target_source = entry.get(
            "target_source",
            "unknown",
        )

        target = entry.get(
            "target",
            "unknown",
        )

        transformation = entry.get(
            "transformation",
            "unknown",
        )

        status = entry.get(
            "status",
            "unknown",
        )

        lines.append(
            f"Round {round_number}: "
            f"source={target_source}, "
            f"target={target}, "
            f"transformation={transformation}, "
            f"status={status}"
        )

        dysec_feedback = entry.get(
            "dysec"
        )

        if isinstance(
            dysec_feedback,
            dict,
        ):

            verdict = dysec_feedback.get(
                "verdict",
                "UNKNOWN",
            )

            score = dysec_feedback.get(
                "score"
            )

            if score is None:
                lines.append(
                    f"  DySec verdict: {verdict}"
                )
            else:
                lines.append(
                    f"  DySec verdict: "
                    f"{verdict}, score={score}"
                )

    return "\n".join(lines)


def _format_dysec_feedback(
    dysec_feedback: dict[str, Any] | None,
) -> str:

    if not dysec_feedback:
        return (
            "No DySec feedback is available."
        )

    verdict = dysec_feedback.get(
        "verdict",
        "UNKNOWN",
    )

    score = dysec_feedback.get(
        "score"
    )

    if score is None:
        return (
            f"Latest DySec verdict: {verdict}"
        )

    return (
        f"Latest DySec verdict: {verdict}\n"
        f"Latest DySec score: {score}"
    )


def build_prompt(
    source_code: str,
    mutation_plan: dict[str, Any],
    round_number: int,
    target_source: str,
    history: list[dict[str, Any]] | None = None,
    package_features: dict[str, Any] | None = None,
    dysec_feedback: dict[str, Any] | None = None,
) -> str:

    plan_text = _format_plan(
        mutation_plan
    )

    package_text = _format_package_features(
        package_features
    )

    history_text = _format_history(
        history
    )

    dysec_text = _format_dysec_feedback(
        dysec_feedback
    )

    target = mutation_plan.get(
        "target",
        "unknown",
    )

    transformation = mutation_plan.get(
        "transformation",
        "unknown",
    )

    return f"""
You are participating in an authorized
security-research benchmark for evaluating
the robustness of Python package malware
detectors.

Your task is to generate ONE source-level
variant of the supplied Python file.

The generated variant should preserve the
observable behavior of the supplied code
while applying the requested source
transformation.

Do NOT add new malicious capabilities.
Do NOT add persistence, credential theft,
destructive behavior, or additional network
communication.

============================================================
EXPERIMENT
============================================================

Round: {round_number}

Target source:
{target_source}

Target:
{target}

Requested transformation:
{transformation}

============================================================
PACKAGE ANALYSIS
============================================================

{package_text}

============================================================
MUTATION PLAN
============================================================

{plan_text}

The mutation planner determines the target
and requested transformation.

Do not replace the target with an unrelated
function or source region.

============================================================
PREVIOUS ATTEMPTS
============================================================

{history_text}

============================================================
DYSEC FEEDBACK
============================================================

{dysec_text}

DySec is an external black-box evaluator.

If a previous variant was DETECTED, make
the next transformation substantively
different where possible.

Do not infer which internal detector
features caused detection.

Do not attempt to manipulate an assumed
detector implementation.

============================================================
SOURCE
============================================================

```python
{source_code}
============================================================
MODIFICATION CONSTRAINTS

Modify ONLY this supplied Python source file.

Target function:
{target}

Requested transformation:
{transformation}

Preserve:

function signatures
public API
return values
exception behavior
relevant side effects
module/global behavior
imports unless required by the transformation
package installation behavior
Python-version compatibility

Do NOT:

add dependencies
remove dependencies
modify package metadata
modify setup configuration
modify entry points
rename public functions/classes
add functionality
remove functionality
add persistence
add credential collection
add destructive behavior
add additional network communication
modify unrelated functions
rewrite the entire file unnecessarily

Keep the modification local to the requested
target.

The transformation should be structural or
semantic-preserving rather than merely cosmetic.

============================================================
OUTPUT

Return ONLY the complete modified Python
source code.

Do not return:

Markdown fences
explanations
analysis
diffs
planner information
comments outside the Python source
""".strip()