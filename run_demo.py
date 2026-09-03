from __future__ import annotations

from pathlib import Path

from config.settings import PACKAGES_DIR
from pipeline.loop import run_package


def find_package(package_name: str) -> Path:
    package_dir = PACKAGES_DIR / package_name

    if not package_dir.exists():
        raise FileNotFoundError(
            f"Package not found: {package_dir}"
        )

    if not package_dir.is_dir():
        raise NotADirectoryError(
            f"Package path is not a directory: {package_dir}"
        )

    return package_dir


def load_original_package(package_dir: Path) -> tuple[str, Path]:
    original_dir = package_dir / "original"

    if not original_dir.exists():
        raise FileNotFoundError(
            f"Original directory not found: {original_dir}"
        )

    python_files = sorted(
        path
        for path in original_dir.rglob("*.py")
        if path.is_file()
    )

    if not python_files:
        raise FileNotFoundError(
            f"No Python source files found in {original_dir}"
        )

    entrypoint = original_dir / "main.py"

    if entrypoint.exists():
        selected_file = entrypoint
    elif len(python_files) == 1:
        selected_file = python_files[0]
    else:
        raise RuntimeError(
            "Cannot determine the package entry point. "
            f"Multiple Python files found in {original_dir}."
        )

    source_code = selected_file.read_text(
        encoding="utf-8"
    )

    if not source_code.strip():
        raise ValueError(
            f"Original source is empty: {selected_file}"
        )

    return source_code, selected_file


def print_result(result: dict) -> None:
    print()
    print("=" * 70)
    print("DEMO RESULT")
    print("=" * 70)

    print(f"Package : {result.get('package')}")
    print(f"Strategy: {result.get('strategy')}")
    print(f"Round   : {result.get('round')}")
    print(f"Attempts: {result.get('total_attempts')}")
    print(f"Status  : {result.get('status')}")

    verdict = result.get("dysec_verdict")

    if verdict is not None:
        print(f"DySec   : {verdict}")

    behavior = result.get("behavior_preserved")

    if behavior is not None:
        print(f"Behavior: {behavior}")

    print("=" * 70)


def main() -> None:
    package_name = "package_0001"

    print("=" * 70)
    print("DySec Robustness Evaluation Demo")
    print("=" * 70)
    print(f"Package: {package_name}")

    package_dir = find_package(package_name)

    original_code, original_path = load_original_package(
        package_dir
    )

    print(f"Original: {original_path}")
    print()

    result = run_package(
        package_name=package_name,
        original_code=original_code,
        original_path=original_path,
    )

    print_result(result)


if __name__ == "__main__":
    main()