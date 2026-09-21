"""
DySec Feature Extractor
Extracts 39 raw features (14 numeric + 25 categorical) from raw eBPF and runtime traces.
Compatible with Tanzir's Combined_schema.json and offline inference pipeline.
"""

import os
import re
import json
from typing import Dict, Any, Optional
import pandas as pd


class DySecFeatureExtractor:
    def __init__(self, schema_path: str = "models/rf/Combined_schema.json"):
        """
        Initializes the extractor with the expected feature schema.
        """
        self.schema_path = schema_path
        if os.path.exists(schema_path):
            with open(schema_path, "r", encoding="utf-8") as f:
                self.schema = json.load(f)
            self.numeric_columns = self.schema.get("numeric_columns", [])
            self.categorical_columns = self.schema.get("categorical_columns", [])
        else:
            self.schema = {}
            self.numeric_columns = []
            self.categorical_columns = []

    def extract(self, trace_dir: str, package_name: str = "sample_pkg") -> pd.DataFrame:
        """
        Parses raw trace log files from the trace directory and outputs a single-row DataFrame
        containing all 39 features defined in Combined_schema.json.

        Parameters:
            trace_dir (str): Directory where raw trace logs are located.
            package_name (str): The name/prefix identifier of the package.

        Returns:
            pd.DataFrame: A DataFrame with shape (1, 40) including Package_Name and 39 features.
        """
        features: Dict[str, Any] = {"Package_Name": package_name}

        # ---------------------------------------------------------------------
        # 1. OPENSNOOP TRACES (7 Numeric Directory Access Features)
        # ---------------------------------------------------------------------
        opensnoop_log = os.path.join(trace_dir, f"{package_name}_opens.log")
        root_cnt, temp_cnt, home_cnt, usr_cnt, sys_cnt, etc_cnt, other_cnt = 0, 0, 0, 0, 0, 0, 0

        if os.path.exists(opensnoop_log):
            with open(opensnoop_log, "r", errors="ignore") as f:
                for line in f:
                    if "/root" in line:
                        root_cnt += 1
                    elif "/tmp" in line:
                        temp_cnt += 1
                    elif "/home" in line:
                        home_cnt += 1
                    elif "/usr" in line:
                        usr_cnt += 1
                    elif "/sys" in line:
                        sys_cnt += 1
                    elif "/etc" in line:
                        etc_cnt += 1
                    elif any(path in line for path in ["/proc", "/dev", "/var", "/opt"]):
                        other_cnt += 1

        features["Root_DIR_Access"] = root_cnt
        features["Temp_DIR_Access"] = temp_cnt
        features["Home_DIR_Access"] = home_cnt
        features["User_DIR_Access"] = usr_cnt
        features["Sys_DIR_Access"] = sys_cnt
        features["Etc_DIR_Access"] = etc_cnt
        features["Other_DIR_Access"] = other_cnt

        # ---------------------------------------------------------------------
        # 2. TCP TRACES (4 Numeric + 1 Categorical Feature)
        # ---------------------------------------------------------------------
        tcp_log = os.path.join(trace_dir, f"{package_name}_tcps.log")
        local_ips, remote_ips = set(), set()
        local_ports, remote_ports = set(), set()
        tcp_transitions = []

        valid_tcp_states = [
            "SYN_SENT", "ESTABLISHED", "CLOSE", "FIN_WAIT1", 
            "FIN_WAIT2", "LAST_ACK", "CLOSE_WAIT", "CLOSING"
        ]

        if os.path.exists(tcp_log):
            with open(tcp_log, "r", errors="ignore") as f:
                for line in f:
                    endpoints = re.findall(r"(\d+\.\d+\.\d+\.\d+):(\d+)", line)
                    if len(endpoints) >= 2:
                        local_ips.add(endpoints[0][0])
                        local_ports.add(endpoints[0][1])
                        remote_ips.add(endpoints[1][0])
                        remote_ports.add(endpoints[1][1])
                    for state in valid_tcp_states:
                        if state in line:
                            tcp_transitions.append(state.lower())

        features["Local_IPs_Access"] = len(local_ips)
        features["Remote_IPs_Access"] = len(remote_ips)
        features["Local_Port_Access"] = len(local_ports)
        features["Remote_Port_Access"] = len(remote_ports)
        features["State_Transition"] = " ".join(tcp_transitions) if tcp_transitions else "close established"

        # ---------------------------------------------------------------------
        # 3. INSTALL TRACES (3 Numeric + 3 Categorical Features)
        # ---------------------------------------------------------------------
        inst_log = os.path.join(trace_dir, f"{package_name}_inst.log")
        direct_deps, all_deps = [], []

        if os.path.exists(inst_log):
            with open(inst_log, "r", errors="ignore") as f:
                content = f.read()
                collected = re.findall(r"Collecting\s+([a-zA-Z0-9_\-\.]+)", content)
                direct_deps = list(dict.fromkeys(collected[:3])) if collected else []
                all_deps = list(dict.fromkeys(collected))

        features["Direct_Dependencies"] = len(direct_deps)
        features["Total_Dependencies"] = len(all_deps)
        features["Indirect_Dependencies"] = max(0, len(all_deps) - len(direct_deps))
        features["Total_Dependencies_List"] = " ".join(all_deps) if all_deps else "none"
        features["Direct_Dependencies_List"] = " ".join(direct_deps) if direct_deps else "none"
        features["Indirect_Dependencies_List"] = (
            " ".join(set(all_deps) - set(direct_deps)) if all_deps else "none"
        )

        # ---------------------------------------------------------------------
        # 4. FILETOP TRACES (5 Categorical Process/Transfer Features)
        # ---------------------------------------------------------------------
        filetop_log = os.path.join(trace_dir, f"{package_name}_filetop.log")
        read_procs, write_procs, read_trans, write_trans, file_procs = [], [], [], [], []

        if os.path.exists(filetop_log):
            with open(filetop_log, "r", errors="ignore") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 6:
                        proc = parts[1].lower()
                        if "R" in parts:
                            read_procs.append(proc)
                            read_trans.append(parts[-1])
                        if "W" in parts:
                            write_procs.append(proc)
                            write_trans.append(parts[-1])
                        file_procs.append(proc)

        features["Read_Processes"] = " ".join(set(read_procs)) if read_procs else "pip python"
        features["Write_Processes"] = " ".join(set(write_procs)) if write_procs else "pip python"
        features["Read_Data_Transfer"] = " ".join(read_trans[:15]) if read_trans else "transfer"
        features["Write_Data_Transfer"] = " ".join(write_trans[:15]) if write_trans else "transfer"
        features["File_Access_Processes"] = " ".join(set(file_procs)) if file_procs else "pip python"

        # ---------------------------------------------------------------------
        # 5. SYSCALL TRACES (6 Categorical Operation Groups)
        # ---------------------------------------------------------------------
        syscall_log = os.path.join(trace_dir, f"{package_name}_syscall.log")
        io_ops, file_ops, net_ops, time_ops, sec_ops, proc_ops = [], [], [], [], [], []

        if os.path.exists(syscall_log):
            with open(syscall_log, "r", errors="ignore") as f:
                for line in f:
                    call = line.strip().split()[0].lower() if line.strip() else ""
                    if call in ["ioctl", "poll", "readv", "writev", "lseek", "fcntl"]:
                        io_ops.append(call)
                    elif call in ["open", "openat", "read", "write", "close", "newfstatat", "fstat", "getdents64"]:
                        file_ops.append(call)
                    elif call in ["socket", "connect", "accept", "bind", "listen", "sendto", "recvfrom"]:
                        net_ops.append(call)
                    elif call in ["clock_gettime", "time", "timer_create", "alarm", "nanosleep"]:
                        time_ops.append(call)
                    elif call in ["getuid", "setuid", "geteuid", "getgid", "chmod", "capset"]:
                        sec_ops.append(call)
                    elif call in ["clone", "fork", "vfork", "execve", "wait4", "exit", "kill"]:
                        proc_ops.append(call)

        features["IO_Operations"] = " ".join(io_ops) if io_ops else "ioctl lseek poll"
        features["File_Operations"] = " ".join(file_ops) if file_ops else "newfstatat openat fstat read write close"
        features["Network_Operations"] = " ".join(net_ops) if net_ops else "socket connect"
        features["Time_Operations"] = " ".join(time_ops) if time_ops else "clock_gettime time"
        features["Security_Operations"] = " ".join(sec_ops) if sec_ops else "getuid geteuid"
        features["Process_Operations"] = " ".join(proc_ops) if proc_ops else "clone execve wait4 exit"

        # ---------------------------------------------------------------------
        # 6. PATTERN TRACES (10 Categorical Behavioral Sequences)
        # ---------------------------------------------------------------------
        pattern_defaults = {
            "Pattern_1": "newfstatat openat fstat lseek ioctl",
            "Pattern_2": "read read read newfstatat",
            "Pattern_3": "write pwrite64 fsync",
            "Pattern_4": "socket bind listen accept execve",
            "Pattern_5": "ioctl setresuid setresgid execve",
            "Pattern_6": "openat mmap ioctl prctl no_fd",
            "Pattern_7": "fcntl fcntl close no_error fd_1",
            "Pattern_8": "pipe write read no_error",
            "Pattern_9": "openat fstat fcntl no_fd",
            "Pattern_10": "newfstatat openat fstat error_enoent",
        }

        pattern_log = os.path.join(trace_dir, f"{package_name}_pattern.log")
        if os.path.exists(pattern_log):
            with open(pattern_log, "r", errors="ignore") as f:
                for line in f:
                    for i in range(1, 11):
                        p_name = f"Pattern_{i}"
                        if p_name in line:
                            clean_seq = (
                                line.replace(f"{p_name}:", "")
                                .replace("->", " ")
                                .replace("=", "_")
                                .strip()
                            )
                            features[p_name] = clean_seq

        for p_name, default_seq in pattern_defaults.items():
            if p_name not in features:
                features[p_name] = default_seq

        df = pd.DataFrame([features])

        # Enforce column order if schema was loaded
        if self.numeric_columns and self.categorical_columns:
            ordered_cols = ["Package_Name"] + self.numeric_columns + self.categorical_columns
            df = df.reindex(columns=ordered_cols)

        return df