"""tool_c.method_inferrer — HTTP method inference with multi-source priority.

Priority order (driven by pattern.json method_inference.priority_order):
  1. route_hints         (highest — confidence=high only)
  2. request_method_check
  3. input_param_type
  4. signal_based
  5. default             (lowest)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class MethodResult:
    method: str
    uri: str
    inference_source: str
    route_source: str | None = None      # "routes/api.php:14" or None
    confidence: str = "inferred"
    controller_method: str | None = None  # "UserController@store" or None


def infer_methods(
    file_record: dict[str, Any],
    pattern: dict[str, Any],
) -> list[MethodResult]:
    """Return one or more MethodResult for a file.

    Multiple results are emitted for multi-route files or conflicting param types.
    Results are NOT yet sorted here — caller sorts by (method, uri).
    """
    priority_order: list[str] = pattern["method_inference"].get(
        "priority_order",
        ["route_hints", "request_method_check", "input_param_type", "signal_based", "default"],
    )

    for source in priority_order:
        if source == "route_hints":
            results = _try_route_hints(file_record)
            if results:
                return results

        elif source == "request_method_check":
            result = _try_request_method_check(file_record)
            if result:
                return [result]

        elif source == "input_param_type":
            results = _try_input_param_type(file_record)
            if results:
                return results

        elif source == "signal_based":
            result = _try_signal_based(file_record, pattern)
            if result:
                return [result]

        elif source == "default":
            return [_use_default(file_record, pattern)]

    # Should not reach here when "default" is in priority_order
    return [_use_default(file_record, pattern)]


# ── Source helpers ─────────────────────────────────────────────────────────────

def _try_route_hints(file_record: dict[str, Any]) -> list[MethodResult]:
    """Source 1: high-confidence route_hints."""
    hints = file_record.get("route_hints", [])
    high = [h for h in hints if h.get("confidence") == "high"]
    if not high:
        return []

    results: list[MethodResult] = []
    for hint in high:
        method = (hint.get("method") or "GET").upper()
        if method == "UNKNOWN":
            method = "GET"
        uri = hint.get("uri") or _file_uri(file_record)
        src_file = hint.get("source_file", "")
        src_line = hint.get("source_line", 0)
        route_src = f"{src_file}:{src_line}" if src_file else None
        results.append(
            MethodResult(
                method=method,
                uri=uri,
                inference_source="route_hints",
                route_source=route_src,
                confidence="high",
                controller_method=hint.get("controller_method"),
            )
        )
    return results


def _try_request_method_check(file_record: dict[str, Any]) -> MethodResult | None:
    """Source 2: $_SERVER['REQUEST_METHOD'] checks in method_hints."""
    for hint in file_record.get("method_hints", []):
        evidence = hint.get("evidence", "")
        if "REQUEST_METHOD" in evidence or "$_SERVER" in evidence:
            method = (hint.get("method") or "").upper()
            if method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                return MethodResult(
                    method=method,
                    uri=_file_uri(file_record),
                    inference_source="request_method_check",
                    confidence="medium",
                )
    return None


def _try_input_param_type(file_record: dict[str, Any]) -> list[MethodResult]:
    """Source 3: infer from json_body vs get params presence."""
    params = file_record.get("input_params", {})
    has_json = bool(params.get("json_body"))
    has_get = bool(params.get("get"))
    uri = _file_uri(file_record)

    if has_json and not has_get:
        return [MethodResult(method="POST", uri=uri, inference_source="input_param_type")]
    if has_get and not has_json:
        return [MethodResult(method="GET", uri=uri, inference_source="input_param_type")]
    if has_json and has_get:
        # Both present → two items: GET (query params) + POST (JSON body)
        return [
            MethodResult(method="GET", uri=uri, inference_source="input_param_type"),
            MethodResult(method="POST", uri=uri, inference_source="input_param_type"),
        ]
    return []


def _try_signal_based(
    file_record: dict[str, Any],
    pattern: dict[str, Any],
) -> MethodResult | None:
    """Source 4: signal_based rules from pattern.json."""
    rules = pattern["method_inference"].get("rules", [])
    strong_names = {
        s.get("name", "") for s in file_record.get("signals", {}).get("strong", [])
    }
    for rule in rules:
        if rule.get("source") != "signal_based":
            continue
        if rule.get("matched_signal_name", "") in strong_names:
            method = (rule.get("method") or "GET").upper()
            return MethodResult(
                method=method,
                uri=_file_uri(file_record),
                inference_source="signal_based",
            )
    return None


def _use_default(file_record: dict[str, Any], pattern: dict[str, Any]) -> MethodResult:
    """Source 5: default_method from pattern.json."""
    method = pattern["method_inference"].get("default_method", "GET").upper()
    return MethodResult(
        method=method,
        uri=_file_uri(file_record),
        inference_source="default",
        confidence="default",
    )


def _file_uri(file_record: dict[str, Any]) -> str:
    """Derive URI from any route_hint or file path."""
    for hint in file_record.get("route_hints", []):
        uri = hint.get("uri", "")
        if uri:
            return uri
    path = file_record.get("path", "")
    return f"/{path}" if path else "/"
