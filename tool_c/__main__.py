"""tool_c.__main__ — CLI entry point for ToolC.

Subcommands:
  generate        Classify endpoints and generate Postman collection
  dry-run         Print classification summary only (no files written)
  validate-rules  Validate pattern.json schema only (no classification)

Usage:
  python tool_c.py generate --jsonl features_raw.jsonl --rules pattern.json --out postman_collection.json
  python tool_c.py dry-run  --jsonl features_raw.jsonl --rules pattern.json
  python tool_c.py validate-rules --rules pattern.json --jsonl features_raw.jsonl
  python -m tool_c generate --jsonl features_raw.jsonl --rules pattern.json --out postman.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


# ── Subcommand: generate ──────────────────────────────────────────────────────

def cmd_generate(args: argparse.Namespace) -> None:
    from tool_c.jsonl_reader     import read_jsonl
    from tool_c.rules_loader     import load_rules
    from tool_c.classifier       import classify_files
    from tool_c.postman_builder  import build_collection
    from tool_c.postman_validator import validate_postman_collection
    from tool_c.catalog_writer   import build_catalog, write_catalog

    # ── Read inputs ──────────────────────────────────────────────────────────
    global_stats, file_records, skipped_summary = read_jsonl(args.jsonl)
    pattern = load_rules(args.rules, global_stats)

    # ── Classify ─────────────────────────────────────────────────────────────
    classified = classify_files(file_records, pattern)

    # ── Dry-run mode ─────────────────────────────────────────────────────────
    if getattr(args, "dry_run", False):
        _print_dry_run(classified, pattern, global_stats, args)
        return

    # ── Build Postman collection ──────────────────────────────────────────────
    folder_structure = getattr(args, "folder_structure", "flat")
    include_uncertain = getattr(args, "include_uncertain", False)
    collection = build_collection(
        classified_files=classified,
        pattern=pattern,
        folder_structure=folder_structure,
        include_uncertain=include_uncertain,
        source_jsonl=args.jsonl,
    )

    # ── Validate ──────────────────────────────────────────────────────────────
    if not validate_postman_collection(collection):
        print("Error: Generated Postman collection failed schema validation.", file=sys.stderr)
        sys.exit(1)

    # ── Write Postman collection ──────────────────────────────────────────────
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(collection, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"[ToolC] Postman collection written to: {args.out}")

    # Count actual items (flatten folders if by_directory)
    postman_items_total = _count_items(collection["item"])

    # ── Write catalog (optional) ──────────────────────────────────────────────
    catalog_path = getattr(args, "catalog", None)
    if catalog_path:
        catalog = build_catalog(
            classified_files=classified,
            pattern=pattern,
            global_stats=global_stats,
            skipped_summary=skipped_summary,
            source_jsonl=args.jsonl,
            postman_items_total=postman_items_total,
        )
        write_catalog(catalog, catalog_path)
        print(f"[ToolC] Endpoint catalog written to: {catalog_path}")

    print(
        f"[ToolC] Done — "
        f"L1={sum(1 for c in classified if c.tier == 'L1')}, "
        f"L2={sum(1 for c in classified if c.tier == 'L2')}, "
        f"L3={sum(1 for c in classified if c.tier == 'L3')}, "
        f"Postman items={postman_items_total}"
    )


# ── Subcommand: dry-run ───────────────────────────────────────────────────────

def cmd_dry_run(args: argparse.Namespace) -> None:
    from tool_c.jsonl_reader    import read_jsonl
    from tool_c.rules_loader    import load_rules
    from tool_c.classifier      import classify_files
    from tool_c.envelope_matcher import match_envelope
    from tool_c.method_inferrer  import infer_methods

    global_stats, file_records, skipped_summary = read_jsonl(args.jsonl)
    pattern = load_rules(args.rules, global_stats)
    classified = classify_files(file_records, pattern)
    _print_dry_run(classified, pattern, global_stats, args)


def _print_dry_run(
    classified: list,
    pattern: dict[str, Any],
    global_stats: dict[str, Any],
    args: argparse.Namespace,
) -> None:
    from tool_c.envelope_matcher import match_envelope
    from tool_c.method_inferrer  import infer_methods

    fw_jsonl = global_stats.get("framework", {}).get("detected", "?")
    fw_pattern = pattern.get("framework", "?")
    fw_match = "✓" if fw_jsonl == fw_pattern else f"MISMATCH (JSONL={fw_jsonl})"

    hints = global_stats.get("pattern_json_generation_hints", {})
    rec_ep = hints.get("recommended_endpoint_threshold", "?")
    rec_un = hints.get("recommended_uncertain_threshold", "?")
    thr_ep = pattern["scoring"]["thresholds"]["endpoint"]
    thr_un = pattern["scoring"]["thresholds"]["uncertain"]

    print("=== ToolC Dry Run ===")
    print(f"JSONL schema version    : 2.0 ✓")
    print(f"Framework (JSONL)       : {fw_jsonl}")
    print(f"Framework (pattern.json): {fw_pattern} {fw_match}")

    # Signal coverage
    freq_table = {
        e["signal"]: e for e in global_stats.get("signal_frequency_table", [])
    }
    custom_registry = {
        e.get("name", ""): e for e in global_stats.get("custom_helper_registry", [])
    }
    scoring = pattern["scoring"]
    all_sigs = (
        scoring.get("strong_signals", [])
        + scoring.get("weak_signals", [])
        + scoring.get("negative_signals", [])
    )

    print("\nSignal coverage check:")
    for sig in all_sigs:
        name = sig["name"]
        if name in freq_table:
            entry = freq_table[name]
            fpr = entry.get("false_positive_risk", "?")
            seen = entry.get("seen_in_files", 0)
            print(f"  {name:<40} → found in JSONL ({seen} files, false_positive_risk: {fpr}) ✓")
        elif name in custom_registry:
            seen = custom_registry[name].get("seen_in_files", 0)
            print(f"  {name:<40} → found in JSONL custom_helper_registry ({seen} files) ✓")
        else:
            print(f"  {name:<40} → NOT FOUND in JSONL ✗")

    print("\nThreshold check:")
    ep_mark = "✓" if rec_ep == "?" or abs(thr_ep - rec_ep) <= 15 else f"DIVERGES from hint={rec_ep}"
    un_mark = "✓" if rec_un == "?" or abs(thr_un - rec_un) <= 15 else f"DIVERGES from hint={rec_un}"
    print(f"  endpoint  : pattern.json={thr_ep}, JSONL hint={rec_ep} {ep_mark}")
    print(f"  uncertain : pattern.json={thr_un}, JSONL hint={rec_un} {un_mark}")

    l1 = [c for c in classified if c.tier == "L1"]
    l2 = [c for c in classified if c.tier == "L2"]
    l3 = [c for c in classified if c.tier == "L3"]

    print("\nClassification results:")
    print(f"  Total file records in JSONL : {len(classified)}")
    print(f"  L1 confirmed endpoints      : {len(l1)}")
    print(f"  L2 uncertain                : {len(l2)}")
    print(f"  L3 ignored                  : {len(l3)}")

    # Multi-method files
    multi = [
        (c, infer_methods(c.file_record, pattern))
        for c in l1 + l2
    ]
    multi = [(c, mrs) for c, mrs in multi if len(mrs) > 1]
    if multi:
        print("\nMulti-method files (will generate multiple Postman items):")
        for c, mrs in multi:
            methods_str = " + ".join(sorted(set(m.method for m in mrs)))
            src = mrs[0].inference_source if mrs else "?"
            print(f"  {c.file_record.get('path', '?')}  → {methods_str} (source: {src})")

    # Score divergence warnings
    divs = [c for c in classified if c.score_divergence_warning]
    if divs:
        print("\nScore divergence warnings (|toolc - toola| > 30):")
        for c in divs:
            print(
                f"  {c.file_record.get('path', '?'):<50}  "
                f"toolc={c.toolc_score}, toola={c.toola_score}  ← REVIEW"
            )

    # Envelope matches
    from collections import Counter as _Counter
    tmpl_counts: _Counter[str] = _Counter()
    no_match_count = 0
    for c in l1 + l2:
        tmpl = match_envelope(c.file_record, pattern)
        if tmpl:
            tmpl_counts[tmpl["name"]] += 1
        else:
            no_match_count += 1
    if tmpl_counts or no_match_count > 0:
        print("\nEnvelope template matches:")
        for name, count in sorted(tmpl_counts.items()):
            print(f"  {name:<20}: {count} files")
        if no_match_count > 0:
            print(
                f"  (no match)          : {no_match_count} files  "
                "← consider adding templates to pattern.json"
            )

    # Total Postman items estimate
    total_items = sum(
        len(infer_methods(c.file_record, pattern))
        for c in l1
    )
    out_path = getattr(args, "out", None) or "(not specified — dry run only)"
    print(f"\nPostman items to be generated: {total_items}")
    print(f"Output would be written to: {out_path}")


# ── Subcommand: validate-rules ────────────────────────────────────────────────

def cmd_validate_rules(args: argparse.Namespace) -> None:
    from tool_c.jsonl_reader import read_jsonl
    from tool_c.rules_loader import load_rules

    global_stats, _, _ = read_jsonl(args.jsonl)
    pattern = load_rules(args.rules, global_stats)  # exits 1 on failure

    # Count validations passed (warnings do not count as failures)
    print("Pattern.json validation: ✓ all checks passed")
    print(f"Framework: {pattern.get('framework', '?')}")
    print(f"Thresholds: endpoint={pattern['scoring']['thresholds']['endpoint']}, "
          f"uncertain={pattern['scoring']['thresholds']['uncertain']}")
    scoring = pattern["scoring"]
    n_signals = (
        len(scoring.get("strong_signals", []))
        + len(scoring.get("weak_signals", []))
        + len(scoring.get("negative_signals", []))
    )
    print(f"Signals: {n_signals} total")
    print(f"Envelope templates: {len(pattern.get('endpoint_envelopes', {}).get('templates', []))}")


# ── Argument parser ───────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tool_c",
        description="ToolC — Rules-Based API Endpoint Classifier and Postman Generator",
    )
    sub = parser.add_subparsers(dest="command")

    # ── generate ─────────────────────────────────────────────────────────────
    gen = sub.add_parser("generate", help="Classify endpoints and generate Postman collection")
    gen.add_argument("--jsonl",    required=True,  help="Path to features_raw.jsonl from ToolA v2")
    gen.add_argument("--rules",    required=True,  help="Path to pattern.json rules file")
    gen.add_argument("--out",      required=True,  help="Output path for postman_collection.json")
    gen.add_argument("--catalog",  default=None,   help="Output path for endpoint_catalog.json")
    gen.add_argument(
        "--include-uncertain", action="store_true",
        help="Include L2 uncertain endpoints in Postman output",
    )
    gen.add_argument(
        "--folder-structure", default="flat", choices=["flat", "by_directory"],
        help="Postman folder grouping: flat (default) or by_directory",
    )
    gen.add_argument(
        "--dry-run", action="store_true",
        help="Print classification summary only; do not write files",
    )

    # ── dry-run ───────────────────────────────────────────────────────────────
    dr = sub.add_parser(
        "dry-run",
        help="Print classification summary only (no files written)",
    )
    dr.add_argument("--jsonl",  required=True, help="Path to features_raw.jsonl")
    dr.add_argument("--rules",  required=True, help="Path to pattern.json rules file")
    dr.add_argument("--out",    default=None,  help="(ignored in dry-run, shows in output)")

    # ── validate-rules ────────────────────────────────────────────────────────
    vr = sub.add_parser(
        "validate-rules",
        help="Validate pattern.json schema only (no classification)",
    )
    vr.add_argument("--rules",  required=True, help="Path to pattern.json rules file")
    vr.add_argument("--jsonl",  required=True, help="Path to features_raw.jsonl (for signal cross-check)")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)
    elif args.command == "generate":
        cmd_generate(args)
    elif args.command == "dry-run":
        cmd_dry_run(args)
    elif args.command == "validate-rules":
        cmd_validate_rules(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()


# ── Utility ───────────────────────────────────────────────────────────────────

def _count_items(item_list: list[dict[str, Any]]) -> int:
    """Recursively count leaf items (not folders)."""
    total = 0
    for item in item_list:
        if "item" in item and "request" not in item:
            # It's a folder
            total += _count_items(item["item"])
        else:
            total += 1
    return total
