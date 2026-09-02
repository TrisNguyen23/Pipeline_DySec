def build_prompt(strategy, source_code):

    return f"""
You are an automated software transformation tool
for academic robustness evaluation.

Transformation strategy:

{strategy["description"]}

Requirements:

1. Preserve the original observable behavior.
2. Preserve required side effects.
3. Do not remove functionality.
4. Do not add unrelated functionality.
5. Return only valid executable Python code.
6. Do not include markdown fences.
7. Do not include explanations.

Source code:

{source_code}
""".strip()