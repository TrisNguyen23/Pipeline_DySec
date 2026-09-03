from __future__ import annotations

import json
from pathlib import Path


def save_json(
    path: Path,
    data: dict,
) -> None:
    """
    Save structured experiment data as JSON.
    """

    path = Path(path)

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False,
        )


def save_text(
    path: Path,
    text: str,
) -> None:
    """
    Save text data as UTF-8.
    """

    path = Path(path)

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        text,
        encoding="utf-8",
    )