from __future__ import annotations

import csv
from pathlib import Path

from config.settings import (
    PACKAGES_DIR,
    OUTPUT_DIR,
)

from pipeline.loop import run_package


def discover_archives() -> list[Path]:

    if not PACKAGES_DIR.exists():
        raise FileNotFoundError(
            f"Packages directory not found: "
            f"{PACKAGES_DIR}"
        )

    return sorted(
        path
        for path in PACKAGES_DIR.rglob(
            "*.tar.gz"
        )
        if path.is_file()
    )


def save_results(
    results: list[dict],
) -> None:

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_file = (
        OUTPUT_DIR
        / "overall_results.csv"
    )

    if not results:
        return

    fieldnames = sorted(
        {
            key
            for result in results
            for key in result.keys()
        }
    )

    with output_file.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        writer.writerows(
            results
        )


def main() -> None:

    archives = discover_archives()

    if not archives:

        raise RuntimeError(
            "No .tar.gz packages found."
        )

    print(
        f"Found {len(archives)} packages."
    )

    results = []

    for index, archive in enumerate(
        archives,
        start=1,
    ):

        package_name = (
            archive.stem
            .removesuffix(".tar")
        )

        print()
        print("=" * 70)
        print(
            f"[{index}/{len(archives)}] "
            f"{package_name}"
        )
        print("=" * 70)

        try:

            result = run_package(
                package_name=package_name,
                archive_path=archive,
            )

            results.append(result)

        except Exception as exc:

            result = {
                "package": package_name,
                "status": "PACKAGE_ERROR",
                "error": str(exc),
            }

            results.append(result)

            print(
                f"ERROR: {exc}"
            )

    save_results(
        results
    )

    print()
    print("=" * 70)
    print("ROBUSTNESS EVALUATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()