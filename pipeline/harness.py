from __future__ import annotations

from pathlib import Path


def save_generated_code(
    generated_dir: Path,
    code: str,
    filename: str = "generated.py",
) -> Path:
    """
    Save generated source code to disk.
    """

    if not code or not code.strip():
        raise ValueError(
            "Cannot save empty generated code."
        )

    generated_dir = Path(
        generated_dir
    )

    generated_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    target_file = (
        generated_dir / filename
    )

    target_file.write_text(
        code,
        encoding="utf-8",
    )

    return target_file