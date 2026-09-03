from __future__ import annotations

import shutil
from pathlib import Path


def copy_package(
    source: Path,
    destination: Path,
) -> Path:

    source = Path(source).resolve()
    destination = Path(
        destination
    ).resolve()

    if not source.exists():
        raise FileNotFoundError(
            f"Source package does not exist: "
            f"{source}"
        )

    if destination.exists():
        shutil.rmtree(destination)

    shutil.copytree(
        source,
        destination,
    )

    return destination