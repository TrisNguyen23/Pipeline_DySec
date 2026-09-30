from __future__ import annotations

import sys
from pathlib import Path

from pipeline.loop import run_package


def main() -> None:
    if len(sys.argv) != 2:
        print(
            "Usage:"
        )
        print(
            "python3 run_demo.py "
            "<package.tar.gz>"
        )
        sys.exit(1)

    archive_path = Path(
        sys.argv[1]
    ).resolve()

    if not archive_path.exists():
        raise FileNotFoundError(
            f"Package archive not found: "
            f"{archive_path}"
        )

    result = run_package(
        archive_path=archive_path,
    )

    print()
    print("=" * 70)
    print("ROBUSTNESS DEMO RESULT")
    print("=" * 70)

    for key, value in result.items():
        print(
            f"{key}: {value}"
        )

    print("=" * 70)


if __name__ == "__main__":
    main()