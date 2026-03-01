"""prompt_assembler.py — Assemble the full AI agent prompt from JSONL evidence."""

from __future__ import annotations

from typing import Any

# ── Static blocks ─────────────────────────────────────────────────────────────

_SYSTEM_BLOCK = """\
You are a senior API analyst. Your task is to generate a pattern.json configuration file
for a tool called ToolC, which classifies PHP API endpoints and generates Postman collections.

You will be given structured evidence extracted from a PHP codebase by ToolA.
Your output must be a single valid JSON object conforming exactly to the schema provided.
Do not output anything other than the JSON object. No prose, no explanation, no markdown fences.\
"""

_TOOLC_SCHEMA_BLOCK = """\
## Target Schema: pattern.json

The output must be a JSON object with exactly these fields. Constraints are mandatory.

{
  "version": "1.0",
  "source_jsonl_schema_version": "2.0",   // MUST be exactly "2.0"
  "framework": "<detected_framework>",     // MUST match: laravel|wordpress|codeigniter|symfony|slim|plain

  "scoring": {
    "strong_signals": [
      // Each entry:
      // - name: MUST appear in signal_frequency_table or custom_helper_registry below
      // - pattern: valid Python regex matching the signal
      // - weight: integer 1-50
      // - kind: MUST be "strong"
      // Include ONLY signals with false_positive_risk "low" or "medium" AND seen_in_files >= 5
    ],
    "weak_signals": [
      // weight: integer 1-20, kind: MUST be "weak"
      // Include signals with medium/high false_positive_risk that still provide evidence
    ],
    "negative_signals": [
      // weight: integer -50 to -1 (MUST be negative), kind: MUST be "negative"
      // Include signals that strongly indicate non-API files (HTML, view rendering, etc.)
    ],
    "thresholds": {
      "endpoint": <integer>,    // Suggested: see pattern_json_generation_hints.recommended_endpoint_threshold
      "uncertain": <integer>    // MUST be strictly less than endpoint
    }
  },

  "endpoint_envelopes": {
    "templates": [
      // Base on envelope_key_frequency evidence only
      // keys_all_of: keys that ALWAYS appear together (use only keys with high co-occurrence)
      // keys_any_of: at least one of these must be present
      // example: object with ONLY keys from keys_all_of + keys_any_of as keys
      //          values: "" (string), 0 (number), true (boolean), null, {}, []
      //          DO NOT invent domain-specific field values
    ]
  },

  "method_inference": {
    "priority_order": ["route_hints", "request_method_check", "input_param_type", "signal_based", "default"],
    "rules": [
      // signal_based rules only - other sources handled automatically
      // Include rules ONLY for signals with clear method implications (e.g. wp_ajax -> POST)
    ],
    "default_method": "GET"    // or "POST" - choose based on codebase evidence
  },

  "postman_defaults": {
    "collection_name": "{collection_name}",
    "base_url_variable": "{base_url_variable}",
    "auth_token_variable": "authToken",
    "default_headers": [
      { "key": "Accept", "value": "application/json", "disabled": false }
    ],
    "auth_header": {
      "key": "Authorization",
      "value_template": "Bearer {{authToken}}"
    },
    "generate_folder_per_directory": false,
    "include_pre_request_script": false,
    "include_test_script": false
  }
}\
"""

_RULES_BLOCK = """\
## Generation Rules (MANDATORY)

R1. EVIDENCE-ONLY: Only include signals that appear in the Signal Frequency Table or
    Custom Helper Registry above. Do not invent signal names.

R2. WEIGHT CALIBRATION:
    - seen_in_files > 30 AND false_positive_risk=low   -> weight range 25-40
    - seen_in_files 10-30 AND false_positive_risk=low  -> weight range 15-25
    - seen_in_files < 10 OR false_positive_risk=medium -> weight range 5-15
    - false_positive_risk=high                         -> use as weak signal only (weight <= 10)

R3. THRESHOLD CALIBRATION:
    - Start from recommended_endpoint_threshold in generation hints
    - Adjust only if human notes specify otherwise
    - uncertain threshold MUST be < endpoint threshold
    - Minimum gap between uncertain and endpoint: 10 points

R4. ENVELOPE TEMPLATES:
    - Only create a template if at least 2 keys appear together in >= 10% of candidate files
    - keys_all_of must have >= 2 entries
    - keys_any_of must have >= 1 entry
    - example object values: use typed placeholders only (see schema)

R5. METHOD INFERENCE RULES:
    - Only add signal_based rules for signals with unambiguous method implications
    - WordPress wp_ajax signals -> POST (always)
    - Laravel route_hints will handle most Laravel cases automatically (no signal_based rule needed)

R6. NO HALLUCINATION:
    - Do not add signals not present in the evidence
    - Do not add envelope keys not present in envelope_key_frequency
    - Do not invent HTTP method mappings not supported by evidence

R7. CONSERVATIVE DEFAULTS:
    - If uncertain about a weight, use the lower end of the range
    - If uncertain about threshold, use the JSONL hint value
    - If no clear envelope pattern, output an empty templates array []

R8. CO-OCCURRENCE DEDUPLICATION:
    - If two signals always appear together (see co-occurrence patterns), include only
      the stronger one as strong_signal; demote the other to weak or omit\
"""

_OUTPUT_FORMAT_BLOCK = """\
## Output Format

Output ONLY a single valid JSON object. No markdown code fences. No prose before or after.
The JSON must be parseable by Python's json.loads() without any preprocessing.

The output will be machine-validated against the ToolC pattern.json schema immediately
after you respond. Validation errors will cause the process to fail.

Begin your response with { and end with }.\
"""


# ── Dynamic evidence block ────────────────────────────────────────────────────

def _fmt_signal_table(signals: list[dict]) -> str:
    rows = []
    rows.append(
        "| Signal | Kind | Seen In Files | % of Candidates "
        "| False Positive Risk | Risk Reason |"
    )
    rows.append("|--------|------|---------------|-----------------|---------------------|-------------|")
    for s in signals:
        rows.append(
            f"| {s.get('signal','')} "
            f"| {s.get('kind','')} "
            f"| {s.get('seen_in_files',0)} "
            f"| {s.get('pct_of_candidates',0):.1f}% "
            f"| {s.get('false_positive_risk','')} "
            f"| {s.get('false_positive_risk_reason','')} |"
        )
    return "\n".join(rows)


def _fmt_helper_table(helpers: list[dict]) -> str:
    if not helpers:
        return "No custom helpers detected."
    rows = []
    rows.append(
        "| Helper Name | Wraps Signal | Called In Files "
        "| % of Candidates | Suggested Kind | Suggested Weight |"
    )
    rows.append("|-------------|--------------|-----------------|-----------------|----------------|-----------------|")
    for h in helpers:
        rows.append(
            f"| {h.get('name','')} "
            f"| {h.get('wraps_signal','')} "
            f"| {h.get('seen_called_in_files', h.get('seen_in_files',0))} "
            f"| {h.get('pct_of_candidates',0):.1f}% "
            f"| {h.get('suggested_kind','')} "
            f"| {h.get('suggested_weight','')} |"
        )
    return "\n".join(rows)


def _fmt_envelope_table(env_keys: list[dict]) -> str:
    rows = []
    rows.append("| Key | Seen In Files | % of Candidates |")
    rows.append("|-----|---------------|-----------------||")
    for e in env_keys[:10]:
        rows.append(
            f"| {e.get('key','')} "
            f"| {e.get('seen_in_files',0)} "
            f"| {e.get('pct_of_candidates',0):.1f}% |"
        )
    return "\n".join(rows)


def _fmt_method_dist(method_dist: dict) -> str:
    if not method_dist:
        return "No method distribution data."
    rows = ["| Method | Count |", "|--------|-------|"]
    for method, count in sorted(method_dist.items()):
        rows.append(f"| {method} | {count} |")
    return "\n".join(rows)


def _fmt_file_record(rec: dict) -> str:
    path  = rec.get("path", "?")
    score = rec.get("score", 0)

    strong   = rec.get("signals", {}).get("strong",   [])
    weak     = rec.get("signals", {}).get("weak",     [])
    negative = rec.get("signals", {}).get("negative", [])

    strong_str   = ", ".join(f"{s['name']}x{s.get('occurrences',1)}" for s in strong)   or "none"
    weak_str     = ", ".join(f"{s['name']}x{s.get('occurrences',1)}" for s in weak)     or "none"
    negative_str = ", ".join(s["name"] for s in negative)                                or "none"

    routes = rec.get("route_hints", [])
    route_str = ", ".join(
        f"{r.get('method','?')} {r.get('uri','?')} ({r.get('source_file','?')}:{r.get('source_line',0)}) [{r.get('confidence','?')}]"
        for r in routes
    ) or "none"

    inp = rec.get("input_params", {})
    get_params  = ", ".join(p["key"] for p in inp.get("get",  []))  or "none"
    post_params = ", ".join(p["key"] for p in inp.get("post", []))  or "none"
    json_params = ", ".join(p["key"] for p in inp.get("json_body", [])) or "none"

    env_keys = ", ".join(e["key"] for e in rec.get("envelope_keys", [])) or "none"

    method_hints = rec.get("method_hints", [])
    mh_str = ", ".join(
        f"{m.get('method','?')} via {m.get('evidence','?')}" for m in method_hints
    ) or "none"

    helpers = ", ".join(h.get("name","?") for h in rec.get("custom_helpers_called", [])) or "none"
    notes   = "; ".join(n.get("note","") for n in rec.get("dynamic_notes", []))          or "none"

    return (
        f"---\n"
        f"File: {path}\n"
        f"ToolA Score: {score}\n"
        f"Strong signals: {strong_str}\n"
        f"Weak signals:   {weak_str}\n"
        f"Negative signals: {negative_str}\n"
        f"Route hints: {route_str}\n"
        f"Input params (GET): {get_params}\n"
        f"Input params (POST): {post_params}\n"
        f"Input params (json_body): {json_params}\n"
        f"Envelope keys: {env_keys}\n"
        f"Method hints: {mh_str}\n"
        f"Custom helpers called: {helpers}\n"
        f"Dynamic notes: {notes}\n"
        f"---"
    )


def _build_evidence_block(
    global_stats: dict,
    selected_signals: list[dict],
    selected_files: list[dict],
    max_signals: int,
    max_files: int,
) -> str:
    fw      = global_stats.get("framework", {})
    summary = global_stats.get("scan_summary", {})
    hints   = global_stats.get("pattern_json_generation_hints", {})
    score_dist = hints.get("score_distribution_summary", {})
    co_occ  = global_stats.get("co_occurrence_patterns", [])

    fw_evidence = ", ".join(fw.get("evidence", []))

    signal_table  = _fmt_signal_table(selected_signals)
    helper_table  = _fmt_helper_table(global_stats.get("custom_helper_registry", []))
    envelope_table = _fmt_envelope_table(global_stats.get("envelope_key_frequency", []))
    method_table  = _fmt_method_dist(global_stats.get("method_distribution", {}))

    co_occ_lines = "\n".join(
        f"- Signals: {', '.join(p.get('signals',[]))} | Files: {p.get('files_count',0)} | Note: {p.get('note','')}"
        for p in co_occ
    ) or "None detected."

    rec_strong   = ", ".join(hints.get("recommended_strong_signals",   []))
    rec_weak     = ", ".join(hints.get("recommended_weak_signals",     []))
    rec_negative = ", ".join(hints.get("recommended_negative_signals", []))
    rec_env      = hints.get("recommended_envelope_template", {})

    file_records_str = "\n\n".join(_fmt_file_record(r) for r in selected_files)

    return f"""\
## Codebase Evidence (from ToolA v2 scan)

### Global Statistics

Framework: {fw.get('detected','unknown')} (confidence: {fw.get('confidence','?')})
Evidence: {fw_evidence}

Files scanned: {summary.get('total_files_scanned',0)}
Files skipped: {summary.get('total_files_skipped',0)}
Candidates above score  0: {summary.get('candidate_files_above_score_0',0)}
Candidates above score 30: {summary.get('candidate_files_above_score_30',0)}
Candidates above score 60: {summary.get('candidate_files_above_score_60',0)}

### Signal Frequency Table (top {len(selected_signals)} of {max_signals} max by seen_in_files)

{signal_table}

### Custom Helper Registry

{helper_table}

### Envelope Key Frequency (top 10)

{envelope_table}

### Signal Co-occurrence Patterns

{co_occ_lines}

### HTTP Method Distribution

{method_table}

### Score Distribution (across all candidate files with score > 0)

p25={score_dist.get('p25','?')}  p50={score_dist.get('p50','?')}
p75={score_dist.get('p75','?')}  p90={score_dist.get('p90','?')}
Note: {score_dist.get('note','')}

Use these percentiles to sanity-check threshold placement:
- A good endpoint threshold sits between p50 and p75
- A good uncertain threshold sits between p25 and p50

### Pattern.json Generation Hints (from ToolA — based on actual score distribution)

Recommended strong signals:   {rec_strong}
Recommended weak signals:     {rec_weak}
Recommended negative signals: {rec_negative}

Recommended endpoint threshold : {hints.get('recommended_endpoint_threshold','?')}
Basis: {hints.get('endpoint_threshold_basis','')}

Recommended uncertain threshold: {hints.get('recommended_uncertain_threshold','?')}
Basis: {hints.get('uncertain_threshold_basis','')}

Minimum required threshold gap : {hints.get('minimum_threshold_gap', 10)}
Note: {hints.get('minimum_threshold_gap_note','')}

Recommended envelope template keys_all_of: {rec_env.get('keys_all_of',[])}
Recommended envelope template keys_any_of: {rec_env.get('keys_any_of',[])}

WARNING: {hints.get('warning','')}

### Representative File Records ({len(selected_files)} examples)

Selection strategy: top-scoring files by ToolA score (diverse across score ranges).

{file_records_str}\
"""


# ── Public entry point ────────────────────────────────────────────────────────

def assemble_prompt(
    global_stats: dict,
    selected_signals: list[dict],
    selected_files: list[dict],
    *,
    collection_name: str = "API Collection",
    base_url_variable: str = "baseUrl",
    human_notes: str = "",
    max_signals: int = 50,
    max_files: int = 20,
) -> str:
    """
    Build the complete AI agent prompt.

    Returns a single string that is entirely self-contained.
    """
    fw      = global_stats.get("framework", {})
    summary = global_stats.get("scan_summary", {})

    task_block = (
        f"## Task\n\n"
        f"Analyze the PHP codebase evidence below and produce a `pattern.json` file that:\n\n"
        f"1. Defines scoring signals (strong/weak/negative) calibrated to THIS specific codebase\n"
        f"2. Sets classification thresholds based on observed signal distributions\n"
        f"3. Defines response envelope templates based on observed envelope key patterns\n"
        f"4. Configures HTTP method inference rules appropriate for the detected framework\n"
        f"5. Provides conservative, evidence-based values — do not invent signals not present in the evidence\n\n"
        f"Framework detected: {fw.get('detected','unknown')}\n"
        f"Total files scanned: {summary.get('total_files_scanned',0)}\n"
        f"Candidate endpoint files: {summary.get('candidate_files_above_score_30',0)}"
    )

    schema_block = _TOOLC_SCHEMA_BLOCK.replace(
        '"{collection_name}"', f'"{collection_name}"'
    ).replace(
        '"{base_url_variable}"', f'"{base_url_variable}"'
    )

    evidence_block = _build_evidence_block(
        global_stats, selected_signals, selected_files, max_signals, max_files
    )

    parts = [
        _SYSTEM_BLOCK,
        "",
        task_block,
        "",
        schema_block,
        "",
        evidence_block,
    ]

    if human_notes:
        truncated = human_notes[:3000]
        parts += [
            "",
            "## Human Reviewer Notes",
            "",
            "The following notes were added by the human reviewer after examining features_report.md.",
            "These notes OVERRIDE automated evidence when there is a conflict.",
            "Treat these as authoritative corrections.",
            "",
            truncated,
            "",
            "If the notes reference signals to EXCLUDE, set their weight to 0 and omit them from the output.",
            "If the notes reference custom threshold adjustments, apply them directly.",
        ]

    parts += [
        "",
        _RULES_BLOCK,
        "",
        _OUTPUT_FORMAT_BLOCK,
    ]

    return "\n".join(parts)
