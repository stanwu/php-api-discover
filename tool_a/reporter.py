"""
Markdown report writer (v2).

Generates a structured human-readable feature extraction report.
"""

import os
from typing import Any, Dict, List

from .models import FileRecord


def generate_markdown_report(
    file_records: List[FileRecord],
    global_stats: Dict[str, Any],
    output_path: str,
    min_score: int = 0,
) -> None:
    with open(output_path, "w", encoding="utf-8") as fh:
        _write_header(fh, global_stats)
        _write_summary(fh, global_stats)
        _write_helper_registry(fh, global_stats)
        _write_top_candidates(fh, file_records, min_score)
        fh.write("\n---\n\n## File Details\n\n")
        _write_file_details(fh, file_records, min_score)


# ── Report sections ───────────────────────────────────────────────────────────

def _write_header(fh, gs: Dict[str, Any]) -> None:
    fh.write("# PHP API Feature Extraction Report\n\n")
    fw = gs.get("framework", {})
    detected = fw.get("detected", "unknown")
    confidence = fw.get("confidence", "unknown")
    evidence = ", ".join(fw.get("evidence", []))
    fh.write(
        f"**Detected Framework:** `{detected}` "
        f"(confidence: {confidence})  \n"
        f"**Evidence:** {evidence}\n\n"
    )


def _write_summary(fh, gs: Dict[str, Any]) -> None:
    fh.write("## Scan Summary\n\n")
    ss = gs.get("scan_summary", {})
    fh.write(f"- Total files scanned: {ss.get('total_files_scanned', 0)}\n")
    fh.write(f"- Total files skipped: {ss.get('total_files_skipped', 0)}")
    skip_reasons = ss.get("skip_reasons", {})
    if skip_reasons:
        reasons_str = ", ".join(f"{v} {k}" for k, v in skip_reasons.items())
        fh.write(f" ({reasons_str})")
    fh.write("\n")
    fh.write(f"- Candidate files (score > 0): {ss.get('candidate_files_above_score_0', 0)}\n")
    fh.write(f"- Candidate files (score ≥ 30): {ss.get('candidate_files_above_score_30', 0)}\n")
    fh.write(f"- Candidate files (score ≥ 60): {ss.get('candidate_files_above_score_60', 0)}\n\n")

    # Top directories
    top_dirs = gs.get("top_dirs", [])
    if top_dirs:
        fh.write("### Top Directories by PHP File Count\n\n")
        for d, c in top_dirs[:10]:
            fh.write(f"- `{d or '(root)'}`: {c} files\n")
        fh.write("\n")

    # Signal frequency table
    sig_table = gs.get("signal_frequency_table", [])
    if sig_table:
        fh.write("### Top Detected Signals\n\n")
        fh.write(
            "| Signal | Kind | Files | % of Candidates | FP Risk |\n"
            "|--------|------|------:|----------------:|---------|\n"
        )
        for row in sig_table[:20]:
            fh.write(
                f"| `{row['signal']}` | {row['kind']} "
                f"| {row['seen_in_files']} | {row['pct_of_candidates']:.1f}% "
                f"| {row.get('false_positive_risk', '-')} |\n"
            )
        fh.write("\n")

    # Envelope key frequency
    env_table = gs.get("envelope_key_frequency", [])
    if env_table:
        fh.write("### Envelope Key Frequency\n\n")
        fh.write("| Key | Files | % of Candidates |\n|-----|------:|----------------:|\n")
        for row in env_table:
            fh.write(
                f"| `{row['key']}` | {row['seen_in_files']} "
                f"| {row['pct_of_candidates']:.1f}% |\n"
            )
        fh.write("\n")


def _write_helper_registry(fh, gs: Dict[str, Any]) -> None:
    helpers = gs.get("custom_helper_registry", [])
    if not helpers:
        return
    fh.write("## Custom Helper Registry\n\n")
    fh.write(
        "| Helper | Defined In | Wraps Signal | Called In Files |\n"
        "|--------|-----------|-------------|----------------:|\n"
    )
    for h in helpers:
        fh.write(
            f"| `{h['helper_name']}` | `{h['defined_in']}` "
            f"| `{h['wraps_signal']}` | {h['seen_called_in_files']} |\n"
        )
    fh.write("\n")


def _write_top_candidates(
    fh, records: List[FileRecord], min_score: int
) -> None:
    fh.write("## Top Candidate Files\n\n")
    sorted_records = sorted(records, key=lambda r: r.score, reverse=True)
    visible = [r for r in sorted_records if not r.skipped and r.score >= min_score][:20]
    if not visible:
        fh.write("_No candidate files above the minimum score threshold._\n\n")
        return
    fh.write("| File | Score |\n|------|------:|\n")
    for r in visible:
        fh.write(f"| `{r.path}` | {r.score} |\n")
    fh.write("\n")


def _write_file_details(
    fh, records: List[FileRecord], min_score: int
) -> None:
    sorted_records = sorted(records, key=lambda r: r.score, reverse=True)

    for record in sorted_records:
        if record.skipped:
            continue
        if record.score < min_score:
            continue

        fh.write(f"### `{record.path}`\n\n")
        fh.write(f"**Framework:** `{record.framework}`  \n")
        fh.write(f"**Heuristic Score:** {record.score}/100\n\n")

        if record.encoding_note:
            fh.write(f"> Encoding note: {record.encoding_note}\n\n")

        # Score breakdown
        if record.score_breakdown:
            fh.write("**Score Breakdown:**\n\n")
            for item in record.score_breakdown:
                sign = "+" if item.delta >= 0 else ""
                loc = f" (line {item.line_no})" if item.line_no else ""
                fh.write(
                    f"- `{item.signal}` [{item.kind}]: "
                    f"{sign}{item.delta}{loc}\n"
                )
            fh.write("\n")

        # Matched signals
        has_signals = any(record.signals.get(k) for k in ("strong", "weak", "negative"))
        if has_signals:
            fh.write("**Matched Signals:**\n\n")
            for kind in ("strong", "weak", "negative"):
                sigs = record.signals.get(kind, [])
                if not sigs:
                    continue
                fh.write(f"- **{kind.capitalize()}:**\n")
                for s in sigs:
                    lines_str = (
                        f" (lines {', '.join(str(n) for n in s.line_nos[:5])})"
                        if s.line_nos else ""
                    )
                    fh.write(
                        f"  - `{s.name}` — {s.occurrences}x{lines_str}, "
                        f"global: {s.global_seen_in_files} files, "
                        f"FP risk: {s.false_positive_risk}\n"
                    )
            fh.write("\n")

        # Dynamic notes
        if record.dynamic_notes:
            fh.write("**Dynamic Pattern Notes:**\n\n")
            for note in record.dynamic_notes:
                fh.write(
                    f"- [{note.type}] Line {note.line_no}: {note.note}  \n"
                    f"  `{note.raw_line}`\n"
                )
            fh.write("\n")

        # Route hints
        if record.route_hints:
            fh.write("**Route Hints:**\n\n")
            for hint in record.route_hints:
                ctrl = f" → `{hint.controller_method}`" if hint.controller_method else ""
                src = f"`{hint.source_file}`:{hint.source_line}" if hint.source_line else hint.source_file
                fh.write(
                    f"- `{hint.method}` `{hint.uri}`{ctrl}  \n"
                    f"  Source: {src}, confidence: {hint.confidence}\n"
                )
            fh.write("\n")
        elif record.framework in ("laravel",):
            fh.write(
                "> Route hint: No route mapping found — file path used as fallback\n\n"
            )
        elif record.framework == "plain":
            fh.write(
                "> Route hint: No route parser available for Plain PHP — "
                "path is inferred from file location\n\n"
            )

        # Input params
        has_params = any(record.input_params.get(k) for k in ("get", "post", "request", "json_body"))
        if has_params:
            fh.write("**Parameter Hints:**\n\n")
            for source_key, label in (
                ("get", "$_GET"), ("post", "$_POST"),
                ("request", "$_REQUEST"), ("json_body", "JSON body"),
            ):
                params = record.input_params.get(source_key, [])
                if params:
                    keys_str = ", ".join(f"`{p.key}`" for p in params)
                    fh.write(f"- {label}: {keys_str}\n")
            fh.write("\n")

        # Method hints
        if record.method_hints:
            methods_str = ", ".join(
                f"`{h['method']}`" for h in record.method_hints
            )
            fh.write(f"**Request Method Hints:** {methods_str}\n\n")

        # Envelope keys
        if record.envelope_keys:
            keys_str = ", ".join(f"`{k.key}`" for k in record.envelope_keys)
            fh.write(f"**Output Envelope Hints:** {keys_str}\n\n")

        # Custom helpers called
        if record.custom_helpers_called:
            fh.write("**Custom Helpers Called:**\n\n")
            for ch in record.custom_helpers_called:
                fh.write(
                    f"- `{ch.name}()` at line {ch.line_no} → resolves to "
                    f"`{ch.resolved_to}` (depth {ch.wrap_depth})\n"
                )
            fh.write("\n")

        # Output snippets
        if record.output_points:
            fh.write("**Output Snippets:**\n")
            for op in record.output_points:
                fh.write(f"\n- **Kind:** `{op.kind}`, **Line:** {op.line_no}\n\n")
                fh.write("  ```php\n")
                for snippet_line in op.context_excerpt.splitlines():
                    fh.write(f"  {snippet_line}\n")
                fh.write("  ```\n")
            fh.write("\n")

        # Redaction notice
        if record.redaction_count > 0:
            fh.write(
                f"> Redaction: {record.redaction_count} value(s) redacted in snippets above.\n\n"
            )

        # Notes
        if record.notes:
            fh.write("**Notes:**\n\n")
            for note in record.notes:
                fh.write(f"- {note}\n")
            fh.write("\n")

        fh.write("---\n\n")
