"""
tool_a v2 — PHP API Feature Extractor

CLI entry point.  Invoked as:
  python tool_a.py scan --root /path --out report.md [--raw raw.jsonl] [...]
  python -m tool_a  scan --root /path --out report.md
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List

from .detector import Detector
from .framework_detector import detect_framework
from .helper_registry import HelperRegistry
from .models import FileRecord, SkippedFile
from .reporter import generate_markdown_report
from .route_mapper import RouteMapper
from .scanner import (
    DEFAULT_EXCLUDE_DIRS,
    DEFAULT_INCLUDE_EXTENSIONS,
    DEFAULT_MAX_FILE_SIZE_MB,
    collect_files,
)
from .serializer import write_jsonl
from .signals import FRAMEWORK_SIGNALS


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="tool_a",
        description="Scan a PHP project and extract API feature evidence.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    scan_p = subparsers.add_parser("scan", help="Scan a PHP project directory.")
    scan_p.add_argument("--root", required=True, help="PHP project root directory.")
    scan_p.add_argument(
        "--out", default="features_report.md", help="Markdown output path."
    )
    scan_p.add_argument("--raw", default=None, help="JSONL output path (optional).")
    scan_p.add_argument(
        "--exclude",
        nargs="*",
        metavar="DIR",
        help=f"Directories to skip. Default: {' '.join(DEFAULT_EXCLUDE_DIRS)}",
    )
    scan_p.add_argument(
        "--ext",
        nargs="*",
        metavar="EXT",
        dest="extensions",
        help=f"File extensions to scan. Default: {' '.join(DEFAULT_INCLUDE_EXTENSIONS)}",
    )
    scan_p.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Maximum number of files to scan (0 = unlimited).",
    )
    scan_p.add_argument(
        "--max-file-size",
        type=float,
        default=DEFAULT_MAX_FILE_SIZE_MB,
        dest="max_file_size",
        help=f"Maximum file size in MB to scan. Default: {DEFAULT_MAX_FILE_SIZE_MB}",
    )
    scan_p.add_argument(
        "--max-snippet-lines",
        type=int,
        default=80,
        dest="max_snippet_lines",
        help="Max total snippet lines per file. Default: 80",
    )
    scan_p.add_argument(
        "--min-score",
        type=int,
        default=0,
        dest="min_score",
        help="Only include files at or above this score in the Markdown report.",
    )
    scan_p.add_argument(
        "--framework",
        default=None,
        choices=["laravel", "wordpress", "codeigniter", "symfony", "slim", "plain"],
        help="Force a specific framework profile (skip auto-detection).",
    )

    # Support running without explicit 'scan' subcommand for convenience
    if len(sys.argv if argv is None else argv) == 1:
        parser.print_help()
        sys.exit(0)

    raw_args = argv if argv is not None else sys.argv[1:]
    if raw_args and raw_args[0] not in ("scan", "-h", "--help"):
        raw_args = ["scan"] + raw_args

    args = parser.parse_args(raw_args)

    if args.command == "scan":
        run_scan(args)
    else:
        parser.print_help()


# ── Scan pipeline ─────────────────────────────────────────────────────────────

def run_scan(args) -> None:
    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"Error: '{root}' is not a valid directory.", file=sys.stderr)
        sys.exit(1)

    # ── 1. Framework detection ────────────────────────────────────────────────
    framework, fw_confidence, fw_evidence = detect_framework(root, args.framework)
    print(f"[framework] Detected: {framework} (confidence: {fw_confidence})")
    for ev in fw_evidence:
        print(f"            {ev}")

    # ── 2. Collect file paths ─────────────────────────────────────────────────
    print("[scanner]   Collecting file paths …")
    file_paths, skipped_raw = collect_files(
        root_path=root,
        exclude_dirs=args.exclude,
        include_extensions=args.extensions,
        max_file_size_mb=args.max_file_size,
        max_files=args.max_files,
    )
    skipped_files: List[SkippedFile] = [
        SkippedFile(
            path=os.path.relpath(s["path"], root),
            reason=s["reason"],
            size_mb=s.get("size_mb"),
        )
        for s in skipped_raw
    ]
    print(f"            {len(file_paths)} files to scan, {len(skipped_files)} skipped.")

    # ── 3. Pass 1: build helper registry + count raw signal frequencies ───────
    print("[pass 1]    Building helper registry …")
    registry = HelperRegistry()
    registry.build_from_files(file_paths, root)
    print(f"            {len(registry.helpers)} custom helpers found.")

    # Count signal frequencies across all files (lightweight pass)
    print("[pass 1]    Counting global signal frequencies …")
    profile = FRAMEWORK_SIGNALS.get(framework, FRAMEWORK_SIGNALS["plain"])
    global_freq: Counter = Counter()   # signal_name → file count
    signal_fpr: Dict[str, str] = {
        sig["name"]: sig.get("false_positive_risk", "low") for sig in profile
    }
    for path in file_paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            continue
        seen_in_this_file: set = set()
        for sig in profile:
            if sig["name"] not in seen_in_this_file and sig["pattern"].search(content):
                global_freq[sig["name"]] += 1
                seen_in_this_file.add(sig["name"])
        registry.count_calls_in_content(content)

    # ── 4. Route mapper ────────────────────────────────────────────────────────
    print("[routes]    Loading route definitions …")
    route_mapper = RouteMapper()
    route_mapper.load(framework, root)

    # ── 5. Pass 2: full per-file analysis ─────────────────────────────────────
    print("[pass 2]    Analysing files …")
    detector = Detector(max_snippet_lines=args.max_snippet_lines)
    file_records: List[FileRecord] = []
    dir_counter: Counter = Counter()

    for path in file_paths:
        rel = os.path.relpath(path, root)
        dir_counter[os.path.dirname(rel)] += 1
        record = detector.analyze_file(
            file_path=path,
            rel_path=rel,
            framework=framework,
            helper_registry=registry,
            route_mapper=route_mapper,
            global_freq=dict(global_freq),
            signal_fpr=signal_fpr,
        )
        file_records.append(record)

    # ── 6. Finalize helper registry stats ─────────────────────────────────────
    candidate_files = [r for r in file_records if not r.skipped and r.score > 0]
    registry.finalize_stats(len(candidate_files))

    # ── 7. Compute global stats ────────────────────────────────────────────────
    global_stats = _build_global_stats(
        framework=framework,
        fw_confidence=fw_confidence,
        fw_evidence=fw_evidence,
        file_records=file_records,
        skipped_files=skipped_files,
        global_freq=global_freq,
        profile=profile,
        signal_fpr=signal_fpr,
        registry=registry,
        dir_counter=dir_counter,
    )

    # ── 8. Write markdown report ───────────────────────────────────────────────
    print(f"[report]    Writing Markdown report to '{args.out}' …")
    generate_markdown_report(file_records, global_stats, args.out, args.min_score)
    print(f"            Done.")

    # ── 9. Write JSONL report (optional) ──────────────────────────────────────
    if args.raw:
        print(f"[jsonl]     Writing JSONL to '{args.raw}' …")
        write_jsonl(global_stats, file_records, skipped_files, args.raw)
        print(f"            Done.")

    _print_summary(file_records, skipped_files)


# ── Global stats builder ──────────────────────────────────────────────────────

def _build_global_stats(
    *,
    framework: str,
    fw_confidence: str,
    fw_evidence: List[str],
    file_records: List[FileRecord],
    skipped_files: List[SkippedFile],
    global_freq: Counter,
    profile: List[dict],
    signal_fpr: Dict[str, str],
    registry: HelperRegistry,
    dir_counter: Counter,
) -> Dict[str, Any]:
    candidate_files = [r for r in file_records if not r.skipped and r.score > 0]
    n_candidates = len(candidate_files)
    scores = sorted(r.score for r in candidate_files)

    def pct(n):
        return round(n / n_candidates * 100, 1) if n_candidates else 0.0

    # Skip reasons
    skip_reasons: Counter = Counter(s.reason for s in skipped_files)

    # Signal frequency table
    sig_table = []
    for sig in profile:
        name = sig["name"]
        n = global_freq.get(name, 0)
        sig_table.append(
            {
                "signal": name,
                "kind": sig["kind"],
                "seen_in_files": n,
                "pct_of_candidates": pct(n),
                "false_positive_risk": sig.get("false_positive_risk", "low"),
                "false_positive_risk_reason": _fpr_reason(
                    sig.get("false_positive_risk", "low"), name
                ),
            }
        )
    sig_table.sort(key=lambda x: x["seen_in_files"], reverse=True)

    # Envelope key frequency
    env_counter: Counter = Counter()
    for r in candidate_files:
        for ek in r.envelope_keys:
            env_counter[ek.key] += 1
    env_table = [
        {"key": k, "seen_in_files": v, "pct_of_candidates": pct(v)}
        for k, v in env_counter.most_common()
    ]

    # Method distribution
    method_dist: Counter = Counter()
    for r in candidate_files:
        if r.route_hints:
            for rh in r.route_hints:
                method_dist[rh.method] += 1
        elif r.method_hints:
            for mh in r.method_hints:
                method_dist[mh["method"]] += 1
        else:
            method_dist["unknown"] += 1

    # Co-occurrence patterns (top 5 signal pairs)
    co_occur = _compute_co_occurrence(candidate_files)

    # Score distribution
    score_dist = _score_percentiles(scores)

    # Recommended signals for pattern.json generation hints
    strong_sigs = sorted(
        (s for s in sig_table if s["kind"] == "strong"),
        key=lambda x: x["seen_in_files"],
        reverse=True,
    )
    weak_sigs = sorted(
        (s for s in sig_table if s["kind"] == "weak"),
        key=lambda x: x["seen_in_files"],
        reverse=True,
    )
    neg_sigs = sorted(
        (s for s in sig_table if s["kind"] == "negative"),
        key=lambda x: x["seen_in_files"],
        reverse=True,
    )

    recommended_strong = [s["signal"] for s in strong_sigs[:5]]
    # Also include custom helpers
    for h in registry.helpers.values():
        if h.helper_name not in recommended_strong:
            recommended_strong.append(h.helper_name)

    # Recommend thresholds based on score distribution
    p50 = score_dist.get("p50", 20)
    p25 = score_dist.get("p25", 10)
    endpoint_thr = max(30, p50)
    uncertain_thr = max(10, min(p25, endpoint_thr - 10))
    if endpoint_thr - uncertain_thr < 10:
        uncertain_thr = endpoint_thr - 10

    # Best recommended envelope keys (appear in ≥ 20 % of candidates)
    threshold_pct = 20.0
    env_all_of = [e["key"] for e in env_table if e["pct_of_candidates"] >= 40.0][:3]
    env_any_of = [
        e["key"]
        for e in env_table
        if threshold_pct <= e["pct_of_candidates"] < 40.0
    ][:5]

    hints = {
        "recommended_strong_signals": recommended_strong,
        "recommended_weak_signals": [s["signal"] for s in weak_sigs[:3]],
        "recommended_negative_signals": [s["signal"] for s in neg_sigs[:3]],
        "recommended_endpoint_threshold": endpoint_thr,
        "endpoint_threshold_basis": (
            f"Files with at least one strong signal cluster at score >= {endpoint_thr}; "
            "threshold set at the lower edge of this cluster"
        ),
        "recommended_uncertain_threshold": uncertain_thr,
        "uncertain_threshold_basis": (
            f"Files with only weak signals and no strong signals cluster below score {uncertain_thr+10}; "
            "threshold set above this cluster"
        ),
        "minimum_threshold_gap": 10,
        "minimum_threshold_gap_note": (
            "ToolB and ToolC both enforce: "
            "(endpoint_threshold - uncertain_threshold) >= minimum_threshold_gap. "
            "Do not adjust recommended values in a way that violates this gap."
        ),
        "score_distribution_summary": {**score_dist, "note": "Percentiles across all candidate files (score > 0)"},
        "recommended_envelope_template": {
            "keys_all_of": env_all_of,
            "keys_any_of": env_any_of,
        },
        "warning": (
            "These are suggestions derived from signal frequency and score distribution only. "
            "Human review is required before using as final pattern.json values."
        ),
    }

    return {
        "record_type": "global_stats",
        "schema_version": "2.0",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "framework": {
            "detected": framework,
            "confidence": fw_confidence,
            "evidence": fw_evidence,
        },
        "scan_summary": {
            "total_files_scanned": len(file_records),
            "total_files_skipped": len(skipped_files),
            "skip_reasons": dict(skip_reasons),
            "candidate_files_above_score_0": len(candidate_files),
            "candidate_files_above_score_30": len(
                [r for r in candidate_files if r.score >= 30]
            ),
            "candidate_files_above_score_60": len(
                [r for r in candidate_files if r.score >= 60]
            ),
        },
        "signal_frequency_table": sig_table,
        "custom_helper_registry": registry.to_jsonl_list(),
        "envelope_key_frequency": env_table,
        "method_distribution": dict(method_dist),
        "co_occurrence_patterns": co_occur,
        "pattern_json_generation_hints": hints,
        # Extra for the Markdown report
        "top_dirs": dir_counter.most_common(10),
    }


# ── Stats helpers ─────────────────────────────────────────────────────────────

def _fpr_reason(fpr: str, signal: str) -> str:
    if fpr == "low":
        return f"Framework-native signal; rarely appears in non-API files"
    if fpr == "medium":
        return f"Appears in both API and non-API files; always co-check negative signals"
    if fpr == "high":
        return f"Very generic; strong negative signals needed to confirm"
    return "n/a"


def _compute_co_occurrence(candidate_files: List[FileRecord]) -> List[dict]:
    """Top 5 signal pairs by file co-occurrence count."""
    from itertools import combinations

    pair_counter: Counter = Counter()
    for record in candidate_files:
        all_signal_names = set()
        for kind_list in record.signals.values():
            for s in kind_list:
                all_signal_names.add(s.name)
        for pair in combinations(sorted(all_signal_names), 2):
            pair_counter[pair] += 1

    result = []
    for (a, b), count in pair_counter.most_common(5):
        result.append(
            {
                "signals": [a, b],
                "files_count": count,
                "note": f"These two signals co-occur in {count} candidate file(s)",
            }
        )
    return result


def _score_percentiles(scores: List[int]) -> Dict[str, Any]:
    if not scores:
        return {"p25": 0, "p50": 0, "p75": 0, "p90": 0}
    n = len(scores)

    def percentile(p):
        idx = max(0, int(n * p / 100) - 1)
        return scores[min(idx, n - 1)]

    return {
        "p25": percentile(25),
        "p50": percentile(50),
        "p75": percentile(75),
        "p90": percentile(90),
    }


def _print_summary(
    file_records: List[FileRecord], skipped_files: List[SkippedFile]
) -> None:
    candidates = [r for r in file_records if not r.skipped and r.score > 0]
    above_30 = [r for r in candidates if r.score >= 30]
    above_60 = [r for r in candidates if r.score >= 60]
    print(
        f"\n[done]      Total: {len(file_records)} scanned, "
        f"{len(skipped_files)} skipped, "
        f"{len(candidates)} candidates (score>0), "
        f"{len(above_30)} above 30, {len(above_60)} above 60."
    )


if __name__ == "__main__":
    main()
