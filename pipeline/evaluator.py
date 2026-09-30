#!/usr/bin/env python3
"""
Research-grade DySec evaluator.

Usage from repository root:
    python -m pipeline.evaluator \
        --trace-dir traces/requeksts-1.0.0/strategy_A/round_01 \
        --package-name requeksts-1.0.0

This evaluator deliberately does NOT continue to RF inference when the trace
evidence or feature extraction is invalid. A prediction is only emitted after
the 39 raw features have been extracted from the canonical trace directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from pipeline.dysec_predictor import DySecPredictor
from pipeline.feature_extractor import DySecFeatureExtractor, _files, _strace_files


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def feature_hash(df: pd.DataFrame, columns: list[str]) -> str:
    payload = {}
    row = df.iloc[0]
    for col in columns:
        value = row[col]
        if pd.isna(value):
            value = ""
        payload[col] = value.item() if hasattr(value, "item") else value
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256_text(canonical)


def discover_trace_evidence(trace_dir: Path) -> dict:
    evidence = {
        "filetop": _files(trace_dir, "QUT-DV25_Filetop_Traces", "*"),
        "installation": _files(trace_dir, "QUT-DV25_Installation_Traces", "*"),
        "opensnoop": _files(trace_dir, "QUT-DV25_Opensnoop_Traces", "*"),
        "tcp": _files(trace_dir, "QUT-DV25_TCP_Traces", "*"),
        "pattern_strace": _strace_files(trace_dir),
        "systemcall": _files(trace_dir, "QUT-DV25_SystemCall_Traces", "*"),
    }
    return evidence


def parse_strace_stats(paths: list[Path]) -> tuple[int, int, list[str]]:
    from pipeline.feature_extractor import _parse_strace_line

    raw_lines = 0
    parsed = 0
    calls = []
    for path in paths:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            raw_lines += 1
            syscall, _ = _parse_strace_line(line)
            if syscall:
                parsed += 1
                calls.append(syscall)
    return raw_lines, parsed, calls


def validate_evidence(evidence: dict) -> None:
    required = ("filetop", "installation", "opensnoop", "tcp", "pattern_strace")
    missing = [name for name in required if not evidence[name]]
    if missing:
        raise RuntimeError(
            "TRACE INTEGRITY FAILED. Missing canonical evidence: "
            + ", ".join(missing)
        )

    empty = []
    for name, paths in evidence.items():
        if name == "systemcall":
            continue
        if paths and all(p.stat().st_size == 0 for p in paths):
            empty.append(name)
    if empty:
        raise RuntimeError(
            "TRACE INTEGRITY FAILED. Empty evidence files: "
            + ", ".join(empty)
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-dir", required=True)
    parser.add_argument("--package-name", required=True)
    parser.add_argument("--model-dir", default="models/rf")
    parser.add_argument("--schema-path", default="models/rf/Combined_schema.json")
    parser.add_argument("--save-json", default=None)
    parser.add_argument("--save-csv", default=None)
    args = parser.parse_args()

    trace_dir = Path(args.trace_dir).resolve()
    if not trace_dir.is_dir():
        raise SystemExit(f"Trace directory not found: {trace_dir}")

    print("=" * 80)
    print(f"EVALUATING: {args.package_name}")
    print("=" * 80)

    evidence = discover_trace_evidence(trace_dir)

    print("\nTRACE DISCOVERY")
    print("-" * 72)
    print(f"Filetop files        : {len(evidence['filetop'])}")
    print(f"Installation files   : {len(evidence['installation'])}")
    print(f"Opensnoop files      : {len(evidence['opensnoop'])}")
    print(f"TCP files            : {len(evidence['tcp'])}")
    print(f"Pattern strace files : {len(evidence['pattern_strace'])}")
    print(f"SystemCall files     : {len(evidence['systemcall'])}")
    print(f"TCP present          : {bool(evidence['tcp'])}")

    validate_evidence(evidence)

    raw_lines, parsed_calls, calls = parse_strace_stats(evidence["pattern_strace"])
    unique_calls = sorted(set(calls))

    syscall_digest = hashlib.sha256(
        "\n".join(calls).encode("utf-8")
    ).hexdigest()

    print("\nSYSCALL TRACE VALIDATION")
    print("-" * 72)
    print(f"Strace files         : {len(evidence['pattern_strace'])}")
    print(f"Raw strace lines     : {raw_lines}")
    print(f"Parsed syscalls      : {parsed_calls}")
    print(f"Unique syscalls      : {len(unique_calls)}")
    print(f"Syscall SHA256       : {syscall_digest}")

    if parsed_calls == 0:
        raise RuntimeError("TRACE INTEGRITY FAILED: zero parseable syscalls.")

    predictor = DySecPredictor(args.model_dir)

    print("\nMODEL")
    print("-" * 72)
    print(f"Raw model features   : {len(predictor.raw_cols)}")
    print(f"Numeric features     : {len(predictor.num_cols)}")
    print(f"Categorical features : {len(predictor.cat_cols)}")
    print(f"Vectorizer features  : {len(predictor.vectorizer.vocabulary_)}")
    print(f"Scaler features      : {predictor.scaler.n_features_in_}")
    print(f"RF features          : {predictor.model.n_features_in_}")

    extractor = DySecFeatureExtractor(args.schema_path)
    feature_df = extractor.extract(str(trace_dir), args.package_name)

    model_df = feature_df.drop(columns=["Package_Name"], errors="ignore")
    expected = predictor.raw_cols
    actual = list(model_df.columns)

    print("\nFEATURE SCHEMA")
    print("-" * 72)
    print(f"Extractor features  : {len(actual)}")
    print(f"Expected raw        : {len(expected)}")
    print(f"Numeric             : {len(predictor.num_cols)}")
    print(f"Categorical         : {len(predictor.cat_cols)}")

    if set(actual) != set(expected):
        missing = [c for c in expected if c not in actual]
        extra = [c for c in actual if c not in expected]
        raise RuntimeError(
            f"FEATURE SCHEMA FAILED.\nMissing: {missing}\nExtra: {extra}"
        )

    model_df = model_df[expected]

    # No fabricated Pattern_* values are allowed.
    pattern_values = {
        c: str(model_df.iloc[0][c])
        for c in expected
        if c.startswith("Pattern_")
    }

    print("\nPATTERN FEATURES")
    print("-" * 72)
    for name, value in pattern_values.items():
        print(f"{name:<20} = {value!r}")

    print("\nEXTRACTED FEATURES")
    print("-" * 72)
    for col in expected:
        print(f"{col:<32} = {model_df.iloc[0][col]!r}")

    fhash = feature_hash(model_df, expected)

    print("\nMODEL PIPELINE")
    print("-" * 72)
    print("Passing exactly 39 raw features to DySecPredictor.")
    print(f"Feature SHA256       : {fhash}")

    result = predictor.predict(model_df)

    print("\nRF INFERENCE")
    print("-" * 72)
    print(f"prediction           : {result['prediction']}")
    print(f"verdict              : {result['verdict']}")
    print(f"p_benign             : {result['p_benign']:.12f}")
    print(f"p_malicious          : {result['p_malicious']:.12f}")
    print(f"transformed features : {result['transformed_features']}")
    print(f"RF features          : {result['rf_features']}")

    diagnostics = {
        "package": args.package_name,
        "trace_directory": str(trace_dir),
        "trace_files": {
            k: [str(p) for p in v] for k, v in evidence.items()
        },
        "trace_counts": {k: len(v) for k, v in evidence.items()},
        "raw_strace_lines": raw_lines,
        "parsed_syscalls": parsed_calls,
        "unique_syscalls": len(unique_calls),
        "syscall_sha256": syscall_digest,
        "raw_features": len(expected),
        "numeric_features": len(predictor.num_cols),
        "categorical_features": len(predictor.cat_cols),
        "vectorizer_features": len(predictor.vectorizer.vocabulary_),
        "transformed_features": result["transformed_features"],
        "rf_features": result["rf_features"],
        "feature_sha256": fhash,
        "pattern_values": pattern_values,
        "prediction": result["prediction"],
        "verdict": result["verdict"],
        "p_benign": result["p_benign"],
        "p_malicious": result["p_malicious"],
        "pattern_fallback": False,
    }

    print("\nRESEARCH DIAGNOSTICS")
    print("-" * 72)
    print(f"Package              : {args.package_name}")
    print(f"Trace directory      : {trace_dir}")
    print(f"Strace files         : {len(evidence['pattern_strace'])}")
    print(f"Raw strace lines     : {raw_lines}")
    print(f"Syscall count        : {parsed_calls}")
    print(f"Unique syscalls      : {len(unique_calls)}")
    print(f"TCP present          : {bool(evidence['tcp'])}")
    print(f"Raw model features   : {len(expected)}")
    print(f"RF features          : {result['rf_features']}")
    print(f"Syscall SHA256       : {syscall_digest}")
    print(f"Feature SHA256       : {fhash}")
    print("Pattern fallback     : False")

    if args.save_json:
        Path(args.save_json).write_text(
            json.dumps(diagnostics, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    if args.save_csv:
        pd.DataFrame([diagnostics]).to_csv(args.save_csv, index=False)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
