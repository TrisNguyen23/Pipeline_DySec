from __future__ import annotations

import json
from typing import Any


def _format_plan(
    mutation_plan: dict[str, Any],
) -> str:
    """
    Format the mutation plan into a deterministic text representation.
    """

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
        "candidate_score",
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
            "Candidate suitability score: "
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
    """
    Format package-level structural analysis.
    """

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
    """
    Format previous mutation attempts.

    Historical detector feedback is reported as experiment metadata.
    It is not converted into mutation-selection instructions.
    """

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

        target_type = entry.get(
            "target_type",
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
            f"target_type={target_type}, "
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
    """
    Format the latest external evaluation result.

    This information is descriptive only. It must not be used to
    instruct the model to optimize against the detector.
    """

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


def _target_instruction(
    mutation_plan: dict[str, Any],
) -> str:
    """
    Generate target-specific instructions without assuming that the
    target is a function.
    """

    target_type = mutation_plan.get(
        "target_type",
        "unknown",
    )

    target = mutation_plan.get(
        "target",
        "unknown",
    )

    start_line = mutation_plan.get(
        "start_line",
    )

    end_line = mutation_plan.get(
        "end_line",
    )

    if target_type == "function":

        return (
            f"Target type: function\n"
            f"Target function: {target}\n"
            f"Target lines: {start_line}-{end_line}"
        )

    if target_type == "class":

        return (
            f"Target type: class\n"
            f"Target class: {target}\n"
            f"Target lines: {start_line}-{end_line}"
        )

    if target_type == "module_block":

        return (
            f"Target type: module-level executable block\n"
            f"Target block: {target}\n"
            f"Target lines: {start_line}-{end_line}"
        )

    return (
        f"Target type: {target_type}\n"
        f"Target: {target}\n"
        f"Target lines: {start_line}-{end_line}"
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
    """
    Build the complete LLM mutation prompt.

    The prompt supports function, class, and module-level targets.
    Detector feedback is included only as observational experiment
    metadata and does not instruct adaptive detector evasion.
    """

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

    target_type = mutation_plan.get(
        "target_type",
        "unknown",
    )

    target = mutation_plan.get(
        "target",
        "unknown",
    )

    transformation = mutation_plan.get(
        "transformation",
        "unknown",
    )

    target_instruction = _target_instruction(
        mutation_plan
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
while applying the requested source-level
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

Target type:
{target_type}

Target:
{target}

Requested transformation:
{transformation}

============================================================
TARGET INSTRUCTIONS
============================================================

{target_instruction}

The target may be a function, class, or
module-level executable block.

Modify the specified target only.

Do not replace the selected target with
an unrelated source region.

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

The planner output must be treated as the
authoritative mutation scope.

============================================================
PREVIOUS ATTEMPTS
============================================================

{history_text}

Previous attempts are provided for
experimental traceability.

Do not use previous detector results to
infer hidden detector features or construct
detector-specific evasion strategies.

============================================================
DYSEC FEEDBACK
============================================================

{dysec_text}

DySec is an external black-box evaluator.

The reported verdict and score are included
as observational experiment metadata only.

Do not infer the implementation, features,
thresholds, or internal decision process of
the detector.

Do not optimize the mutation specifically
against the detector.

============================================================
SOURCE
============================================================

```python
{source_code}
============================================================
MODIFICATION CONSTRAINTS

Modify ONLY this supplied Python source file.

Target:
{target}

Target type:
{target_type}

Requested transformation:
{transformation}

Target-specific scope:
{target_instruction}

Preserve:

function signatures
public API
class interfaces
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
rename public functions
rename public classes
add functionality
remove functionality
add persistence
add credential collection
add destructive behavior
add additional network communication
modify unrelated functions
modify unrelated classes
modify unrelated module-level code
rewrite the entire file unnecessarily

Keep the modification local to the requested
target.

The transformation should be structural or
semantic-preserving rather than merely
cosmetic.

============================================================
OUTPUT

Return ONLY the modified target region.

Do not return:

Markdown fences
explanations
analysis
diffs
planner information
comments outside the Python source
""".strip()