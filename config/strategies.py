STRATEGIES = [
    {
        "name": "strategy_A",
        "description": """
Apply structural refactoring while preserving the
original observable behavior and side effects.

Use equivalent restructuring of functions,
control flow, statements, and code organization.

Do not change:
- inputs
- outputs
- return values
- exceptions that are part of the original behavior
- externally visible side effects
- package interfaces
- required dependencies
- installation behavior

The resulting program must remain executable.
""",
    },

    {
        "name": "strategy_B",
        "description": """
Apply function decomposition and equivalent
control-flow restructuring.

You may split existing logic into helper functions
or reorganize equivalent execution paths.

Preserve exactly the same observable behavior
and side effects.

Do not introduce new functionality.
Do not remove existing functionality.
Do not change inputs, outputs, return values,
exceptions, package interfaces, or dependencies.
""",
    },

    {
        "name": "strategy_C",
        "description": """
Apply implementation-level refactoring.

Possible transformations include:
- equivalent API usage
- variable renaming
- local implementation restructuring
- equivalent expression transformations
- alternative but semantically equivalent organization

Preserve behavior and side effects exactly.

Do not change:
- public interfaces
- package metadata
- dependencies
- inputs
- outputs
- return values
- externally observable side effects

Only make transformations that remain semantically equivalent.
""",
    },
]