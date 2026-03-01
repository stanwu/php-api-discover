"""tool_c.classifier — Re-scoring and confidence tier assignment.

Re-scores each file record using pattern.json rules.
ToolA's score is used only as a cross-check reference (|diff| > 30 → warning).

Confidence tiers:
  L1: toolc_score >= thresholds.endpoint      → "confirmed_endpoint"
  L2: thresholds.uncertain <= score < endpoint → "uncertain"
  L3: score < thresholds.uncertain             → "not_endpoint"
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ClassifiedFile:
    file_record: dict[str, Any]
    toolc_score: int
    toola_score: int
    tier: str                            # "L1", "L2", "L3"
    confidence_label: str                # "confirmed_endpoint" | "uncertain" | "not_endpoint"
    matched_signals: dict[str, list[str]]  # {"strong": [...], "weak": [...], "negative": [...]}
    score_divergence_warning: str | None


_TIER_LABELS: dict[str, str] = {
    "L1": "confirmed_endpoint",
    "L2": "uncertain",
    "L3": "not_endpoint",
}


def find_signal_in_pattern(
    name: str,
    signal_list: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Exact name match lookup in a signal list."""
    for sig in signal_list:
        if sig.get("name") == name:
            return sig
    return None


def compute_toolc_score(
    file_record: dict[str, Any],
    pattern: dict[str, Any],
) -> tuple[int, dict[str, list[str]]]:
    """Compute ToolC score for one file record.

    Returns (clamped_score [0..100], matched_signals_dict).
    """
    scoring = pattern["scoring"]
    strong_patterns = scoring["strong_signals"]
    weak_patterns = scoring["weak_signals"]
    negative_patterns = scoring["negative_signals"]

    score = 0
    matched: dict[str, list[str]] = {"strong": [], "weak": [], "negative": []}

    signals = file_record.get("signals", {})

    # Track names counted via signals.strong (double-count guard with custom helpers)
    counted_via_strong: set[str] = set()

    # Strong signals — cap occurrences at 3 to prevent inflation
    for sig in signals.get("strong", []):
        name = sig.get("name", "")
        m = find_signal_in_pattern(name, strong_patterns)
        if m:
            occurrences = sig.get("occurrences", 1)
            score += m["weight"] * min(occurrences, 3)
            matched["strong"].append(name)
            counted_via_strong.add(name)

    # Weak signals — no occurrence multiplication
    for sig in signals.get("weak", []):
        name = sig.get("name", "")
        m = find_signal_in_pattern(name, weak_patterns)
        if m:
            score += m["weight"]
            matched["weak"].append(name)

    # Negative signals
    for sig in signals.get("negative", []):
        name = sig.get("name", "")
        m = find_signal_in_pattern(name, negative_patterns)
        if m:
            score += m["weight"]  # negative value
            matched["negative"].append(name)

    # Custom helpers — treated as strong signals; same cap; double-count guard
    helper_counts = Counter(
        h.get("name", "") for h in file_record.get("custom_helpers_called", [])
    )
    for helper_name, call_count in helper_counts.items():
        if not helper_name or helper_name in counted_via_strong:
            continue
        m = find_signal_in_pattern(helper_name, strong_patterns)
        if m:
            score += m["weight"] * min(call_count, 3)
            matched["strong"].append(helper_name)

    return max(0, min(100, score)), matched


def _is_excluded(path: str, exclude_paths: list[str]) -> bool:
    return any(path.startswith(prefix) for prefix in exclude_paths)


def _has_allowed_extension(path: str, include_extensions: list[str]) -> bool:
    if not include_extensions:
        return True
    return any(path.endswith(ext) for ext in include_extensions)


def classify_files(
    file_records: list[dict[str, Any]],
    pattern: dict[str, Any],
) -> list[ClassifiedFile]:
    """Classify all file records, returning a list sorted by file path."""
    exclude_paths = pattern.get("exclude_paths", [])
    include_extensions = pattern.get("include_extensions", [".php"])
    thresholds = pattern["scoring"]["thresholds"]
    endpoint_thr = thresholds["endpoint"]
    uncertain_thr = thresholds["uncertain"]

    results: list[ClassifiedFile] = []

    for record in file_records:
        path = record.get("path", "")

        if _is_excluded(path, exclude_paths):
            continue
        if not _has_allowed_extension(path, include_extensions):
            continue

        toolc_score, matched = compute_toolc_score(record, pattern)
        toola_score = record.get("score", 0)

        if toolc_score >= endpoint_thr:
            tier = "L1"
        elif toolc_score >= uncertain_thr:
            tier = "L2"
        else:
            tier = "L3"

        divergence_warning: str | None = None
        if abs(toolc_score - toola_score) > 30:
            divergence_warning = (
                f"Score divergence: toolc={toolc_score}, toola={toola_score} "
                f"(diff={abs(toolc_score - toola_score)}) — REVIEW"
            )

        results.append(
            ClassifiedFile(
                file_record=record,
                toolc_score=toolc_score,
                toola_score=toola_score,
                tier=tier,
                confidence_label=_TIER_LABELS[tier],
                matched_signals=matched,
                score_divergence_warning=divergence_warning,
            )
        )

    results.sort(key=lambda c: c.file_record.get("path", ""))
    return results
