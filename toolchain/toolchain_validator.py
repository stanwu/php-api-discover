"""toolchain_validator.py — Shared pattern.json validation module (V1–V13)

Used by both ToolB and ToolC.
Entry point: validate_pattern_json(pattern, global_stats) -> ValidationResult

V11 note: _-prefixed top-level keys are stripped silently BEFORE any validation.
_tool_b_meta must NEVER be present when this function is called.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

try:
    import jsonschema
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False

# ── JSON Schema for V1 structural validation ──────────────────────────────────

_SIGNAL_ITEM = {
    "type": "object",
    "required": ["name", "pattern", "weight", "kind"],
    "properties": {
        "name":    {"type": "string"},
        "pattern": {"type": "string"},
        "weight":  {"type": "integer"},
        "kind":    {"type": "string"},
    },
}

_ENVELOPE_TEMPLATE_ITEM = {
    "type": "object",
    "required": ["name"],
    "properties": {
        "name":        {"type": "string"},
        "keys_all_of": {"type": "array", "items": {"type": "string"}},
        "keys_any_of": {"type": "array", "items": {"type": "string"}},
        "example":     {"type": "object"},
    },
}

PATTERN_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "version", "source_jsonl_schema_version", "framework",
        "scoring", "endpoint_envelopes", "method_inference", "postman_defaults",
    ],
    "properties": {
        "version":                    {"type": "string"},
        "source_jsonl_schema_version": {"type": "string"},
        "framework": {
            "type": "string",
            "enum": ["laravel", "wordpress", "codeigniter", "symfony", "slim", "plain"],
        },
        "scoring": {
            "type": "object",
            "required": ["strong_signals", "weak_signals", "negative_signals", "thresholds"],
            "properties": {
                "strong_signals":   {"type": "array", "items": _SIGNAL_ITEM},
                "weak_signals":     {"type": "array", "items": _SIGNAL_ITEM},
                "negative_signals": {"type": "array", "items": _SIGNAL_ITEM},
                "thresholds": {
                    "type": "object",
                    "required": ["endpoint", "uncertain"],
                    "properties": {
                        "endpoint": {"type": "integer"},
                        "uncertain": {"type": "integer"},
                    },
                },
            },
        },
        "endpoint_envelopes": {
            "type": "object",
            "required": ["templates"],
            "properties": {
                "templates": {"type": "array", "items": _ENVELOPE_TEMPLATE_ITEM},
            },
        },
        "method_inference": {
            "type": "object",
            "required": ["priority_order", "rules", "default_method"],
            "properties": {
                "priority_order": {"type": "array", "items": {"type": "string"}},
                "rules":          {"type": "array"},
                "default_method": {"type": "string"},
            },
        },
        "postman_defaults": {
            "type": "object",
            "required": [
                "collection_name", "base_url_variable",
                "auth_token_variable", "default_headers", "auth_header",
            ],
            "properties": {
                "collection_name":              {"type": "string"},
                "base_url_variable":            {"type": "string"},
                "auth_token_variable":          {"type": "string"},
                "default_headers":              {"type": "array"},
                "auth_header":                  {"type": "object"},
                "generate_folder_per_directory": {"type": "boolean"},
                "include_pre_request_script":   {"type": "boolean"},
                "include_test_script":          {"type": "boolean"},
            },
        },
    },
}


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    valid:    bool
    errors:   list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.valid = False
        self.errors.append(msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


# ── Public entry point ────────────────────────────────────────────────────────

def validate_pattern_json(
    pattern: dict[str, Any],
    global_stats: dict[str, Any] | None = None,
) -> ValidationResult:
    """
    Validate a pattern.json dict against rules V1–V13.

    Args:
        pattern:      The parsed pattern.json dict (may contain _-prefixed keys).
        global_stats: The global_stats object from features_raw.jsonl line 0.
                      Required for V6, V8, V12; skipped if None.

    Returns:
        ValidationResult with .valid, .errors (hard failures), .warnings (soft).
    """
    result = ValidationResult(valid=True)

    # ── V11: Strip _-prefixed top-level keys BEFORE any validation (silent) ──
    clean: dict[str, Any] = {k: v for k, v in pattern.items() if not k.startswith("_")}

    # ── V1: JSON schema structural validation ─────────────────────────────────
    if _HAS_JSONSCHEMA:
        try:
            jsonschema.validate(clean, PATTERN_JSON_SCHEMA)
        except jsonschema.ValidationError as exc:
            result.add_error(f"V1 Schema validation: {exc.message} (path: {list(exc.absolute_path)})")
            return result  # can't meaningfully continue
        except jsonschema.SchemaError as exc:
            result.add_error(f"V1 Internal schema error: {exc.message}")
            return result
    else:
        # Minimal fallback without jsonschema
        required = [
            "version", "source_jsonl_schema_version", "framework",
            "scoring", "endpoint_envelopes", "method_inference", "postman_defaults",
        ]
        for key in required:
            if key not in clean:
                result.add_error(f"V1 Missing required top-level field: '{key}'")
        if not result.valid:
            return result

    # ── V13: source_jsonl_schema_version (warning only) ──────────────────────
    sjsv = clean.get("source_jsonl_schema_version")
    if sjsv != "2.0":
        result.add_warning(f"V13 source_jsonl_schema_version is {sjsv!r}, expected '2.0'")

    # ── Extract commonly used sub-structures ──────────────────────────────────
    scoring    = clean.get("scoring", {})
    thresholds = scoring.get("thresholds", {})
    endpoint   = thresholds.get("endpoint")
    uncertain  = thresholds.get("uncertain")
    strong     = scoring.get("strong_signals",   [])
    weak       = scoring.get("weak_signals",     [])
    negative   = scoring.get("negative_signals", [])
    all_signals = strong + weak + negative

    # ── V2: All regex patterns must compile ──────────────────────────────────
    for sig in all_signals:
        pat = sig.get("pattern", "")
        try:
            re.compile(pat)
        except re.error as exc:
            result.add_error(
                f"V2 Regex compile error for signal '{sig.get('name')}': {exc}"
            )

    # ── V3: thresholds.uncertain < thresholds.endpoint ───────────────────────
    if isinstance(endpoint, int) and isinstance(uncertain, int):
        if uncertain >= endpoint:
            result.add_error(
                f"V3 thresholds.uncertain ({uncertain}) must be strictly less than "
                f"thresholds.endpoint ({endpoint})"
            )

    # ── V4: Negative signal weights must be negative integers ─────────────────
    for sig in negative:
        w = sig.get("weight")
        if not isinstance(w, int) or w >= 0:
            result.add_error(
                f"V4 Negative signal '{sig.get('name')}' has invalid weight {w!r} "
                f"(must be a negative integer)"
            )

    # ── V5: Positive signal weights must be positive integers ─────────────────
    for sig in strong + weak:
        w = sig.get("weight")
        if not isinstance(w, int) or w <= 0:
            result.add_error(
                f"V5 Signal '{sig.get('name')}' has invalid weight {w!r} "
                f"(must be a positive integer)"
            )

    # ── V6: Signal names must appear in JSONL evidence ───────────────────────
    if global_stats is not None:
        known: set[str] = set()
        for entry in global_stats.get("signal_frequency_table", []):
            known.add(entry.get("signal", ""))
        for entry in global_stats.get("custom_helper_registry", []):
            known.add(entry.get("name", ""))

        for sig in all_signals:
            name = sig.get("name", "")
            if name and name not in known:
                result.add_error(
                    f"V6 Signal name '{name}' not found in JSONL "
                    f"signal_frequency_table or custom_helper_registry"
                )

    # ── V7: envelope.example keys must be subset of keys_all_of ∪ keys_any_of ─
    templates = clean.get("endpoint_envelopes", {}).get("templates", [])
    for tmpl in templates:
        allowed = set(tmpl.get("keys_all_of", [])) | set(tmpl.get("keys_any_of", []))
        example = tmpl.get("example", {})
        if isinstance(example, dict):
            for k in example:
                if k not in allowed:
                    result.add_error(
                        f"V7 Envelope example key '{k}' in template "
                        f"'{tmpl.get('name', '?')}' is not in keys_all_of or keys_any_of"
                    )

    # ── V8: framework should match JSONL (warning only) ──────────────────────
    if global_stats is not None:
        detected = global_stats.get("framework", {}).get("detected")
        pattern_fw = clean.get("framework")
        if detected and pattern_fw and detected != pattern_fw:
            result.add_warning(
                f"V8 pattern.json framework '{pattern_fw}' does not match "
                f"JSONL detected framework '{detected}'"
            )

    # ── V9: Template names must be unique ────────────────────────────────────
    names = [t.get("name") for t in templates if t.get("name")]
    if len(names) != len(set(names)):
        result.add_error("V9 Duplicate template names in endpoint_envelopes.templates")

    # ── V10: priority_order must end with "default" ───────────────────────────
    priority = clean.get("method_inference", {}).get("priority_order", [])
    if not priority or priority[-1] != "default":
        result.add_error(
            "V10 method_inference.priority_order must end with 'default'"
        )

    # ── V12: Threshold gap must meet minimum (warning only) ──────────────────
    if global_stats is not None and isinstance(endpoint, int) and isinstance(uncertain, int):
        hints   = global_stats.get("pattern_json_generation_hints", {})
        min_gap = hints.get("minimum_threshold_gap", 10)
        gap     = endpoint - uncertain
        if gap < min_gap:
            result.add_warning(
                f"V12 Threshold gap ({gap}) is less than minimum required gap "
                f"({min_gap}) from JSONL generation hints"
            )

    return result
