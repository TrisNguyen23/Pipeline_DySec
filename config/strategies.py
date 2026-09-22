STRATEGIES = [
    {
        "name": "strategy_A",
        "description": """
Apply structural refactoring to the internal Python source code while
preserving all observable behavior and side effects.

Focus ONLY on code organisation and structure, such as:
- reorganising statements or code blocks
- restructuring equivalent function organisation
- simplifying or rearranging internal code layout
- removing redundant structural patterns without changing semantics

Do NOT intentionally change the execution logic or implementation technique.

CRITICAL COMPATIBILITY CONSTRAINTS:
- ONLY modify internal Python source files (.py).
- ABSOLUTELY DO NOT modify, create, delete, or touch:
  setup.py, pyproject.toml, setup.cfg, MANIFEST.in, or any package metadata files.
- DO NOT add, remove, rename, upgrade, downgrade, or replace dependencies.
- Preserve all existing imports and dependency requirements.
- Preserve function signatures, module names, public APIs, inputs, outputs,
  return values, exceptions, and externally observable side effects.
- Do not introduce new functionality or remove existing functionality.
- The resulting source code must be syntactically valid Python.
- The resulting package must remain installable using the original packaging
  configuration.

Only apply transformations that are semantically equivalent to the original.
""",
    },

    {
        "name": "strategy_B",
        "description": """
Apply function decomposition and control-flow restructuring to the internal
Python source code while preserving all observable behavior and side effects.

Focus on transformations such as:
- splitting large functions into equivalent helper functions
- reorganising conditional branches
- restructuring loops while preserving their semantics
- replacing equivalent control-flow patterns
- reorganising execution paths without changing their observable results

CRITICAL COMPATIBILITY CONSTRAINTS:
- ONLY modify internal Python source files (.py).
- ABSOLUTELY DO NOT modify, create, delete, or touch:
  setup.py, pyproject.toml, setup.cfg, MANIFEST.in, or any package metadata files.
- DO NOT add, remove, rename, upgrade, downgrade, or replace dependencies.
- Preserve all existing imports and dependency requirements.
- Keep all function signatures, module names, and public APIs identical.
- Preserve inputs, outputs, return values, exceptions, and externally
  observable side effects.
- Do not introduce new functionality or remove existing functionality.
- The resulting source code must be syntactically valid Python.
- The resulting package must remain installable using the original packaging
  configuration.

Only apply transformations that are semantically equivalent to the original.
""",
    },

    {
        "name": "strategy_C",
        "description": """
Apply implementation-level refactoring to the internal Python source code
while preserving all observable behavior and side effects.

Focus on alternative but semantically equivalent implementations, such as:
- equivalent expression transformations
- local variable and intermediate-value restructuring
- equivalent API usage where the dependency and API contract remain unchanged
- replacing equivalent implementation idioms
- reorganising local computations

Do NOT modify the overall package architecture or public interfaces.

CRITICAL COMPATIBILITY CONSTRAINTS:
- ONLY modify internal Python source files (.py).
- ABSOLUTELY DO NOT modify, create, delete, or touch:
  setup.py, pyproject.toml, setup.cfg, MANIFEST.in, or any package metadata files.
- DO NOT add, remove, rename, upgrade, downgrade, or replace dependencies.
- Preserve all existing imports and dependency requirements.
- Keep all function signatures, module names, and public APIs identical.
- Preserve inputs, outputs, return values, exceptions, and externally
  observable side effects.
- Do not introduce new functionality or remove existing functionality.
- The resulting source code must be syntactically valid Python.
- The resulting package must remain installable using the original packaging
  configuration.

Only apply transformations that are semantically equivalent to the original.
""",
    },
]