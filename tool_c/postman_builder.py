"""tool_c.postman_builder — Builds Postman Collection v2.1 structures.

Handles:
  - Body generation (raw JSON / urlencoded / none)
  - Query parameter generation for GET
  - Folder grouping (flat or by_directory)
  - Pre-request / test scripts
  - Secret redaction delegation
  - Stable sort: file path → method → uri
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tool_c.classifier import ClassifiedFile
from tool_c.envelope_matcher import match_envelope
from tool_c.method_inferrer import MethodResult, infer_methods
from tool_c.redactor import param_placeholder, redact_body


# ── Public entry point ────────────────────────────────────────────────────────

def build_collection(
    classified_files: list[ClassifiedFile],
    pattern: dict[str, Any],
    folder_structure: str = "flat",
    include_uncertain: bool = False,
    source_jsonl: str = "",
) -> dict[str, Any]:
    """Build a Postman Collection v2.1 document."""
    defaults = pattern["postman_defaults"]
    base_url_var = defaults.get("base_url_variable", "baseUrl")
    auth_token_var = defaults.get("auth_token_variable", "authToken")
    collection_name = defaults.get("collection_name", "API Collection")

    # ── Collect all items (pre-sort) ──────────────────────────────────────────
    raw_items: list[dict[str, Any]] = []

    for cf in classified_files:
        if cf.tier == "L3":
            continue
        if cf.tier == "L2" and not include_uncertain:
            continue

        envelope_template = match_envelope(cf.file_record, pattern)
        method_results = infer_methods(cf.file_record, pattern)
        # Sort methods alphabetically, then by uri
        method_results.sort(key=lambda m: (m.method, m.uri))

        for mr in method_results:
            item = _build_item(
                cf, mr, envelope_template, pattern, base_url_var, auth_token_var
            )
            raw_items.append(item)

    # ── Disambiguate duplicate names ──────────────────────────────────────────
    name_count: Counter[str] = Counter(i["name"] for i in raw_items)
    name_occurrence: dict[str, int] = {}
    for item in raw_items:
        name = item["name"]
        if name_count[name] > 1:
            name_occurrence[name] = name_occurrence.get(name, 0) + 1
            item["name"] = f"{name} [{name_occurrence[name]}]"

    # ── Structure items ───────────────────────────────────────────────────────
    if folder_structure == "by_directory":
        items = _group_by_directory(raw_items)
    else:
        items = raw_items

    # ── Assemble collection ───────────────────────────────────────────────────
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    collection: dict[str, Any] = {
        "info": {
            "name": collection_name,
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            "_tool_c_generated": True,
            "_source_jsonl_schema_version": "2.0",
            "_generated_at": now,
            "_framework": pattern.get("framework", ""),
            "_pattern_json_version": pattern.get("version", ""),
        },
        "variable": [
            {"key": base_url_var, "value": "", "type": "string"},
            {"key": auth_token_var, "value": "", "type": "string"},
        ],
        "item": items,
    }
    return collection


# ── Item builder ──────────────────────────────────────────────────────────────

def _build_item(
    cf: ClassifiedFile,
    mr: MethodResult,
    envelope_template: dict[str, Any] | None,
    pattern: dict[str, Any],
    base_url_var: str,
    auth_token_var: str,
) -> dict[str, Any]:
    defaults = pattern["postman_defaults"]
    auth_header = defaults.get("auth_header", {})
    default_headers: list[dict[str, Any]] = list(defaults.get("default_headers", []))
    include_pre = defaults.get("include_pre_request_script", False)
    include_test = defaults.get("include_test_script", False)

    method = mr.method.upper()
    uri = mr.uri
    file_path = cf.file_record.get("path", "")

    # Item name
    controller = mr.controller_method
    if controller:
        item_name = f"{method} {uri} ({controller})"
    else:
        item_name = f"{method} {uri}"

    # Headers
    headers: list[dict[str, Any]] = []
    for h in default_headers:
        headers.append({
            "key": h.get("key", ""),
            "value": h.get("value", ""),
            "type": "text",
            "disabled": h.get("disabled", False),
        })
    # Auth header
    auth_key = auth_header.get("key", "Authorization")
    auth_value = auth_header.get("value_template", f"Bearer {{{{{auth_token_var}}}}}")
    headers.append({"key": auth_key, "value": auth_value, "type": "text", "disabled": False})

    # Body + Content-Type header
    body_obj, body_redacted = _build_body(cf.file_record, method)
    if body_obj is not None and method in ("POST", "PUT", "PATCH"):
        if body_obj.get("mode") == "raw":
            headers.append({
                "key": "Content-Type", "value": "application/json",
                "type": "text", "disabled": False,
            })

    # URL
    url_obj = _build_url(uri, base_url_var, method, cf.file_record)

    # Response example
    response_body_str, resp_redacted = _build_response_example_body(envelope_template)
    response_item_name = (
        f"Example Response (template: {envelope_template['name']})"
        if envelope_template else "Example Response"
    )
    response: list[dict[str, Any]] = [
        {
            "name": response_item_name,
            "originalRequest": {"method": method, "url": {"raw": url_obj["raw"]}},
            "status": "OK",
            "code": 200,
            "header": [{"key": "Content-Type", "value": "application/json"}],
            "body": response_body_str,
        }
    ]

    # Redaction tracking
    redaction_applied = body_redacted or resp_redacted

    # _tool_c_meta
    no_envelope_match = envelope_template is None
    meta: dict[str, Any] = {
        "source_file": file_path,
        "confidence_tier": cf.tier,
        "toolc_score": cf.toolc_score,
        "toola_score": cf.toola_score,
        "score_divergence_warning": cf.score_divergence_warning,
        "method_inference_source": mr.inference_source,
        "route_hint_source": mr.route_source if mr.inference_source == "route_hints" else None,
        "matched_envelope_template": envelope_template["name"] if envelope_template else None,
        "no_envelope_match": no_envelope_match,
        "dynamic_notes": cf.file_record.get("dynamic_notes", []),
        "redaction_applied": redaction_applied,
    }

    item: dict[str, Any] = {
        "name": item_name,
        "request": {
            "method": method,
            "header": headers,
            "url": url_obj,
        },
        "response": response,
        "_tool_c_meta": meta,
    }

    if body_obj is not None:
        item["request"]["body"] = body_obj

    # Scripts
    event: list[dict[str, Any]] = []
    if include_pre:
        event.append({
            "listen": "prerequest",
            "script": {
                "exec": [
                    "// Auto-generated by ToolC — do not add business logic here",
                    "console.log('[ToolC] Requesting: ' + pm.info.requestName);",
                ],
                "type": "text/javascript",
            },
        })
    if include_test:
        event.append({
            "listen": "test",
            "script": {
                "exec": [
                    "// Auto-generated by ToolC",
                    'pm.test("Status is 2xx", function () {',
                    "    pm.expect(pm.response.code).to.be.oneOf([200, 201, 204]);",
                    "});",
                ],
                "type": "text/javascript",
            },
        })
    if event:
        item["event"] = event

    return item


# ── Body generation ───────────────────────────────────────────────────────────

def _build_body(
    file_record: dict[str, Any],
    method: str,
) -> tuple[dict[str, Any] | None, bool]:
    """Build Postman request body object.

    Returns (body_obj_or_None, was_redacted).
    """
    if method in ("GET", "DELETE"):
        return None, False

    params = file_record.get("input_params", {})
    json_body_params: list[dict[str, Any]] = params.get("json_body", [])
    post_params: list[dict[str, Any]] = params.get("post", [])

    if json_body_params:
        skeleton: dict[str, object] = {}
        redacted_flag = False
        for p in json_body_params:
            key = p.get("key", "")
            val = param_placeholder(key, redact_if_secret=True)
            if val == "REDACTED":
                redacted_flag = True
            skeleton[key] = val
        raw_str = json.dumps(skeleton, indent=2)
        # Apply string-level redaction too (catches nested patterns)
        raw_str, str_redacted = redact_body(raw_str)
        body_obj = {
            "mode": "raw",
            "raw": raw_str,
            "options": {"raw": {"language": "json"}},
        }
        return body_obj, redacted_flag or str_redacted

    if post_params:
        urlencoded = []
        for p in post_params:
            key = p.get("key", "")
            value = param_placeholder(key, redact_if_secret=True)
            urlencoded.append({
                "key": key,
                "value": str(value) if not isinstance(value, str) else value,
                "type": "text",
            })
        return {"mode": "urlencoded", "urlencoded": urlencoded}, False

    # No params
    body_obj = {
        "mode": "raw",
        "raw": "{}",
        "options": {"raw": {"language": "json"}},
        "_note": "no params extracted",
    }
    return body_obj, False


# ── URL builder ───────────────────────────────────────────────────────────────

def _build_url(
    uri: str,
    base_url_var: str,
    method: str,
    file_record: dict[str, Any],
) -> dict[str, Any]:
    base_placeholder = f"{{{{{base_url_var}}}}}"
    raw = f"{base_placeholder}{uri}"
    path_segments = [seg for seg in uri.lstrip("/").split("/") if seg]

    url_obj: dict[str, Any] = {
        "raw": raw,
        "host": [base_placeholder],
        "path": path_segments,
        "query": [],
    }

    # Query params for GET
    if method == "GET":
        get_params = file_record.get("input_params", {}).get("get", [])
        url_obj["query"] = [
            {"key": p.get("key", ""), "value": "", "disabled": False}
            for p in get_params
        ]

    return url_obj


# ── Response example body ─────────────────────────────────────────────────────

def _build_response_example_body(
    envelope_template: dict[str, Any] | None,
) -> tuple[str, bool]:
    """Build the response example body string.

    Returns (body_json_str, was_redacted).
    """
    if envelope_template is None:
        return "{}", False

    example = envelope_template.get("example", {})
    body_str = json.dumps(example, indent=2)
    redacted, was_redacted = redact_body(body_str)
    return redacted, was_redacted


# ── Folder grouping ───────────────────────────────────────────────────────────

def _group_by_directory(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group items into Postman folder objects by directory path."""
    folders: dict[str, list[dict[str, Any]]] = {}

    for item in items:
        meta = item.get("_tool_c_meta", {})
        file_path = meta.get("source_file", "")
        parent = str(Path(file_path).parent) if file_path else ""
        folder_name = "(root)" if (parent == "." or parent == "") else parent
        folders.setdefault(folder_name, []).append(item)

    result: list[dict[str, Any]] = []
    for folder_name in sorted(folders.keys()):
        result.append({
            "name": folder_name,
            "item": folders[folder_name],
        })
    return result
