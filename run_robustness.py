from __future__ import annotations

import argparse
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
        for path in PACKAGES_DIR.rglob("*.tar.gz")
        if path.is_file()
    )


def select_archives(
    archives: list[Path],
    package_name: str | None = None,
    limit: int | None = None,
) -> list[Path]:
    selected = archives

    if package_name:
        selected = [
            archive
            for archive in selected
            if archive.name.removesuffix(".tar.gz")
            == package_name
        ]

        if not selected:
            raise RuntimeError(
                f"Package not found: {package_name}"
            )

    if limit is not None:
        if limit <= 0:
            raise ValueError(
                "--limit must be greater than 0."
            )

        selected = selected[:limit]

    return selected


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
            extrasaction="ignore",
        )

        writer.writeheader()
        writer.writerows(results)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run the DySec robustness "
            "evaluation pipeline."
        )
    )

    parser.add_argument(
        "--method",
        choices=[
            "proposed",
            "function_level",
        ],
        default="proposed",
        help=(
            "Mutation strategy used by "
            "the robustness pipeline."
        ),
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Run only the first N discovered "
            "packages."
        ),
    )

    parser.add_argument(
        "--package",
        type=str,
        default=None,
        help=(
            "Run one specific package by archive "
            "basename without .tar.gz."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume after manually recording DySec feedback.",
    )

    args = parser.parse_args()

    archives = discover_archives()

    if not archives:
        raise RuntimeError(
            "No .tar.gz packages found."
        )

    selected_archives = select_archives(
        archives,
        package_name=args.package,
        limit=args.limit,
    )

    if not selected_archives:
        raise RuntimeError(
            "No packages selected."
        )

    print(
        f"Found {len(archives)} packages."
    )

    print(
        f"Selected {len(selected_archives)} package(s)."
    )

    print(
        f"Method: {args.method}"
    )

    if args.package:
        print(
            f"Package filter: {args.package}"
        )

    if args.limit is not None:
        print(
            f"Limit: {args.limit}"
        )

    results = []

    for index, archive in enumerate(
        selected_archives,
        start=1,
    ):
        package_name = (
            archive.name.removesuffix(
                ".tar.gz"
            )
        )

        print()
        print("=" * 70)
        print(
            f"[{index}/{len(selected_archives)}] "
            f"{package_name}"
        )
        print("=" * 70)

        try:
            result = run_package(
                archive_path=archive,
                method=args.method,
                resume=args.resume,
            )

            results.append(result)

            print(
                f"Status: {result.get('status')}"
            )

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
    print(
        "ROBUSTNESS EVALUATION COMPLETE"
    )
    print("=" * 70)


if __name__ == "__main__":
    main()