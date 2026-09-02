from pathlib import Path
import csv

from config.settings import PACKAGES_DIR, OUTPUT_DIR
from pipeline.loop import run_package


def discover_packages():
    """
    Discover all package directories under packages/.
    """

    if not PACKAGES_DIR.exists():
        raise FileNotFoundError(
            f"Packages directory not found: {PACKAGES_DIR}"
        )

    return sorted(
        path
        for path in PACKAGES_DIR.iterdir()
        if path.is_dir()
    )


def load_original_code(package_dir):
    """
    Load the original Python code for a package.

    For the initial simulation, the package is expected
    to contain original/main.py.
    """

    original_dir = package_dir / "original"

    if not original_dir.exists():
        raise FileNotFoundError(
            f"Original directory not found: {original_dir}"
        )

    main_file = original_dir / "main.py"

    if not main_file.exists():
        raise FileNotFoundError(
            f"Original main.py not found: {main_file}"
        )

    return main_file.read_text(
        encoding="utf-8"
    )


def save_overall_results(results):
    """
    Save one summary row per package.
    """

    output_file = (
        OUTPUT_DIR / "overall_results.csv"
    )

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True
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

    with open(
        output_file,
        "w",
        newline="",
        encoding="utf-8"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames
        )

        writer.writeheader()
        writer.writerows(results)

    print(
        f"\n[+] Overall results saved to:"
        f"\n    {output_file}"
    )


def print_final_statistics(results):
    """
    Print simple experiment statistics.
    """

    total = len(results)

    successful = sum(
        result.get("status")
        == "SUCCESSFUL_EVASION"
        for result in results
    )

    exhausted = sum(
        result.get("status")
        == "ALL_STRATEGIES_EXHAUSTED"
        for result in results
    )

    errors = sum(
        result.get("status")
        in {
            "PACKAGE_ERROR",
            "GENERATION_ERROR",
            "EXECUTION_ERROR",
        }
        for result in results
    )

    print()
    print("=" * 65)
    print("             EXPERIMENT SUMMARY")
    print("=" * 65)

    print(f"Total packages      : {total:,}")
    print(f"Successful evasions : {successful:,}")
    print(f"All strategies fail : {exhausted:,}")
    print(f"Errors              : {errors:,}")

    if total > 0:

        evasion_rate = (
            successful / total * 100
        )

        print(
            f"Evasion rate        : "
            f"{evasion_rate:.2f}%"
        )

    print("=" * 65)


def main():

    print("=" * 65)
    print("      DYSEC AUTOMATED ROBUSTNESS EVALUATION")
    print("=" * 65)

    packages = discover_packages()

    print(
        f"\n[+] Packages discovered: "
        f"{len(packages):,}"
    )

    if not packages:
        print(
            "[-] No packages found."
        )
        return

    results = []

    for index, package_dir in enumerate(
        packages,
        start=1
    ):

        package_name = package_dir.name

        print()
        print("#" * 65)
        print(
            f"[PACKAGE {index}/{len(packages)}] "
            f"{package_name}"
        )
        print("#" * 65)

        try:
            original_code = load_original_code(
                package_dir
            )
            result = run_package(
                package_name=package_name,
                original_code=original_code,
            )

            results.append(result)

        except Exception as exc:

            print(
                f"[-] Package failed: {exc}"
            )

            result = {
                "package": package_name,
                "status": "PACKAGE_ERROR",
                "error": str(exc),
            }

            results.append(result)
    save_overall_results(
        results
    )
    print_final_statistics(
        results
    )
if __name__ == "__main__":
    main()