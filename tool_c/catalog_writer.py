"""tool_c.catalog_writer — Builds and writes endpoint_catalog.json.

Produces a structured audit document covering:
  - Summary stats
  - Per-signal coverage across L1/L2/L3 files
  - Threshold divergence check (V10)
  - Detailed endpoint list (L1)
  - Uncertain endpoint list (L2)
  - Skipped files from JSONL
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from tool_c.classifier import ClassifiedFile
from tool_c.envelope_matcher import match_envelope
from tool_c.method_inferrer import infer_methods


def build_catalog(
    classified_files: list[ClassifiedFile],
    pattern: dict[str, Any],
    global_stats: dict[str, Any],
    skipped_summary: dict[str, Any],
    source_jsonl: str = "",
    postman_items_total: int = 0,
) -> dict[str, Any]:
    """Build the full endpoint_catalog.json structure."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    l1 = [c for c in classified_files if c.tier == "L1"]
    l2 = [c for c in classified_files if c.tier == "L2"]
    l3 = [c for c in classified_files if c.tier == "L3"]

    # Count multi-method files
    multi_method_count = sum(
        1 for c in l1 + l2
        if len(infer_methods(c.file_record, pattern)) > 1
    )

    # Count files with no envelope match
    no_envelope_count = sum(
        1 for c in l1 + l2
        if match_envelope(c.file_record, pattern) is None
    )

    # Count divergence warnings
    divergence_count = sum(
        1 for c in classified_files if c.score_divergence_warning
    )

    # Count redactions (approximated from _tool_c_meta — not available at catalog stage,
    # so we check param keys directly)
    redaction_count = sum(
        1 for c in l1 + l2
        if _has_secret_param(c.file_record)
    )

    # Summary
    summary: dict[str, Any] = {
        "total_file_records_in_jsonl": len(classified_files),
        "l1_endpoint_count": len(l1),
        "l2_uncertain_count": len(l2),
        "l3_ignored_count": len(l3),
        "multi_method_files": multi_method_count,
        "no_envelope_match_count": no_envelope_count,
        "score_divergence_warnings": divergence_count,
        "redaction_applied_count": redaction_count,
        "postman_items_total": postman_items_total,
    }

    # Signal coverage
    signal_coverage = _build_signal_coverage(classified_files, pattern, global_stats)

    # Threshold divergence check (V10 from prompt)
    threshold_check = _build_threshold_check(pattern, global_stats)

    # Endpoint details (L1)
    endpoints = [_build_endpoint_entry(c, pattern) for c in l1]

    # Uncertain list (L2)
    uncertain_endpoints = [_build_uncertain_entry(c) for c in l2]

    # Skipped files
    skipped = skipped_summary.get("skipped_files", [])

    return {
        "generated_at": now,
        "tool_c_version": "1.0",
        "source_jsonl": source_jsonl,
        "pattern_json_version": pattern.get("version", ""),
        "framework": pattern.get("framework", ""),
        "summary": summary,
        "pattern_json_signal_coverage": signal_coverage,
        "threshold_divergence_check": threshold_check,
        "endpoints": endpoints,
        "uncertain_endpoints": uncertain_endpoints,
        "skipped_from_jsonl": skipped,
    }


def write_catalog(catalog: dict[str, Any], path: str) -> None:
    """Write catalog dict to a JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_signal_coverage(
    classified_files: list[ClassifiedFile],
    pattern: dict[str, Any],
    global_stats: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compute per-signal coverage across classification tiers."""
    scoring = pattern["scoring"]
    all_signals = (
        scoring.get("strong_signals", [])
        + scoring.get("weak_signals", [])
        + scoring.get("negative_signals", [])
    )

    # Build lookup: signal_name → global seen_in_files
    freq_table = {
        entry["signal"]: entry.get("seen_in_files", 0)
        for entry in global_stats.get("signal_frequency_table", [])
    }
    known_signals = set(freq_table.keys())
    for entry in global_stats.get("custom_helper_registry", []):
        known_signals.add(entry.get("name", ""))

    coverage: list[dict[str, Any]] = []
    for sig in all_signals:
        name = sig.get("name", "")
        l1_count = sum(1 for c in classified_files if c.tier == "L1" and name in _all_signal_names(c))
        l2_count = sum(1 for c in classified_files if c.tier == "L2" and name in _all_signal_names(c))
        l3_count = sum(1 for c in classified_files if c.tier == "L3" and name in _all_signal_names(c))
        coverage.append({
            "signal_name": name,
            "in_global_stats": name in known_signals,
            "global_seen_in_files": freq_table.get(name, 0),
            "matched_in_l1_files": l1_count,
            "matched_in_l2_files": l2_count,
            "matched_in_l3_files": l3_count,
        })
    return coverage


def _all_signal_names(cf: ClassifiedFile) -> set[str]:
    """All signal names that contributed to this file's score."""
    names: set[str] = set()
    signals = cf.file_record.get("signals", {})
    for sig in signals.get("strong", []) + signals.get("weak", []) + signals.get("negative", []):
        names.add(sig.get("name", ""))
    for h in cf.file_record.get("custom_helpers_called", []):
        names.add(h.get("name", ""))
    return names


def _build_threshold_check(
    pattern: dict[str, Any],
    global_stats: dict[str, Any],
) -> dict[str, Any]:
    hints = global_stats.get("pattern_json_generation_hints", {})
    recommended = hints.get("recommended_endpoint_threshold", None)
    actual = pattern["scoring"]["thresholds"]["endpoint"]
    divergence = abs(actual - recommended) if recommended is not None else None
    warning_msg: str | None = None
    if divergence is not None and divergence > 15:
        warning_msg = (
            f"WARNING: threshold divergence — "
            f"your value={actual}, JSONL hint={recommended}"
        )
    return {
        "recommended_endpoint_threshold": recommended,
        "pattern_json_endpoint_threshold": actual,
        "divergence": divergence,
        "warning": warning_msg,
    }


def _build_endpoint_entry(
    cf: ClassifiedFile,
    pattern: dict[str, Any],
) -> dict[str, Any]:
    """Full detail entry for an L1 endpoint."""
    method_results = infer_methods(cf.file_record, pattern)
    envelope_template = match_envelope(cf.file_record, pattern)

    inferred_methods = []
    for mr in sorted(method_results, key=lambda m: (m.method, m.uri)):
        inferred_methods.append({
            "method": mr.method,
            "uri": mr.uri,
            "inference_source": mr.inference_source,
            "route_source": mr.route_source,
            "confidence": mr.confidence,
        })

    params = cf.file_record.get("input_params", {})
    extracted_params = {
        "get": [p.get("key", "") for p in params.get("get", [])],
        "post": [p.get("key", "") for p in params.get("post", [])],
        "json_body": [p.get("key", "") for p in params.get("json_body", [])],
    }

    return {
        "file": cf.file_record.get("path", ""),
        "confidence_tier": cf.tier,
        "toolc_score": cf.toolc_score,
        "toola_score": cf.toola_score,
        "score_divergence_warning": cf.score_divergence_warning,
        "matched_signals": cf.matched_signals,
        "inferred_methods": inferred_methods,
        "extracted_params": extracted_params,
        "matched_envelope_template": envelope_template["name"] if envelope_template else None,
        "no_envelope_match": envelope_template is None,
        "dynamic_notes": cf.file_record.get("dynamic_notes", []),
        "postman_items_generated": len(method_results),
        "redaction_applied": _has_secret_param(cf.file_record),
    }


def _build_uncertain_entry(cf: ClassifiedFile) -> dict[str, Any]:
    """Simplified entry for an L2 uncertain endpoint."""
    matched = cf.matched_signals
    has_strong = bool(matched.get("strong"))
    if not has_strong:
        reason = "Only weak signals matched; no strong signal present"
    else:
        reason = "Score below confirmed_endpoint threshold"
    return {
        "file": cf.file_record.get("path", ""),
        "confidence_tier": cf.tier,
        "toolc_score": cf.toolc_score,
        "toola_score": cf.toola_score,
        "score_divergence_warning": cf.score_divergence_warning,
        "reason_for_uncertainty": reason,
    }


_SECRET_RE_KEYS = ("api_key", "apikey", "token", "secret", "password")


def _has_secret_param(file_record: dict[str, Any]) -> bool:
    """Check if any input param key looks like a secret."""
    params = file_record.get("input_params", {})
    for bucket in ("get", "post", "json_body", "request"):
        for p in params.get(bucket, []):
            key = p.get("key", "").lower()
            if any(s in key for s in _SECRET_RE_KEYS):
                return True
    return False
