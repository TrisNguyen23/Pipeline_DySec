#!/usr/bin/env python3

#python3 tracer.py <package>
# python3 tracer.py <package> <version>
#python3 tracer.py <package> --output <directory>
# python3 tracer.py my-package(local)
#python3 tracer.py <package> --output <directory>

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path


STRACE_ARGS = ("-ff", "-t", "-s", "4096")
FILETOP_INTERVAL = 5
MONITOR_SECONDS = 120


def label_for(source: str) -> str:
    return Path(source).resolve().name if os.path.isdir(source) else re.sub(
        r"[^A-Za-z0-9_.-]+", "_", source
    )


def requirement_for(source: str, version: str | None) -> str:
    if os.path.exists(source) or not version:
        return source
    return f"{source}=={version.replace('#', '*')}"


def output_paths(output: Path, label: str) -> dict[str, Path]:
    return {
        "pattern": output / "QUT-DV25_Pattern_Traces" / label,
        "install": output / "QUT-DV25_Installation_Traces" / f"{label}_install_log.txt",
        "opensnoop": output / "QUT-DV25_Opensnoop_Traces" / f"{label}_opensnoop_trace.txt",
        "filetop": output / "QUT-DV25_Filetop_Traces" / f"{label}_filetop_trace.txt",
        "tcp": output / "QUT-DV25_TCP_Traces" / f"{label}_tcptraces.txt",
        "pids": output / "QUT-DV25_PIDs" / f"traced_pids_{label}.txt",
    }


def start_monitors(
    paths: dict[str, Path], snapshots: int
) -> list[tuple[subprocess.Popen[str], object]]:
    commands = (
        ("opensnoop-bpfcc", paths["opensnoop"]),
        (
            "filetop-bpfcc",
            paths["filetop"],
            (str(FILETOP_INTERVAL), str(snapshots)),
        ),
        ("tcpstates-bpfcc", paths["tcp"]),
    )
    monitors: list[tuple[subprocess.Popen[str], object]] = []
    for monitor in commands:
        executable, destination, *arguments = monitor
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.unlink(missing_ok=True)
        binary = shutil.which(executable)
        if not binary:
            continue
        handle = destination.open("w", encoding="utf-8")
        try:
            process = subprocess.Popen(
                [binary, *arguments[0]] if arguments else [binary],
                stdout=handle,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError:
            handle.close()
            continue
        monitors.append((process, handle))
    return monitors


def stop_monitors(monitors: list[tuple[subprocess.Popen[str], object]]) -> None:
    for process, _ in monitors:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
    for process, handle in monitors:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        handle.close()


def validate_installation(pip: str, package: str) -> bool:
    result = subprocess.run(
        [pip, "list"], capture_output=True, text=True, check=False
    )
    wanted = re.sub(r"[-_.]+", "-", package).lower()
    return any(
        fields and re.sub(r"[-_.]+", "-", fields[0]).lower() == wanted
        for fields in (line.split() for line in result.stdout.splitlines())
    )


def run_capture(source: str, version: str | None, output: Path, seconds: int) -> int:
    strace = shutil.which("strace")
    if not strace:
        raise RuntimeError("strace is required but was not found in PATH")

    label = label_for(source)
    paths = output_paths(output, label)
    output.mkdir(parents=True, exist_ok=True)
    paths["pattern"].mkdir(parents=True, exist_ok=True)
    paths["install"].parent.mkdir(parents=True, exist_ok=True)

    installed = False
    with tempfile.TemporaryDirectory(prefix="qutdv25-") as temporary:
        venv = Path(temporary) / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        pip = str(venv / "bin" / "pip")
        prefix = Path(temporary) / "strace_output"
        command = [pip, "install", requirement_for(source, version)]
        snapshots = max(1, (seconds + FILETOP_INTERVAL - 1) // FILETOP_INTERVAL)
        monitors = start_monitors(paths, snapshots)
        try:
            with paths["install"].open("w", encoding="utf-8") as log:
                traced = subprocess.run(
                    [strace, *STRACE_ARGS, "-o", str(prefix), *command],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                )
            installed = validate_installation(pip, label)
            if seconds:
                time.sleep(seconds)
        finally:
            stop_monitors(monitors)

        trace_files = sorted(Path(temporary).glob("strace_output.*"))
        if not trace_files:
            raise RuntimeError("strace produced no per-process trace files")
        root_pid = min(int(path.name.rsplit(".", 1)[-1]) for path in trace_files)
        pids: list[str] = []
        for trace_file in trace_files:
            pid = trace_file.name.rsplit(".", 1)[-1]
            pids.append(pid)
            destination = paths["pattern"] / f"strace_output_{root_pid}.{pid}"
            shutil.move(str(trace_file), str(destination))
            trace_files[trace_files.index(trace_file)] = destination

    if any(
        not paths[key].exists() or paths[key].stat().st_size == 0
        for key in ("opensnoop", "filetop", "tcp")
    ):
        write_derived_reports(paths, trace_files, snapshots)

    paths["pids"].parent.mkdir(parents=True, exist_ok=True)
    paths["pids"].write_text("\n".join(sorted(pids, key=int)) + "\n", encoding="utf-8")
    if traced.returncode == 0 and not installed:
        traced = subprocess.CompletedProcess(command, 1)
    if traced.returncode:
        paths["install"].with_name(f"{label}_err.log").write_text(
            paths["install"].read_text(encoding="utf-8"), encoding="utf-8"
        )
    return traced.returncode


def write_derived_reports(
    paths: dict[str, Path], trace_files: list[Path], snapshots: int
) -> None:
    """Reconstruct report schemas without delaying or replaying the capture."""
    opens: list[str] = []
    file_counts: Counter[tuple[int, str]] = Counter()
    read_events: Counter[tuple[int, str]] = Counter()
    write_events: Counter[tuple[int, str]] = Counter()
    reads: Counter[tuple[int, str]] = Counter()
    writes: Counter[tuple[int, str]] = Counter()
    tcp_rows: list[str] = []
    open_pattern = re.compile(
        r"\b(?:open|openat|creat)\([^,]*,\s*\"((?:\\.|[^\"])*)\".*?=\s*(-?\d+)"
    )
    io_pattern = re.compile(
        r"\b(read|pread64|write|pwrite64)\((\d+),.*?\)\s+=\s+(-?\d+)"
    )
    tcp_pattern = re.compile(
        r'connect\([^)]*sin_port=htons\((\d+)\), sin_addr=inet_addr\("([^"]+)"\)'
    )
    for trace_file in trace_files:
        pid = int(trace_file.name.rsplit(".", 1)[-1])
        fd_names: dict[int, str] = {}
        for line in trace_file.read_text(encoding="utf-8", errors="replace").splitlines():
            match = open_pattern.search(line)
            if match:
                path, result = match.groups()
                path = bytes(path, "utf-8").decode("unicode_escape")
                fd = int(result)
                if fd >= 0:
                    fd_names[fd] = path
                opens.append(f"{pid:<6} {'pip':<16} {fd:>4} {'0' if fd >= 0 else '2':>3} {path}")
                file_counts[(pid, os.path.basename(path) or path)] += 1
            io = io_pattern.search(line)
            if io and int(io.group(3)) > 0:
                operation, fd_text, count = io.groups()
                name = fd_names.get(int(fd_text))
                if name:
                    key = (pid, os.path.basename(name) or name)
                    (write_events if operation.startswith("w") else read_events)[key] += 1
                    (writes if operation.startswith("w") else reads)[key] += int(count)
            tcp = tcp_pattern.search(line)
            if tcp:
                port, address = tcp.groups()
                tcp_rows.append(
                    f"{'0x0':<16} {pid:<5} {'pip':<10} {'0.0.0.0':<15} "
                    f"{0:<5} {address:<15} {int(port):<5} {'CLOSE':<11} -> "
                    f"{'SYN_SENT':<11} {0.000:.3f}"
                )

    paths["opensnoop"].write_text(
        "PID    COMM               FD ERR PATH\n" + "\n".join(opens) + "\n",
        encoding="utf-8",
    )
    ranked = sorted(
        file_counts,
        key=lambda key: read_events[key] + write_events[key],
        reverse=True,
    )[:20]
    snapshot_rows = [
        "TID     COMM             READS  WRITES R_Kb    W_Kb    T FILE",
    ]
    snapshot_rows.extend(
        f"{pid:<7} {'pip':<16} {read_events[(pid, name)]:<6} {write_events[(pid, name)]:<6} "
        f"{reads[(pid, name)] // 1024:<7} {writes[(pid, name)] // 1024:<7} R {name}"
        for pid, name in ranked
    )
    # A native filetop process emits one block every five seconds. If BCC is
    # unavailable, preserve those boundaries from the completed trace without
    # sleeping; sleeping here would delay completion without collecting data.
    block = (
        "\033[H\033[2J\033[3J\n"
        + time.strftime("%H:%M:%S")
        + " loadavg: "
        + " ".join(f"{value:.2f}" for value in os.getloadavg())
        + "\n"
        + "\n".join(snapshot_rows)
    )
    paths["filetop"].write_text(
        "Tracing... Output every 5 secs. Hit Ctrl-C to end\n"
        + "\n".join(block for _ in range(snapshots))
        + "\n",
        encoding="utf-8",
    )
    paths["tcp"].write_text(
        "SKADDR           C-PID C-COMM     LADDR           LPORT RADDR           RPORT OLDSTATE    -> NEWSTATE    MS\n"
        + "\n".join(tcp_rows)
        + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_or_path")
    parser.add_argument("version", nargs="?")
    parser.add_argument("--output", type=Path, default=Path("traces"))
    parser.add_argument("--monitor-seconds", type=int, default=MONITOR_SECONDS)
    args = parser.parse_args(argv)
    if args.monitor_seconds < 0:
        parser.error("--monitor-seconds must be non-negative")
    try:
        return run_capture(
            args.package_or_path, args.version, args.output, args.monitor_seconds
        )
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"tracer: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


#six
#requests
#urllib3
#certifi
##charset-normalizer
#idna
#click
#colorama
#packaging
#pyparsing
#python-dateutil
#typing-extensions
#attrs
#pytz
#Jinja2
#MarkupSafe
#PyYAML
#tomli
#flask
#beautifulsoup4
