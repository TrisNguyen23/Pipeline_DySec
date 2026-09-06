from __future__ import annotations

import argparse
import os
import pwd
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent

TRACE_ENGINE_DIR = PROJECT_ROOT / "trace_engine"
DEFAULT_TRACE_OUTPUT = PROJECT_ROOT / "output_data" / "traces"

BPFTRACE_PROBES = {
    "filetop": "filetop.bt",
    "opensnoop": "opensnoop.bt",
    "tcp": "tcp.bt",
    "syscount": "syscount.bt",
    "syscall_sequence": "syscall_sequence.bt",
}

@dataclass
class TraceResult:
    package_dir: str
    trace_dir: str

    install_return_code: Optional[int]
    install_success: bool

    trace_available: bool
    probe_errors: List[str]

    started_at: float
    finished_at: float

    duration_seconds: float

    trace_files: Dict[str, str]

    notes: str = ""

def require_root() -> None:
    """
    bpftrace normally requires root privileges.
    """
    if os.geteuid() != 0:
        raise PermissionError(
            "tracer.py must be run as root because bpftrace requires "
            "privileged access."
        )


def check_command(command: str) -> None:
    """
    Make sure an external command exists.
    """
    if shutil.which(command) is None:
        raise FileNotFoundError(
            f"Required command '{command}' was not found in PATH."
        )


def resolve_sandbox_user(username: str) -> tuple[int, int]:
    """
    Return (uid, gid) for the sandbox user.
    """
    try:
        user = pwd.getpwnam(username)
    except KeyError as exc:
        raise RuntimeError(
            f"Sandbox user '{username}' does not exist."
        ) from exc

    return user.pw_uid, user.pw_gid


def validate_probe_files(probe_dir: Path) -> None:
    """
    Make sure all five .bt probe files exist.
    """
    missing = []

    for filename in BPFTRACE_PROBES.values():
        path = probe_dir / filename

        if not path.is_file():
            missing.append(str(path))

    if missing:
        raise FileNotFoundError(
            "Missing bpftrace probe files:\n"
            + "\n".join(f"  - {path}" for path in missing)
        )


def make_writable_by_user(
    path: Path,
    uid: int,
    gid: int,
) -> None:
    """
    Give the sandbox user ownership of a working directory.
    """
    path.mkdir(parents=True, exist_ok=True)

    for current in [path]:
        os.chown(current, uid, gid)


def set_process_identity(uid: int, gid: int):
    """
    Return a preexec function that drops privileges to the sandbox user.
    """

    def _set_identity():
        os.setgid(gid)
        os.setuid(uid)

        os.environ["HOME"] = pwd.getpwuid(uid).pw_dir
        os.environ["USER"] = pwd.getpwuid(uid).pw_name

        os.environ["PATH"] = (
            "/usr/local/sbin:"
            "/usr/local/bin:"
            "/usr/sbin:"
            "/usr/bin:"
            "/sbin:"
            "/bin"
        )

        os.environ["LANG"] = "C"
        os.environ["LC_ALL"] = "C"

    return _set_identity

class ProbeSet:
    """
    Starts and stops the five DySec/QUT-DV25 bpftrace probes.

    The probes are:

        filetop
        opensnoop
        tcp
        syscount
        syscall_sequence

    Each probe receives sandbox_uid as its argument, matching the
    collaborator's extract_traces.py design.
    """

    def __init__(
        self,
        trace_dir: Path,
        sandbox_uid: int,
        probe_dir: Path,
    ):
        self.trace_dir = trace_dir
        self.sandbox_uid = sandbox_uid
        self.probe_dir = probe_dir

        self.processes: Dict[str, subprocess.Popen] = {}

        self.trace_dir.mkdir(parents=True, exist_ok=True)

    def start(self) -> None:
        """
        Start all five bpftrace probes.
        """

        for name, script_name in BPFTRACE_PROBES.items():
            script_path = self.probe_dir / script_name
            output_path = self.trace_dir / f"{name}.trace"

            output_file = open(
                output_path,
                "w",
                encoding="utf-8",
            )

            command = [
                "bpftrace",
                str(script_path),
                str(self.sandbox_uid),
            ]

            try:
                process = subprocess.Popen(
                    command,
                    stdout=output_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except Exception:
                output_file.close()
                raise

            self.processes[name] = process

        # Give bpftrace time to attach its probes.
        time.sleep(3)

    def stop(self, timeout: int = 12) -> List[str]:
        """
        Stop all probes gracefully.

        SIGINT is important because bpftrace uses it to print map output
        and terminate cleanly.
        """

        errors = []

        for name, process in self.processes.items():

            if process.poll() is not None:
                continue

            try:
                os.killpg(
                    process.pid,
                    signal.SIGINT,
                )
            except ProcessLookupError:
                continue
            except Exception as exc:
                errors.append(
                    f"{name}: failed to send SIGINT: {exc}"
                )

        deadline = time.time() + timeout

        for name, process in self.processes.items():

            remaining = max(
                0.1,
                deadline - time.time(),
            )

            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                errors.append(
                    f"{name}: did not terminate after SIGINT"
                )

                try:
                    os.killpg(
                        process.pid,
                        signal.SIGKILL,
                    )
                except ProcessLookupError:
                    pass

                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    errors.append(
                        f"{name}: failed to terminate"
                    )

        self.processes.clear()

        return errors

class LocalPackageTracer:
    """
    Trace a local Python package using the five DySec bpftrace probes.

    Expected input:

        package_dir/
            setup.py
            package source...

    The package is installed from the local filesystem.

    No PyPI download is performed.
    """

    def __init__(
        self,
        trace_output_dir: Path = DEFAULT_TRACE_OUTPUT,
        probe_dir: Path = TRACE_ENGINE_DIR,
        sandbox_user: str = "dysec",
        post_install_window: int = 120,
        install_timeout: int = 180,
    ):
        self.trace_output_dir = Path(trace_output_dir)
        self.probe_dir = Path(probe_dir)

        self.sandbox_user = sandbox_user
        self.post_install_window = post_install_window
        self.install_timeout = install_timeout

        require_root()

        check_command("bpftrace")
        check_command("python3")

        validate_probe_files(self.probe_dir)

        self.sandbox_uid, self.sandbox_gid = resolve_sandbox_user(
            sandbox_user
        )

    def create_environment(
        self,
        work_dir: Path,
    ) -> Path:
        """
        Create a fresh virtual environment for this trace run.
        """

        env_dir = work_dir / ".trace_env"

        if env_dir.exists():
            shutil.rmtree(env_dir)

        env_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        os.chown(
            env_dir,
            self.sandbox_uid,
            self.sandbox_gid,
        )

        command = [
            "python3",
            "-m",
            "venv",
            str(env_dir),
        ]

        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=set_process_identity(
                self.sandbox_uid,
                self.sandbox_gid,
            ),
            timeout=60,
        )

        if result.returncode != 0:
            raise RuntimeError(
                "Failed to create virtual environment.\n"
                f"{result.stdout}"
            )

        return env_dir

    def install_local_package(
        self,
        package_dir: Path,
        env_dir: Path,
    ) -> subprocess.CompletedProcess:
        """
        Install the package from the local filesystem.

        Important:
        - --no-index prevents package downloads.
        - --no-deps prevents dependency installation.
        - --no-build-isolation prevents pip from trying to create a
          separate build environment requiring packages from the network.

        The package itself is still executed during installation.
        """

        pip_path = env_dir / "bin" / "pip"

        command = [
            str(pip_path),
            "install",
            "--no-input",
            "--no-deps",
            "--no-index",
            "--no-build-isolation",
            str(package_dir),
        ]

        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=set_process_identity(
                self.sandbox_uid,
                self.sandbox_gid,
            ),
            timeout=self.install_timeout,
        )

        return result

    def trace(
        self,
        package_dir: str | Path,
        trace_name: Optional[str] = None,
    ) -> TraceResult:
        """
        Execute one local package installation while collecting traces.

        Example:

            tracer.trace(
                "/home/user/test_package"
            )

        Returns TraceResult.
        """

        package_dir = Path(package_dir).resolve()

        if not package_dir.exists():
            raise FileNotFoundError(
                f"Package directory does not exist: {package_dir}"
            )

        if not package_dir.is_dir():
            raise NotADirectoryError(
                f"Package path is not a directory: {package_dir}"
            )

        if trace_name is None:
            trace_name = package_dir.name

        trace_dir = (
            self.trace_output_dir
            / trace_name
        )

        if trace_dir.exists():
            shutil.rmtree(trace_dir)

        trace_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        os.chown(
            trace_dir,
            self.sandbox_uid,
            self.sandbox_gid,
        )

        work_dir = (
            trace_dir
            / "workspace"
        )

        work_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        os.chown(
            work_dir,
            self.sandbox_uid,
            self.sandbox_gid,
        )

        started_at = time.time()

        probe_set = ProbeSet(
            trace_dir=trace_dir,
            sandbox_uid=self.sandbox_uid,
            probe_dir=self.probe_dir,
        )

        install_return_code = None
        install_success = False
        probe_errors: List[str] = []
        notes = ""

        env_dir = None

        try:
            env_dir = self.create_environment(work_dir)

            venv_python = env_dir / "bin" / "python"

            subprocess.run(
                [
                    str(venv_python),
                    "-m",
                    "ensurepip",
                    "--upgrade",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            print(
                "[Tracer] Starting bpftrace probes..."
            )
            probe_set.start()

            print(
                "[Tracer] Probes attached."
            )

            print(
                f"[Tracer] Installing local package:\n"
                f"          {package_dir}"
            )

            try:
                result = self.install_local_package(
                    package_dir=package_dir,
                    env_dir=env_dir,
                )

                install_return_code = result.returncode
                install_success = (
                    result.returncode == 0
                )

                print(
                    f"[Tracer] pip return code: "
                    f"{result.returncode}"
                )

                if result.stdout:
                    print(
                        "[Tracer] pip output:"
                    )
                    print(result.stdout)

            except subprocess.TimeoutExpired:
                install_return_code = None
                install_success = False

                notes = (
                    "Package installation exceeded "
                    f"{self.install_timeout}s timeout."
                )

                print(
                    "[Tracer] Installation timed out."
                )

            print(
                f"[Tracer] Collecting post-install behaviour "
                f"for {self.post_install_window}s..."
            )

            time.sleep(
                self.post_install_window
            )

        finally:

            print(
                "[Tracer] Stopping bpftrace probes..."
            )

            probe_errors = probe_set.stop()

            print(
                "[Tracer] Tracing finished."
            )

            if env_dir is not None:
                try:
                    shutil.rmtree(
                        env_dir,
                        ignore_errors=True,
                    )
                except Exception:
                    pass

        finished_at = time.time()

        # --------------------------------------------------------------
        # 7. Check generated trace files
        # --------------------------------------------------------------

        trace_files = {}

        for name in BPFTRACE_PROBES:
            path = trace_dir / f"{name}.trace"

            if path.exists():
                trace_files[name] = str(path)

        trace_available = (
            len(trace_files) > 0
        )

        if not trace_available:
            notes = (
                f"{notes} No trace files were produced."
            ).strip()

        elif len(trace_files) < len(BPFTRACE_PROBES):
            missing = (
                set(BPFTRACE_PROBES)
                - set(trace_files)
            )

            notes = (
                f"{notes} Missing trace files: "
                + ", ".join(sorted(missing))
            ).strip()

        return TraceResult(
            package_dir=str(package_dir),
            trace_dir=str(trace_dir),
            install_return_code=install_return_code,
            install_success=install_success,
            trace_available=trace_available,
            probe_errors=probe_errors,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=finished_at - started_at,
            trace_files=trace_files,
            notes=notes,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Trace a local Python package using the "
            "five DySec bpftrace probes."
        )
    )

    parser.add_argument(
        "package_dir",
        help="Path to the local Python package directory.",
    )

    parser.add_argument(
        "--output",
        default=str(DEFAULT_TRACE_OUTPUT),
        help="Directory where traces will be stored.",
    )

    parser.add_argument(
        "--probe-dir",
        default=str(TRACE_ENGINE_DIR),
        help="Directory containing the five .bt probe files.",
    )

    parser.add_argument(
        "--sandbox-user",
        default="dysec",
        help="Linux user used to install/execute the package.",
    )

    parser.add_argument(
        "--window",
        type=int,
        default=120,
        help="Post-install tracing window in seconds.",
    )

    parser.add_argument(
        "--install-timeout",
        type=int,
        default=180,
        help="Maximum package installation time in seconds.",
    )

    parser.add_argument(
        "--trace-name",
        default=None,
        help="Name of the trace output directory.",
    )

    args = parser.parse_args()

    tracer = LocalPackageTracer(
        trace_output_dir=Path(args.output),
        probe_dir=Path(args.probe_dir),
        sandbox_user=args.sandbox_user,
        post_install_window=args.window,
        install_timeout=args.install_timeout,
    )

    result = tracer.trace(
        package_dir=args.package_dir,
        trace_name=args.trace_name,
    )

    print()
    print("=" * 60)
    print("TRACE RESULT")
    print("=" * 60)

    print(
        f"Package:          {result.package_dir}"
    )
    print(
        f"Trace directory:  {result.trace_dir}"
    )
    print(
        f"Install success:  {result.install_success}"
    )
    print(
        f"Install return:   {result.install_return_code}"
    )
    print(
        f"Trace available:  {result.trace_available}"
    )
    print(
        f"Duration:         {result.duration_seconds:.2f}s"
    )

    print()
    print("Trace files:")

    for name, path in result.trace_files.items():
        print(
            f"  {name:20s} {path}"
        )

    if result.probe_errors:
        print()
        print("Probe errors:")

        for error in result.probe_errors:
            print(
                f"  - {error}"
            )

    if result.notes:
        print()
        print(
            f"Notes: {result.notes}"
        )

    print("=" * 60)


if __name__ == "__main__":
    main()