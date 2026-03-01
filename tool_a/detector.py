"""
Signal detector — performs per-file analysis for pass 2.

Responsibilities:
  - Detect framework-specific signals (with line numbers and occurrence counts)
  - Detect dynamic patterns (variable dispatch, concatenated headers)
  - Detect custom helper calls (using HelperRegistry)
  - Extract input params, method hints, envelope keys, output points
  - Apply secret redaction (via redactor)
  - Invoke scorer for the final heuristic score
"""

import re
from typing import Dict, List, Optional, Tuple

from .helper_registry import HelperRegistry
from .models import (
    CustomHelperCall,
    DynamicNote,
    EnvelopeKey,
    FileRecord,
    InputParam,
    OutputPoint,
    RouteHint,
    ScoreBreakdownItem,
    SignalMatch,
)
from .redactor import redact_secrets
from .route_mapper import RouteMapper
from .scorer import score_file
from .signals import FRAMEWORK_SIGNALS

# ── Input extraction patterns ─────────────────────────────────────────────────
_GET_RE = re.compile(r"\$_GET\s*\[\s*['\"]([^'\"]+?)['\"]\s*\]")
_POST_RE = re.compile(r"\$_POST\s*\[\s*['\"]([^'\"]+?)['\"]\s*\]")
_REQUEST_RE = re.compile(r"\$_REQUEST\s*\[\s*['\"]([^'\"]+?)['\"]\s*\]")
_PHP_INPUT_RE = re.compile(
    r"json_decode\s*\(\s*file_get_contents\s*\(\s*['\"]php://input['\"]\s*\)"
)
_JSON_VAR_ASSIGN_RE = re.compile(r"\$(\w+)\s*=\s*json_decode\b")

# ── Envelope key detection ────────────────────────────────────────────────────
_ENVELOPE_RE = re.compile(
    r"['\"](?P<key>ok|success|code|message|data|result|error|status)['\"]\s*=>",
    re.IGNORECASE,
)

# ── Method hint detection ─────────────────────────────────────────────────────
_METHOD_RE = re.compile(
    r"\$_SERVER\s*\[\s*['\"]REQUEST_METHOD['\"]\s*\]\s*(?:===|==)\s*['\"]"
    r"(?P<method>GET|POST|PUT|DELETE|PATCH)['\"]",
    re.IGNORECASE,
)

# ── Output point detection ────────────────────────────────────────────────────
_OUTPUT_RE = re.compile(
    r"\b(?:echo|print|exit|die)\s*\(?\s*json_encode\s*\("
    r"|response\s*\(\s*\)\s*->\s*json\s*\("
    r"|wp_send_json(?:_success|_error)?\s*\("
    r"|\bnew\s+JsonResponse\s*\("
    r"|\$this\s*->\s*json\s*\("
    r"|\$response\s*->\s*withJson\s*\("
    r"|\$this\s*->\s*output\s*->\s*set_content_type\s*\("
    r"|\$this\s*->\s*response\s*\(",
    re.IGNORECASE,
)

# ── Dynamic pattern detection ─────────────────────────────────────────────────
# Names of functions whose string assignment in a variable triggers weak flagging
_VAR_DISPATCH_TARGETS = {
    "json_encode", "wp_send_json", "wp_send_json_success", "wp_send_json_error",
}
_VAR_ASSIGN_RE = re.compile(r"\$(\w+)\s*=\s*['\"](\w+)['\"]")
_VAR_CALL_RE = re.compile(r"\$(\w+)\s*\(")

# Concatenated header: header( ... with a '.' concat operator in the arg
_CONCAT_HEADER_RE = re.compile(r"header\s*\(", re.IGNORECASE)
_HEADER_CONCAT_ARG_RE = re.compile(
    r"header\s*\(\s*(?:['\"]Content-Type['\"].*\.|.*\.\s*\$\w+)", re.IGNORECASE
)


class Detector:
    def __init__(self, max_snippet_lines: int = 80) -> None:
        self.max_snippet_lines = max_snippet_lines

    def analyze_file(
        self,
        file_path: str,
        rel_path: str,
        framework: str,
        helper_registry: HelperRegistry,
        route_mapper: RouteMapper,
        global_freq: Dict[str, int],
        signal_fpr: Dict[str, str],
    ) -> FileRecord:
        """
        Analyse a single PHP file and return a populated FileRecord.

        global_freq  : mapping signal_name → number of files it was seen in (pass-1 counts)
        signal_fpr   : mapping signal_name → false_positive_risk string
        """
        record = FileRecord(path=rel_path, framework=framework)

        # ── Read file ─────────────────────────────────────────────────────────
        content, encoding_note = _read_file(file_path)
        if content is None:
            record.skipped = True
            record.skip_reason = "read_error"
            record.encoding_note = encoding_note
            return record

        if encoding_note:
            record.encoding_note = encoding_note

        lines = content.splitlines()
        profile = FRAMEWORK_SIGNALS.get(framework, FRAMEWORK_SIGNALS["plain"])

        # ── Detect framework signals ──────────────────────────────────────────
        seen_signal_names: set = set()
        for sig in profile:
            name = sig["name"]
            if name in seen_signal_names:
                continue  # deduplicate identical names in a profile
            pat: re.Pattern = sig["pattern"]
            kind: str = sig["kind"]
            delta: int = sig["delta"]
            fpr: str = sig.get("false_positive_risk", "low")
            override_fpr = signal_fpr.get(name, fpr)

            occurrences = 0
            line_nos: List[int] = []
            for i, line in enumerate(lines):
                if pat.search(line):
                    occurrences += 1
                    line_nos.append(i + 1)

            if occurrences == 0:
                continue

            seen_signal_names.add(name)
            match = SignalMatch(
                name=name,
                occurrences=occurrences,
                line_nos=line_nos,
                global_seen_in_files=global_freq.get(name, occurrences),
                false_positive_risk=override_fpr,
            )
            record.signals[kind].append(match)
            record.score_breakdown.append(
                ScoreBreakdownItem(
                    signal=name,
                    kind=kind,
                    delta=delta,
                    line_no=line_nos[0],
                )
            )

        # ── Detect custom helper calls ─────────────────────────────────────────
        helper_call_pat = helper_registry.get_call_pattern()
        if helper_call_pat:
            for i, line in enumerate(lines):
                m = helper_call_pat.search(line)
                if m:
                    helper_name = m.group(1)
                    entry = helper_registry.helpers.get(helper_name)
                    if not entry:
                        continue
                    wrap_depth = entry.wrap_depth
                    if wrap_depth > 2:
                        record.notes.append(
                            f"Deep indirection (depth {wrap_depth}) detected via "
                            f"{helper_name}() at line {i+1} — not scored to avoid false positives"
                        )
                        record.dynamic_notes.append(
                            DynamicNote(
                                type="deep_indirection",
                                line_no=i + 1,
                                note=f"Indirection depth {wrap_depth} — not scored",
                                raw_line=line.strip(),
                            )
                        )
                        continue

                    resolved_to = entry.wraps_signal
                    record.custom_helpers_called.append(
                        CustomHelperCall(
                            name=helper_name,
                            line_no=i + 1,
                            resolved_to=resolved_to,
                            wrap_depth=wrap_depth,
                        )
                    )
                    # Score as strong (custom helper weight = +20)
                    already_added = any(
                        b.signal == f"custom_helper:{helper_name}"
                        for b in record.score_breakdown
                    )
                    if not already_added:
                        record.score_breakdown.append(
                            ScoreBreakdownItem(
                                signal=f"custom_helper:{helper_name}",
                                kind="strong",
                                delta=20,
                                line_no=i + 1,
                            )
                        )
                        # Also surface as a strong signal match
                        record.signals["strong"].append(
                            SignalMatch(
                                name=f"custom_helper:{helper_name}",
                                occurrences=1,
                                line_nos=[i + 1],
                                global_seen_in_files=entry.seen_called_in_files,
                                false_positive_risk="low",
                            )
                        )

        # ── Dynamic pattern detection ─────────────────────────────────────────
        self._detect_dynamic_patterns(lines, record)

        # ── Route hints ───────────────────────────────────────────────────────
        record.route_hints = route_mapper.get_hints_for_file(rel_path, content)

        # ── Input parameter extraction ────────────────────────────────────────
        record.input_params["get"] = _extract_params(_GET_RE, lines)
        record.input_params["post"] = _extract_params(_POST_RE, lines)
        record.input_params["request"] = _extract_params(_REQUEST_RE, lines)
        record.input_params["json_body"] = _extract_json_body_params(content, lines)

        # ── Method hints ──────────────────────────────────────────────────────
        record.method_hints = _extract_method_hints(lines)

        # ── Envelope keys ─────────────────────────────────────────────────────
        record.envelope_keys = _extract_envelope_keys(lines)

        # ── Output points + redaction ─────────────────────────────────────────
        record.output_points = self._extract_output_points(lines)
        # Redact snippets
        total_redact = 0
        for op in record.output_points:
            redacted, cnt = redact_secrets(op.context_excerpt)
            op.context_excerpt = redacted
            total_redact += cnt
        record.redaction_count = total_redact

        # ── Final score ───────────────────────────────────────────────────────
        record.score = score_file(record.score_breakdown)

        return record

    # ── Dynamic patterns ──────────────────────────────────────────────────────

    def _detect_dynamic_patterns(self, lines: List[str], record: FileRecord) -> None:
        var_map: Dict[str, Tuple[str, int]] = {}  # var_name → (signal_name, assign_line)

        for i, line in enumerate(lines):
            # Variable function assignment
            m = _VAR_ASSIGN_RE.search(line)
            if m:
                var_name, value = m.group(1), m.group(2)
                if value in _VAR_DISPATCH_TARGETS:
                    var_map[var_name] = (value, i + 1)

            # Variable function call
            m = _VAR_CALL_RE.search(line)
            if m:
                var_name = m.group(1)
                if var_name in var_map:
                    signal_name, _ = var_map[var_name]
                    record.dynamic_notes.append(
                        DynamicNote(
                            type="variable_dispatch",
                            line_no=i + 1,
                            note=(
                                f"Possible dynamic dispatch of {signal_name} "
                                f"via ${var_name}"
                            ),
                            raw_line=line.strip(),
                        )
                    )
                    # Add as weak signal if not already present
                    existing_names = {s.name for s in record.signals["weak"]}
                    if "json_encode(" not in existing_names:
                        record.signals["weak"].append(
                            SignalMatch(
                                name="json_encode(",
                                occurrences=1,
                                line_nos=[i + 1],
                                global_seen_in_files=0,
                                false_positive_risk="medium",
                            )
                        )
                        record.score_breakdown.append(
                            ScoreBreakdownItem(
                                signal="json_encode( (dynamic dispatch)",
                                kind="weak",
                                delta=10,
                                line_no=i + 1,
                            )
                        )

            # Concatenated header
            if _CONCAT_HEADER_RE.search(line):
                if "." in line and _HEADER_CONCAT_ARG_RE.search(line):
                    record.dynamic_notes.append(
                        DynamicNote(
                            type="concatenated_header",
                            line_no=i + 1,
                            note="Concatenated header — manual review required",
                            raw_line=line.strip(),
                        )
                    )
                    # +5 per spec
                    record.score_breakdown.append(
                        ScoreBreakdownItem(
                            signal="concatenated_header",
                            kind="weak",
                            delta=5,
                            line_no=i + 1,
                        )
                    )

    # ── Output point extraction ───────────────────────────────────────────────

    def _extract_output_points(self, lines: List[str]) -> List[OutputPoint]:
        points: List[OutputPoint] = []
        half = max(2, self.max_snippet_lines // 2)
        last_end = -1
        total_snippet_lines = 0

        for i, line in enumerate(lines):
            if not _OUTPUT_RE.search(line):
                continue
            if i <= last_end:
                continue
            if total_snippet_lines >= self.max_snippet_lines:
                break

            start = max(0, i - half)
            end = min(len(lines), i + half + 1)
            snippet = "\n".join(lines[start:end])
            last_end = end - 1
            total_snippet_lines += end - start

            kind = _classify_output(line)
            points.append(
                OutputPoint(
                    kind=kind,
                    line_no=i + 1,
                    context_excerpt=snippet,
                )
            )
        return points


# ── Module-level helpers ──────────────────────────────────────────────────────

def _read_file(file_path: str):
    """Returns (content, encoding_note).  content is None on hard error."""
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            return fh.read(), None
    except UnicodeDecodeError:
        pass
    # Try chardet or fall back to latin-1
    try:
        import chardet
        with open(file_path, "rb") as fh:
            raw = fh.read()
        detected = chardet.detect(raw)
        enc = detected.get("encoding") or "latin-1"
        note = f"Decoded with {enc} (UTF-8 failed)"
        return raw.decode(enc, errors="replace"), note
    except ImportError:
        pass
    try:
        with open(file_path, "r", encoding="latin-1") as fh:
            return fh.read(), "Decoded with latin-1 (UTF-8 failed)"
    except Exception as exc:
        return None, f"read_error: {exc}"


def _extract_params(pat: re.Pattern, lines: List[str]) -> List[InputParam]:
    seen: set = set()
    result: List[InputParam] = []
    for i, line in enumerate(lines):
        for m in pat.finditer(line):
            key = m.group(1)
            if key not in seen:
                seen.add(key)
                result.append(InputParam(key=key, line_no=i + 1))
    return result


def _extract_json_body_params(content: str, lines: List[str]) -> List[InputParam]:
    if not _PHP_INPUT_RE.search(content):
        return []
    # Find variables assigned from json_decode
    var_names = _JSON_VAR_ASSIGN_RE.findall(content)
    if not var_names:
        return []
    var_pat = re.compile(
        r"\$(" + "|".join(re.escape(v) for v in var_names) + r")"
        r"\s*\[\s*['\"]([^'\"]+?)['\"]\s*\]"
    )
    seen: set = set()
    result: List[InputParam] = []
    for i, line in enumerate(lines):
        for m in var_pat.finditer(line):
            key = m.group(2)
            if key not in seen:
                seen.add(key)
                result.append(InputParam(key=key, line_no=i + 1))
    return result


def _extract_method_hints(lines: List[str]) -> List[dict]:
    hints = []
    seen: set = set()
    for i, line in enumerate(lines):
        m = _METHOD_RE.search(line)
        if m:
            method = m.group("method").upper()
            if method not in seen:
                seen.add(method)
                hints.append(
                    {
                        "method": method,
                        "evidence": line.strip(),
                        "line_no": i + 1,
                    }
                )
    return hints


def _extract_envelope_keys(lines: List[str]) -> List[EnvelopeKey]:
    seen: set = set()
    result: List[EnvelopeKey] = []
    for i, line in enumerate(lines):
        for m in _ENVELOPE_RE.finditer(line):
            key = m.group("key").lower()
            if key not in seen:
                seen.add(key)
                result.append(EnvelopeKey(key=key, line_no=i + 1))
    return result


def _classify_output(line: str) -> str:
    line_lower = line.lower()
    if "response()->json" in line_lower:
        return "response()->json("
    if "wp_send_json_success" in line_lower:
        return "wp_send_json_success("
    if "wp_send_json_error" in line_lower:
        return "wp_send_json_error("
    if "wp_send_json" in line_lower:
        return "wp_send_json("
    if "jsonresponse" in line_lower:
        return "new JsonResponse("
    if "->json(" in line_lower:
        return "$this->json("
    if "withjson" in line_lower:
        return "$response->withJson("
    if "json_encode" in line_lower:
        return "json_encode("
    return "output"
