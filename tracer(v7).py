#!/usr/bin/env python3

"""
QUT-DV25-compatible dynamic tracer using strace.

Usage:
    python3 tracer.py <package>
    python3 tracer.py <package> <version>
    python3 tracer.py <local-package>
    python3 tracer.py <package> --output <directory>
    python3 tracer.py <package> --monitor-seconds 120
"""

from __future__ import annotations

import argparse
from collections import Counter
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STRACE_ARGS = (
    "-ff",
    "-t",
    "-s",
    "4096",
)

MONITOR_SECONDS = 120


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def normalize_package_name(name: str) -> str:
    """
    Normalise Python package names according to common distribution rules.
    """
    return re.sub(r"[-_.]+", "-", name).lower()


def label_for(source: str) -> str:
    """
    Generate a filesystem-safe label for the package.
    """
    if os.path.isdir(source):
        name = Path(source).resolve().name
    else:
        name = source

    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def requirement_for(source: str, version: str | None) -> str:
    """
    Build the pip requirement.

    Examples:
        requests + 2.32.5
            -> requests==2.32.5

        requests
            -> requests

        ./package
            -> ./package
    """
    if os.path.exists(source) or not version:
        return source

    return f"{source}=={version}"


def output_paths(output: Path, label: str) -> dict[str, Path]:
    """
    Preserve the QUT-DV25-style output directory structure.
    """
    return {
        "pattern": (
            output
            / "QUT-DV25_Pattern_Traces"
            / label
        ),
        "install": (
            output
            / "QUT-DV25_Installation_Traces"
            / f"{label}_install_log.txt"
        ),
        "opensnoop": (
            output
            / "QUT-DV25_Opensnoop_Traces"
            / f"{label}_opensnoop_trace.txt"
        ),
        "filetop": (
            output
            / "QUT-DV25_Filetop_Traces"
            / f"{label}_filetop_trace.txt"
        ),
        "tcp": (
            output
            / "QUT-DV25_TCP_Traces"
            / f"{label}_tcptraces.txt"
        ),
        "pids": (
            output
            / "QUT-DV25_PIDs"
            / f"traced_pids_{label}.txt"
        ),
        "syscalls": (
            output
            / "QUT-DV25_Pattern_Traces"
            / label
            / "syscall_sequence.txt"
        ),
    }


# ---------------------------------------------------------------------------
# Package validation
# ---------------------------------------------------------------------------

def package_name_from_source(source: str) -> str:
    """
    Best-effort extraction of the package/distribution name.

    For a PyPI requirement:
        requests -> requests

    For a local directory:
        /tmp/foo-1.0.0 -> foo-1.0.0

    Validation is still performed using pip show/list.
    """
    if os.path.isdir(source):
        return Path(source).resolve().name

    return source


def validate_installation(
    pip: str,
    source: str,
    version: str | None = None,
) -> bool:
    """
    Verify that the requested package is installed in the temporary venv.

    Uses `pip list` and normalises distribution names.

    This is intentionally more tolerant than comparing against a generated
    label such as "requeksts-1.0.0".
    """
    result = subprocess.run(
        [pip, "list", "--format=freeze"],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        return False

    requested = source

    # For a local directory, try package metadata using pip show after
    # installation. The directory name may contain a version suffix.
    if os.path.isdir(source):
        requested = Path(source).resolve().name

        # Strip common version suffixes.
        requested = re.sub(
            r"[-_.]v?\d+(?:[-_.]\d+)*$",
            "",
            requested,
            flags=re.IGNORECASE,
        )

    # For normal package + explicit version.
    if version and not os.path.exists(source):
        requested = source

    requested = normalize_package_name(requested)

    for line in result.stdout.splitlines():
        if "==" not in line:
            continue

        installed_name = line.split("==", 1)[0].strip()

        if normalize_package_name(installed_name) == requested:
            return True

    # Fallback: pip show.
    result = subprocess.run(
        [pip, "show", requested],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    return result.returncode == 0


# ---------------------------------------------------------------------------
# strace parsing
# ---------------------------------------------------------------------------

SYSCALL_PATTERN = re.compile(
    r"^\s*(?:\d{2}:\d{2}:\d{2}\s+)?"
    r"([a-zA-Z_][a-zA-Z0-9_]*)"
    r"\("
)

OPEN_PATTERN = re.compile(
    r"""
    \b
    (?:open|openat|openat2|creat)
    \(
    .*?
    ["']
    (?P<path>
        (?:\\.|[^"'])*
    )
    ["']
    .*?
    \)
    \s*=\s*
    (?P<result>-?\d+)
    """,
    re.VERBOSE,
)

CONNECT_PATTERN = re.compile(
    r"""
    \bconnect
    \(
    .*?
    sin_port=htons\((?P<port>\d+)\)
    .*?
    (?:inet_addr|inet_pton)\(
    ["'](?P<address>[^"']+)["']
    """,
    re.VERBOSE,
)

IO_PATTERN = re.compile(
    r"""
    \b
    (?P<operation>
        read|
        pread64|
        preadv|
        readv|
        write|
        pwrite64|
        pwritev|
        writev
    )
    \(
    (?P<fd>\d+)
    .*?
    \)
    \s*=\s*
    (?P<count>-?\d+)
    """,
    re.VERBOSE,
)


def extract_syscall_name(line: str) -> str | None:
    """
    Extract syscall name from one strace line.
    """
    match = SYSCALL_PATTERN.search(line)

    if not match:
        return None

    return match.group(1)


# ---------------------------------------------------------------------------
# Derived QUT-DV25-style reports
# ---------------------------------------------------------------------------

def write_derived_reports(
    paths: dict[str, Path],
    trace_files: list[Path],
) -> None:
    """
    Reconstruct QUT-DV25-style reports from raw strace output.

    Important:
        These reports are derived from strace. They are not claiming to be
        native BCC output.
    """

    opens: list[str] = []
    tcp_rows: list[str] = []

    file_counts: Counter[tuple[int, str]] = Counter()
    read_events: Counter[tuple[int, str]] = Counter()
    write_events: Counter[tuple[int, str]] = Counter()
    reads: Counter[tuple[int, str]] = Counter()
    writes: Counter[tuple[int, str]] = Counter()

    syscall_sequence: list[str] = []

    for trace_file in sorted(
        trace_files,
        key=lambda p: int(p.name.rsplit(".", 1)[-1]),
    ):
        try:
            pid = int(trace_file.name.rsplit(".", 1)[-1])
        except ValueError:
            continue

        fd_names: dict[int, str] = {}

        try:
            lines = trace_file.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
        except OSError:
            continue

        for line in lines:
            # ---------------------------------------------------------------
            # Syscall sequence
            # ---------------------------------------------------------------

            syscall = extract_syscall_name(line)

            if syscall:
                syscall_sequence.append(syscall)

            # ---------------------------------------------------------------
            # File open activity
            # ---------------------------------------------------------------

            match = OPEN_PATTERN.search(line)

            if match:
                path = match.group("path")
                result = int(match.group("result"))

                # Decode common strace escaping.
                try:
                    path = bytes(
                        path,
                        "utf-8",
                    ).decode(
                        "unicode_escape",
                        errors="replace",
                    )
                except UnicodeDecodeError:
                    pass

                if result >= 0:
                    fd_names[result] = path

                error_code = "0" if result >= 0 else "2"

                opens.append(
                    f"{pid:<6} "
                    f"{'pip':<16} "
                    f"{result:>4} "
                    f"{error_code:>3} "
                    f"{path}"
                )

                basename = os.path.basename(path) or path
                file_counts[(pid, basename)] += 1

            # ---------------------------------------------------------------
            # File I/O
            # ---------------------------------------------------------------

            io_match = IO_PATTERN.search(line)

            if io_match:
                operation = io_match.group("operation")
                fd = int(io_match.group("fd"))
                count = int(io_match.group("count"))

                if count > 0:
                    name = fd_names.get(fd)

                    if name:
                        basename = os.path.basename(name) or name
                        key = (pid, basename)

                        if operation.startswith("w"):
                            write_events[key] += 1
                            writes[key] += count
                        else:
                            read_events[key] += 1
                            reads[key] += count

            # ---------------------------------------------------------------
            # Network connect activity
            # ---------------------------------------------------------------

            tcp_match = CONNECT_PATTERN.search(line)

            if tcp_match:
                port = int(tcp_match.group("port"))
                address = tcp_match.group("address")

                tcp_rows.append(
                    f"{'0x0':<16} "
                    f"{pid:<5} "
                    f"{'pip':<10} "
                    f"{'0.0.0.0':<15} "
                    f"{0:<5} "
                    f"{address:<15} "
                    f"{port:<5} "
                    f"{'CLOSE':<11} -> "
                    f"{'SYN_SENT':<11} "
                    f"{0.000:.3f}"
                )

    # -----------------------------------------------------------------------
    # opensnoop-style report
    # -----------------------------------------------------------------------

    paths["opensnoop"].parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    paths["opensnoop"].write_text(
        "PID    COMM               FD ERR PATH\n"
        + "\n".join(opens)
        + "\n",
        encoding="utf-8",
    )

    # -----------------------------------------------------------------------
    # filetop-style report
    # -----------------------------------------------------------------------

    ranked = sorted(
        file_counts,
        key=lambda key: (
            read_events[key] + write_events[key]
        ),
        reverse=True,
    )[:20]

    snapshot_rows = [
        "TID     COMM             READS  WRITES R_Kb    W_Kb    T FILE",
    ]

    for pid, name in ranked:
        snapshot_rows.append(
            f"{pid:<7} "
            f"{'pip':<16} "
            f"{read_events[(pid, name)]:<6} "
            f"{write_events[(pid, name)]:<6} "
            f"{reads[(pid, name)] // 1024:<7} "
            f"{writes[(pid, name)] // 1024:<7} "
            f"R {name}"
        )

    block = (
        "\033[H\033[2J\033[3J\n"
        + time.strftime("%H:%M:%S")
        + "\n"
        + "\n".join(snapshot_rows)
    )

    paths["filetop"].parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    paths["filetop"].write_text(
        "Tracing... Output every 5 secs. Hit Ctrl-C to end\n"
        + block
        + "\n",
        encoding="utf-8",
    )

    # -----------------------------------------------------------------------
    # TCP-style report
    # -----------------------------------------------------------------------

    paths["tcp"].parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    paths["tcp"].write_text(
        "SKADDR          C-PID C-COMM     "
        "LADDR           LPORT RADDR           RPORT "
        "OLDSTATE    -> NEWSTATE    MS\n"
        + "\n".join(tcp_rows)
        + "\n",
        encoding="utf-8",
    )

    # -----------------------------------------------------------------------
    # Syscall sequence
    # -----------------------------------------------------------------------

    paths["syscalls"].parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    paths["syscalls"].write_text(
        "\n".join(syscall_sequence) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Main capture
# ---------------------------------------------------------------------------

def run_capture(
    source: str,
    version: str | None,
    output: Path,
    seconds: int,
) -> int:

    # -----------------------------------------------------------------------
    # Check strace
    # -----------------------------------------------------------------------

    strace = shutil.which("strace")

    if not strace:
        raise RuntimeError(
            "strace is required but was not found in PATH"
        )

    # -----------------------------------------------------------------------
    # Paths
    # -----------------------------------------------------------------------

    label = label_for(source)
    paths = output_paths(output, label)

    output.mkdir(
        parents=True,
        exist_ok=True,
    )

    paths["pattern"].mkdir(
        parents=True,
        exist_ok=True,
    )

    paths["install"].parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # -----------------------------------------------------------------------
    # Temporary isolated environment
    # -----------------------------------------------------------------------

    traced: subprocess.CompletedProcess[str] | None = None
    installed = False
    trace_files: list[Path] = []
    pids: list[str] = []

    with tempfile.TemporaryDirectory(
        prefix="qutdv25-"
    ) as temporary:

        temporary_path = Path(temporary)

        venv = temporary_path / "venv"

        # Create virtual environment.
        subprocess.run(
            [
                sys.executable,
                "-m",
                "venv",
                str(venv),
            ],
            check=True,
        )

        pip = str(venv / "bin" / "pip")

        python = str(venv / "bin" / "python")

        # -------------------------------------------------------------------
        # Upgrade pip/setuptools/wheel before installation
        #
        # This is intentionally NOT traced. The actual package installation
        # below is what we want to capture.
        # -------------------------------------------------------------------

        bootstrap_command = [
            pip,
            "install",
            "--upgrade",
            "pip",
            "setuptools",
            "wheel",
        ]

        bootstrap_log = paths["install"].with_name(
            f"{label}_bootstrap_log.txt"
        )

        with bootstrap_log.open(
            "w",
            encoding="utf-8",
        ) as log:

            bootstrap = subprocess.run(
                bootstrap_command,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )

        if bootstrap.returncode != 0:
            print(
                f"tracer: failed to bootstrap pip/setuptools/wheel; "
                f"see {bootstrap_log}",
                file=sys.stderr,
            )

            return bootstrap.returncode

        # -------------------------------------------------------------------
        # Actual package installation
        #
        # IMPORTANT:
        #   No --no-index
        #   No --no-deps
        #   No --no-build-isolation
        #
        # Therefore pip may retrieve:
        #   setuptools
        #   wheel
        #   build dependencies
        #   runtime dependencies
        #   package itself
        # -------------------------------------------------------------------

        requirement = requirement_for(
            source,
            version,
        )

        command = [
            pip,
            "install",
            requirement,
        ]

        prefix = temporary_path / "strace_output"

        try:
            with paths["install"].open(
                "w",
                encoding="utf-8",
            ) as log:

                log.write(
                    "QUT-DV25 strace installation capture\n"
                )
                log.write(
                    f"Package: {requirement}\n"
                )
                log.write(
                    f"Python: {python}\n"
                )
                log.write(
                    f"pip: {pip}\n"
                )
                log.write(
                    "Internet/build dependencies: ENABLED\n"
                )
                log.write(
                    "strace: ENABLED\n"
                )
                log.write(
                    "\n"
                )

                log.flush()

                traced = subprocess.run(
                    [
                        strace,
                        *STRACE_ARGS,
                        "-o",
                        str(prefix),
                        *command,
                    ],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                )

            # ---------------------------------------------------------------
            # Validate package installation
            # ---------------------------------------------------------------

            installed = validate_installation(
                pip,
                source,
                version,
            )

            # ---------------------------------------------------------------
            # Keep observation window
            #
            # Note:
            # The pip process has already finished. strace therefore captures
            # installation behaviour rather than an additional execution
            # workload during this sleep.
            # ---------------------------------------------------------------

            if seconds:
                time.sleep(seconds)

        finally:
            # Nothing external needs to be stopped because strace itself
            # terminates with the traced command.
            pass

        # -------------------------------------------------------------------
        # Locate all strace -ff output files
        # -------------------------------------------------------------------

        trace_files = sorted(
            temporary_path.glob("strace_output.*"),
            key=lambda path: int(
                path.name.rsplit(".", 1)[-1]
            ),
        )

        if not trace_files:
            raise RuntimeError(
                "strace produced no per-process trace files"
            )

        # -------------------------------------------------------------------
        # Determine root PID
        # -------------------------------------------------------------------

        try:
            root_pid = min(
                int(
                    path.name.rsplit(".", 1)[-1]
                )
                for path in trace_files
            )
        except ValueError as exc:
            raise RuntimeError(
                "unable to determine root PID from strace output"
            ) from exc

        # -------------------------------------------------------------------
        # Move trace files to permanent output
        # -------------------------------------------------------------------

        permanent_trace_files: list[Path] = []

        for trace_file in trace_files:

            pid = trace_file.name.rsplit(
                ".",
                1,
            )[-1]

            pids.append(pid)

            destination = (
                paths["pattern"]
                / f"strace_output_{root_pid}.{pid}"
            )

            shutil.move(
                str(trace_file),
                str(destination),
            )

            permanent_trace_files.append(
                destination
            )

        trace_files = permanent_trace_files

    # -----------------------------------------------------------------------
    # Generate derived reports
    # -----------------------------------------------------------------------

    write_derived_reports(
        paths,
        trace_files,
    )

    # -----------------------------------------------------------------------
    # Save PID list
    # -----------------------------------------------------------------------

    paths["pids"].parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    paths["pids"].write_text(
        "\n".join(
            sorted(
                pids,
                key=int,
            )
        )
        + "\n",
        encoding="utf-8",
    )

    # -----------------------------------------------------------------------
    # Installation result
    # -----------------------------------------------------------------------

    if traced is None:
        raise RuntimeError(
            "installation command did not execute"
        )

    final_returncode = traced.returncode

    # pip may return 0 while validation fails.
    if final_returncode == 0 and not installed:
        final_returncode = 1

        with paths["install"].open(
            "a",
            encoding="utf-8",
        ) as log:
            log.write(
                "\n"
                "WARNING: pip returned success, but package "
                "validation failed.\n"
            )

    # -----------------------------------------------------------------------
    # Human-readable status
    # -----------------------------------------------------------------------

    status_file = paths["pattern"] / "capture_status.txt"

    status_lines = [
        f"package={requirement_for(source, version)}",
        f"label={label}",
        f"pip_returncode={traced.returncode}",
        f"installation_validated={installed}",
        f"trace_available={bool(trace_files)}",
        f"trace_process_count={len(trace_files)}",
        f"monitor_seconds={seconds}",
    ]

    if traced.returncode == 0 and installed:
        status_lines.append("installation_status=SUCCESS")
    else:
        status_lines.append("installation_status=FAILED")

    status_file.write_text(
        "\n".join(status_lines) + "\n",
        encoding="utf-8",
    )

    # -----------------------------------------------------------------------
    # Error copy
    # -----------------------------------------------------------------------

    if final_returncode != 0:
        error_log = paths["install"].with_name(
            f"{label}_err.log"
        )

        error_log.write_text(
            paths["install"].read_text(
                encoding="utf-8",
                errors="replace",
            ),
            encoding="utf-8",
        )

    return final_returncode


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(
    argv: list[str] | None = None,
) -> int:

    parser = argparse.ArgumentParser(
        description=__doc__,
    )

    parser.add_argument(
        "package_or_path",
        help="PyPI package name or local package path",
    )

    parser.add_argument(
        "version",
        nargs="?",
        help="Optional package version",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path("traces"),
        help="Output directory",
    )

    parser.add_argument(
        "--monitor-seconds",
        type=int,
        default=MONITOR_SECONDS,
        help="Observation delay after installation",
    )

    args = parser.parse_args(argv)

    if args.monitor_seconds < 0:
        parser.error(
            "--monitor-seconds must be non-negative"
        )

    try:
        return run_capture(
            args.package_or_path,
            args.version,
            args.output,
            args.monitor_seconds,
        )

    except (
        OSError,
        RuntimeError,
        subprocess.CalledProcessError,
    ) as exc:

        print(
            f"tracer: {exc}",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())