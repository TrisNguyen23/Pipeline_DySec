STRATEGIES = [
    {
        "name": "strategy_A",
        "description": """
Apply SUBSTANTIAL STRUCTURAL REFACTORING to the internal Python source code
while preserving all observable behavior and side effects.

The goal is to produce a meaningful structural transformation rather than a
superficial edit.

Possible transformations include:
- decomposing a large internal function into multiple cooperating helpers
- consolidating several closely related internal operations
- reorganising responsibilities between existing internal functions
- introducing an additional internal abstraction layer
- moving related computations into logically separated internal helpers
- restructuring multiple related code blocks together
- replacing deeply nested internal organisation with equivalent layered
  organisation
- reorganising how internal helper functions cooperate
- restructuring several related functions consistently rather than modifying
  only one local statement

The transformation should affect a meaningful portion of the internal
implementation when the source code permits it.

AVOID SUPERFICIAL TRANSFORMATIONS:
- simple variable renaming alone
- formatting-only changes
- comment-only changes
- whitespace changes
- simple statement reordering without structural impact
- changing a single local expression without broader restructuring

The resulting implementation should remain recognisably equivalent in
functionality while being substantially reorganised internally.

CRITICAL COMPATIBILITY CONSTRAINTS:
- ONLY modify internal Python source files (.py).
- ABSOLUTELY DO NOT modify, create, delete, or touch:
  setup.py, pyproject.toml, setup.cfg, MANIFEST.in, or any package metadata.
- DO NOT add, remove, rename, upgrade, downgrade, or replace dependencies.
- Preserve all existing imports and dependency requirements unless an import
  becomes genuinely unnecessary because of the internal refactoring.
- Preserve function signatures, module names, public APIs, inputs, outputs,
  return values, exceptions, and externally observable side effects.
- Do not introduce new functionality.
- Do not remove existing functionality.
- Do not alter package metadata or installation configuration.
- The resulting source code must be syntactically valid Python.
- The resulting package must remain installable using the original packaging
  configuration.
- Preserve externally observable behaviour.

Prefer transformations involving multiple related internal functions when
this can be done safely.

Only apply transformations that are semantically equivalent to the original.
""",
    },

    {
        "name": "strategy_B",
        "description": """
Apply SUBSTANTIAL CONTROL-FLOW AND DATA-FLOW RESTRUCTURING to the internal
Python source code while preserving all observable behavior and side effects.

The transformation should meaningfully restructure how existing computations
are organised internally.

Possible transformations include:
- decomposing complex control flow into cooperating helper functions
- restructuring nested conditionals into equivalent internal decision stages
- reorganising loop-based processing into equivalent multi-stage processing
- introducing intermediate values or internal processing stages
- changing the internal order in which independent computations are performed
  when their observable semantics remain unchanged
- restructuring data passed between internal helper functions
- replacing one equivalent control-flow organisation with another
- separating validation, computation, and result construction into internal
  stages
- combining several small internal operations into a coordinated processing
  stage
- restructuring multiple execution paths while preserving their outcomes

The transformation should involve meaningful changes to control or data flow,
not merely cosmetic edits.

AVOID SUPERFICIAL TRANSFORMATIONS:
- variable renaming alone
- formatting-only changes
- comment-only changes
- changing one condition without broader restructuring
- replacing a single expression with an equivalent expression
- arbitrary statement reordering that does not change internal structure

CRITICAL COMPATIBILITY CONSTRAINTS:
- ONLY modify internal Python source files (.py).
- ABSOLUTELY DO NOT modify, create, delete, or touch:
  setup.py, pyproject.toml, setup.cfg, MANIFEST.in, or any package metadata.
- DO NOT add, remove, rename, upgrade, downgrade, or replace dependencies.
- Preserve existing imports and dependency requirements.
- Preserve function signatures, module names, and public APIs.
- Preserve inputs, outputs, return values, exceptions, and externally
  observable side effects.
- Do not introduce new functionality.
- Do not remove existing functionality.
- Do not change package metadata or installation configuration.
- The resulting source code must be syntactically valid Python.
- The resulting package must remain installable using the original packaging
  configuration.

Only apply transformations that are semantically equivalent to the original.
""",
    },

    {
        "name": "strategy_C",
        "description": """
Apply SUBSTANTIAL IMPLEMENTATION-LEVEL RESTRUCTURING to the internal Python
source code while preserving all observable behavior and side effects.

The objective is to change how existing functionality is internally
implemented, rather than merely changing its appearance.

Possible transformations include:
- restructuring intermediate representations
- changing how intermediate values are produced and consumed
- replacing one internal algorithmic idiom with an equivalent one
- reorganising local computation into multiple internal stages
- changing internal data preparation and reconstruction steps
- introducing equivalent internal helper abstractions
- replacing direct computation with an equivalent sequence of internal
  operations
- changing internal representation while preserving the same external result
- restructuring repeated internal computation into reusable helpers
- replacing one equivalent implementation pattern with another appropriate
  pattern already expressible using the package's existing dependencies

The transformation may affect multiple related functions when necessary to
produce a coherent implementation.

AVOID SUPERFICIAL TRANSFORMATIONS:
- variable renaming alone
- formatting changes
- comment changes
- simple constant renaming
- single-expression substitutions with no meaningful implementation change

Do not introduce unnecessary complexity purely for its own sake. The resulting
implementation must remain understandable, maintainable, syntactically valid,
and semantically equivalent.

CRITICAL COMPATIBILITY CONSTRAINTS:
- ONLY modify internal Python source files (.py).
- ABSOLUTELY DO NOT modify, create, delete, or touch:
  setup.py, pyproject.toml, setup.cfg, MANIFEST.in, or any package metadata.
- DO NOT add, remove, upgrade, downgrade, or replace dependencies.
- Do not introduce external libraries.
- Preserve existing imports and dependency requirements.
- Preserve all function signatures, module names, and public APIs.
- Preserve inputs, outputs, return values, exceptions, and externally
  observable side effects.
- Do not introduce new functionality.
- Do not remove existing functionality.
- Do not alter package installation behaviour.
- The resulting source code must remain installable using the original
  packaging configuration.

Only apply transformations that are semantically equivalent to the original.
""",
    },
]