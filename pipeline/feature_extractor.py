"""
DySec feature extraction for Tanzir's 39-feature inference bundle.

IMPORTANT:
- This extractor does NOT fabricate missing features.
- It reads the canonical QUT-DV25 trace directories directly.
- It derives Pattern_1..Pattern_10 from the actual strace stream when no
  separate processed pattern file is present.
- Missing pattern occurrences are represented by "" (empty string), never
  by None or invented defaults.
"""

from __future__ import annotations

import ipaddress
import json
import re
from collections import OrderedDict
from pathlib import Path
from typing import Iterable

import pandas as pd


TRACE_DIRS = {
    "filetop": "QUT-DV25_Filetop_Traces",
    "installation": "QUT-DV25_Installation_Traces",
    "opensnoop": "QUT-DV25_Opensnoop_Traces",
    "tcp": "QUT-DV25_TCP_Traces",
    "pattern": "QUT-DV25_Pattern_Traces",
    "syscall": "QUT-DV25_SystemCall_Traces",
}

SYSCALL_GROUPS = OrderedDict(
    [
        (
            "IO_Operations",
            {
                "ioctl", "poll", "readv", "writev", "lseek", "fcntl",
                "pselect6", "ppoll", "select", "io_uring_enter",
            },
        ),
        (
            "File_Operations",
            {
                "open", "openat", "openat2", "creat", "read", "pread64",
                "write", "pwrite64", "close", "lseek", "fstat", "newfstatat",
                "stat", "statx", "getdents", "getdents64", "readlink",
                "readlinkat", "unlink", "unlinkat", "rename", "renameat",
                "renameat2", "mkdir", "mkdirat", "rmdir", "chmod", "fchmod",
                "truncate", "ftruncate", "fsync", "fdatasync",
            },
        ),
        (
            "Network_Operations",
            {
                "socket", "socketpair", "connect", "accept", "accept4",
                "bind", "listen", "sendto", "sendmsg", "sendmmsg", "recvfrom",
                "recvmsg", "recvmmsg", "getsockname", "getpeername",
                "shutdown", "setsockopt", "getsockopt",
            },
        ),
        (
            "Time_Operations",
            {
                "clock_gettime", "clock_nanosleep", "nanosleep", "time",
                "timer_create", "timer_delete", "timer_settime",
                "timer_gettime", "alarm", "gettimeofday",
            },
        ),
        (
            "Security_Operations",
            {
                "getuid", "geteuid", "setuid", "setreuid", "setresuid",
                "getgid", "getegid", "setgid", "setregid", "setresgid",
                "capget", "capset", "prctl", "seccomp",
            },
        ),
        (
            "Process_Operations",
            {
                "fork", "vfork", "clone", "clone3", "execve", "execveat",
                "wait4", "waitid", "exit", "exit_group", "kill", "tkill",
                "tgkill", "getpid", "getppid",
            },
        ),
    ]
)

PATTERN_DEFS = {
    "Pattern_1": ("newfstatat", "openat", "fstat"),
    "Pattern_2": ("read", "pread64", "lseek"),
    "Pattern_3": ("write", "pwrite64", "fsync"),
    "Pattern_4": ("socket", "bind", "listen"),
    "Pattern_5": ("fork", "execve", "wait4"),
    "Pattern_6": ("mmap", "mprotect", "munmap"),
    "Pattern_7": ("dup", "dup2", "close"),
    "Pattern_8": ("pipe", "write", "read"),
    "Pattern_9": ("fcntl", "lockf", "close"),
    "Pattern_10": ("open", "read"),
}

STRACE_LINE_RE = re.compile(
    r'^\s*(?:(?:\d+:\d+:\d+(?:\.\d+)?)\s+)?'
    r'(?:\[pid\s+\d+\]\s+)?'
    r'([A-Za-z_][A-Za-z0-9_]*)\s*\('
)

ERROR_RE = re.compile(r"=\s*-1\s+([A-Z][A-Z0-9_]+)\b")
ABS_PATH_RE = re.compile(r'(?<![A-Za-z0-9_.-])/(?:[^ \t\r\n"\'<>]|\\ )+')


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _files(root: Path, dirname: str, pattern: str = "*") -> list[Path]:
    d = root / dirname
    if not d.is_dir():
        return []
    return sorted(p for p in d.rglob(pattern) if p.is_file())


def _first_existing(root: Path, dirname: str, names: Iterable[str]) -> Path | None:
    for name in names:
        p = root / dirname / name
        if p.is_file():
            return p
    return None


def _ordered_unique(values: Iterable[str]) -> list[str]:
    seen = set()
    out = []
    for value in values:
        value = str(value).strip()
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _parse_strace_line(line: str) -> tuple[str | None, str | None]:
    m = STRACE_LINE_RE.search(line)
    if not m:
        return None, None
    syscall = m.group(1).lower()
    err = ERROR_RE.search(line)
    return syscall, (err.group(1) if err else None)


def _strace_files(root: Path) -> list[Path]:
    # Only canonical strace_output_* files under Pattern_Traces are accepted.
    return _files(root, TRACE_DIRS["pattern"], "strace_output_*")


def _syscall_events(root: Path) -> tuple[list[str], list[str], int]:
    events: list[str] = []
    errors: list[str] = []
    raw_lines = 0
    for path in _strace_files(root):
        for line in _read(path).splitlines():
            raw_lines += 1
            syscall, err = _parse_strace_line(line)
            if syscall:
                events.append(syscall)
                if err:
                    errors.append(err)
    return events, errors, raw_lines


def _extract_paths(text: str) -> list[str]:
    return [m.group(0).replace("\\ ", " ") for m in ABS_PATH_RE.finditer(text)]


def _opensnoop_features(root: Path) -> dict:
    files = _files(root, TRACE_DIRS["opensnoop"], "*")
    if not files:
        raise ValueError("Missing QUT-DV25_Opensnoop_Traces evidence.")

    counts = {
        "Root_DIR_Access": 0,
        "Temp_DIR_Access": 0,
        "Home_DIR_Access": 0,
        "User_DIR_Access": 0,
        "Sys_DIR_Access": 0,
        "Etc_DIR_Access": 0,
        "Other_DIR_Access": 0,
    }

    for path in files:
        for line in _read(path).splitlines():
            for candidate in _extract_paths(line):
                # Avoid substring errors such as /home appearing inside another path.
                p = candidate.rstrip(",;")
                if p == "/root" or p.startswith("/root/"):
                    counts["Root_DIR_Access"] += 1
                elif p == "/tmp" or p.startswith("/tmp/"):
                    counts["Temp_DIR_Access"] += 1
                elif p == "/home" or p.startswith("/home/"):
                    counts["Home_DIR_Access"] += 1
                elif p == "/usr" or p.startswith("/usr/"):
                    counts["User_DIR_Access"] += 1
                elif p == "/sys" or p.startswith("/sys/"):
                    counts["Sys_DIR_Access"] += 1
                elif p == "/etc" or p.startswith("/etc/"):
                    counts["Etc_DIR_Access"] += 1
                else:
                    counts["Other_DIR_Access"] += 1

    return counts


def _tcp_features(root: Path) -> dict:
    files = _files(root, TRACE_DIRS["tcp"], "*")
    if not files:
        raise ValueError("Missing QUT-DV25_TCP_Traces evidence.")

    local_ips: set[str] = set()
    remote_ips: set[str] = set()
    local_ports: set[str] = set()
    remote_ports: set[str] = set()
    transitions: list[str] = []

    header_idx = None
    for path in files:
        lines = _read(path).splitlines()
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            if stripped.startswith("SKADDR") and "LADDR" in stripped and "RADDR" in stripped:
                cols = stripped.split()
                header_idx = {name: cols.index(name) for name in ("LADDR", "LPORT", "RADDR", "RPORT")
                              if name in cols}
                continue

            if header_idx and all(k in header_idx for k in ("LADDR", "LPORT", "RADDR", "RPORT")):
                cols = stripped.split()
                if len(cols) > max(header_idx.values()):
                    lip = cols[header_idx["LADDR"]]
                    lport = cols[header_idx["LPORT"]]
                    rip = cols[header_idx["RADDR"]]
                    rport = cols[header_idx["RPORT"]]
                    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", lip):
                        local_ips.add(lip)
                    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", rip):
                        remote_ips.add(rip)
                    if lport.isdigit():
                        local_ports.add(lport)
                    if rport.isdigit():
                        remote_ports.add(rport)

                    if "->" in cols:
                        i = cols.index("->")
                        if i > 0 and i + 1 < len(cols):
                            transitions.append(f"{cols[i-1]} {cols[i+1]}")
                continue

            # Compatibility fallback for older/raw TCP output with endpoint pairs.
            endpoints = re.findall(r"(\d+\.\d+\.\d+\.\d+):(\d+)", stripped)
            if len(endpoints) >= 2:
                local_ips.add(endpoints[0][0])
                local_ports.add(endpoints[0][1])
                remote_ips.add(endpoints[1][0])
                remote_ports.add(endpoints[1][1])

            states = re.findall(
                r"\b(SYN_SENT|ESTABLISHED|CLOSE|FIN_WAIT1|FIN_WAIT2|"
                r"LAST_ACK|CLOSE_WAIT|CLOSING|LISTEN|SYN_RECV|TIME_WAIT)\b",
                stripped,
            )
            if len(states) >= 2:
                transitions.append(f"{states[0]} {states[1]}")
            elif states:
                transitions.append(states[0])

    return {
        "Local_IPs_Access": len(local_ips),
        "Remote_IPs_Access": len(remote_ips),
        "Local_Port_Access": len(local_ports),
        "Remote_Port_Access": len(remote_ports),
        "State_Transition": " ".join(_ordered_unique(transitions)),
    }


def _normalise_dep_name(value: str) -> str:
    value = value.strip().strip(";,")
    value = re.split(r"[<>=!~;\[\]]", value, maxsplit=1)[0]
    value = re.sub(r"[-_.]+", "-", value).lower()
    return value


def _installation_features(root: Path, package_name: str) -> dict:
    files = _files(root, TRACE_DIRS["installation"], "*")
    if not files:
        raise ValueError("Missing QUT-DV25_Installation_Traces evidence.")

    text = "\n".join(_read(p) for p in files)
    deps: list[str] = []
    direct: list[str] = []

    # pip's verbose dependency lines distinguish direct dependencies from
    # transitive ones through the "(from A->B)" chain.
    collecting_re = re.compile(
        r"Collecting\s+([A-Za-z0-9][A-Za-z0-9_.-]*(?:\s*[<>=!~].*?)?)"
        r"(?:\s+\(|\s*$)",
        re.I,
    )
    for m in collecting_re.finditer(text):
        name = _normalise_dep_name(m.group(1))
        if name:
            deps.append(name)

    root_norm = _normalise_dep_name(package_name)
    for line in text.splitlines():
        if "Collecting " not in line:
            continue
        m = collecting_re.search(line)
        if not m:
            continue
        name = _normalise_dep_name(m.group(1))
        if not name:
            continue
        if "(from " in line:
            origin = line.split("(from ", 1)[1].split(")", 1)[0]
            chain = [_normalise_dep_name(x) for x in origin.split("->")]
            chain = [x for x in chain if x]
            if root_norm in chain and len(chain) == 1:
                direct.append(name)
            elif root_norm in chain and len(chain) >= 2:
                # e.g. "requests->requeksts"
                if chain[-1] == root_norm and len(chain) == 2:
                    direct.append(name)
        else:
            # A top-level "Collecting X" is usually a direct requirement
            # when pip did not print an origin clause.
            direct.append(name)

    deps = _ordered_unique(deps)
    direct = _ordered_unique(direct)
    indirect = [d for d in deps if d not in set(direct)]

    return {
        "Total_Dependencies": len(deps),
        "Direct_Dependencies": len(direct),
        "Indirect_Dependencies": len(indirect),
        "Total_Dependencies_List": " ".join(deps),
        "Direct_Dependencies_List": " ".join(direct),
        "Indirect_Dependencies_List": " ".join(indirect),
    }


def _filetop_features(root: Path) -> dict:
    files = _files(root, TRACE_DIRS["filetop"], "*")
    if not files:
        raise ValueError("Missing QUT-DV25_Filetop_Traces evidence.")

    read_processes: list[str] = []
    write_processes: list[str] = []
    access_processes: list[str] = []
    read_kb = 0
    write_kb = 0

    # BCC filetop format:
    # TID COMM READS WRITES R_Kb W_Kb T FILE
    row_re = re.compile(
        r"^\s*\d+\s+(\S+)\s+(\d+)\s+(\d+)\s+"
        r"([0-9.]+)\s+([0-9.]+)\s+\S\s+(.+?)\s*$"
    )

    for path in files:
        for line in _read(path).splitlines():
            m = row_re.match(line)
            if not m:
                continue
            comm, reads, writes, rkb, wkb, _file = m.groups()
            reads_i = int(reads)
            writes_i = int(writes)
            if reads_i > 0:
                read_processes.append(comm)
            if writes_i > 0:
                write_processes.append(comm)
            access_processes.append(comm)
            read_kb += int(float(rkb))
            write_kb += int(float(wkb))

    return {
        "Read_Processes": " ".join(_ordered_unique(read_processes)),
        "Write_Processes": " ".join(_ordered_unique(write_processes)),
        "Read_Data_Transfer": str(read_kb),
        "Write_Data_Transfer": str(write_kb),
        "File_Access_Processes": " ".join(_ordered_unique(access_processes)),
    }


def _syscall_features(root: Path, events: list[str]) -> dict:
    if not events:
        raise ValueError("No parseable syscall events found in QUT-DV25 Pattern/SystemCall traces.")

    result = {}
    for column, group in SYSCALL_GROUPS.items():
        result[column] = " ".join(_ordered_unique(e for e in events if e in group))
    return result


def _find_pattern(tokens: list[str], pattern: tuple[str, ...]) -> bool:
    n = len(pattern)
    if n > len(tokens):
        return False
    for i in range(len(tokens) - n + 1):
        if tuple(tokens[i:i+n]) == pattern:
            return True
    return False


def _pattern_features(root: Path, events_by_file: dict[Path, list[str]]) -> dict:
    # Prefer an explicit processed pattern log if one exists, but never invent
    # values. Otherwise derive the ten documented signatures from strace.
    explicit = _files(root, TRACE_DIRS["pattern"], "*.log")
    explicit = [p for p in explicit if not p.name.startswith("strace_output_")]

    result = {name: "" for name in PATTERN_DEFS}

    if explicit:
        text = "\n".join(_read(p).lower() for p in explicit)
        for name, seq in PATTERN_DEFS.items():
            if "->".join(seq) in text or " ".join(seq) in text:
                result[name] = " ".join(seq)
        # Even an explicit pattern file can be empty for individual patterns.
        return result

    for name, seq in PATTERN_DEFS.items():
        for tokens in events_by_file.values():
            if _find_pattern(tokens, seq):
                result[name] = " ".join(seq)
                break

    # Error-sensitive enrichment for Pattern_10.
    if not result["Pattern_10"]:
        for path, tokens in events_by_file.items():
            if "open" in tokens and "read" in tokens:
                text = _read(path)
                if "ENOENT" in text:
                    result["Pattern_10"] = "open read error=ENOENT no-fd"
                    break

    return result


class DySecFeatureExtractor:
    def __init__(self, schema_path: str = "models/rf/Combined_schema.json"):
        self.schema_path = Path(schema_path)
        if not self.schema_path.is_file():
            raise FileNotFoundError(f"Schema not found: {self.schema_path}")

        self.schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        self.numeric_columns = list(self.schema["numeric_columns"])
        self.categorical_columns = list(self.schema["categorical_columns"])
        self.expected_columns = self.numeric_columns + self.categorical_columns

        if len(self.expected_columns) != 39:
            raise ValueError(
                f"Tanzir bundle schema must expose 39 raw features; got "
                f"{len(self.expected_columns)}."
            )

    def extract(self, trace_dir: str, package_name: str) -> pd.DataFrame:
        root = Path(trace_dir)
        if not root.is_dir():
            raise FileNotFoundError(f"Trace directory not found: {root}")

        events, _errors, raw_lines = _syscall_events(root)
        strace_files = _strace_files(root)
        if not strace_files:
            raise ValueError("No canonical strace_output_* files found.")

        events_by_file: dict[Path, list[str]] = {}
        for path in strace_files:
            tokens = []
            for line in _read(path).splitlines():
                syscall, _ = _parse_strace_line(line)
                if syscall:
                    tokens.append(syscall)
            events_by_file[path] = tokens

        features = {"Package_Name": package_name}
        features.update(_opensnoop_features(root))
        features.update(_tcp_features(root))
        features.update(_installation_features(root, package_name))
        features.update(_filetop_features(root))
        features.update(_syscall_features(root, events))
        features.update(_pattern_features(root, events_by_file))

        missing = [c for c in self.expected_columns if c not in features]
        if missing:
            raise ValueError(f"Extractor failed to create features: {missing}")

        # The model bundle expects numeric fields to be numeric and categorical
        # fields to be text. Empty categorical values are intentional absence,
        # not the literal token "None".
        row = {"Package_Name": package_name}
        for col in self.numeric_columns:
            row[col] = float(features[col])
        for col in self.categorical_columns:
            value = features[col]
            row[col] = "" if value is None else str(value)

        df = pd.DataFrame([row], columns=["Package_Name"] + self.expected_columns)
        df.attrs["raw_strace_lines"] = raw_lines
        df.attrs["parsed_syscalls"] = len(events)
        df.attrs["strace_files"] = len(strace_files)
        return df
