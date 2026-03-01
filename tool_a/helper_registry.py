"""
First-pass custom helper discovery.

Scans all PHP files to find user-defined functions that internally call
known JSON-output signals.  These helpers are then treated as strong signals
in the main (second) scan pass.
"""

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Signals whose presence inside a function body qualifies it as a "JSON helper"
_KNOWN_SIGNAL_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bjson_encode\s*\("),
    re.compile(r"\bwp_send_json(?:_success|_error)?\s*\("),
    re.compile(r"response\s*\(\s*\)\s*->\s*json\s*\("),
    re.compile(r"\bnew\s+JsonResponse\s*\("),
    re.compile(r"\$this\s*->\s*json\s*\("),
    re.compile(r"header\s*\(\s*['\"]Content-Type:\s*application/json['\"]"),
    re.compile(r"\b(?:die|exit)\s*\(\s*json_encode\s*\("),
    re.compile(r"\$this\s*->\s*output\s*->\s*set_content_type\s*\("),
    re.compile(r"\$response\s*->\s*withJson\s*\("),
]

# Map signal pattern → display name used in registry output
_SIGNAL_DISPLAY: Dict[re.Pattern, str] = {
    _KNOWN_SIGNAL_PATTERNS[0]: "json_encode(",
    _KNOWN_SIGNAL_PATTERNS[1]: "wp_send_json(",
    _KNOWN_SIGNAL_PATTERNS[2]: "response()->json(",
    _KNOWN_SIGNAL_PATTERNS[3]: "new JsonResponse(",
    _KNOWN_SIGNAL_PATTERNS[4]: "$this->json(",
    _KNOWN_SIGNAL_PATTERNS[5]: "header('Content-Type: application/json')",
    _KNOWN_SIGNAL_PATTERNS[6]: "die/exit(json_encode(",
    _KNOWN_SIGNAL_PATTERNS[7]: "$this->output->set_content_type(",
    _KNOWN_SIGNAL_PATTERNS[8]: "$response->withJson(",
}

# Matches any `function name(` occurrence.
_FUNC_DEF_RE = re.compile(r"function\s+(\w+)\s*\(")

# Class methods are preceded by access/modifier keywords on the same line.
# We skip these so only standalone (global) functions are registered as helpers.
_METHOD_MODIFIER_RE = re.compile(
    r"(?:public|protected|private|static|abstract|final)\s+",
    re.IGNORECASE,
)


@dataclass
class HelperEntry:
    helper_name: str
    defined_in: str          # "rel/path.php:line_no"
    wraps_signal: str        # display name of the wrapped signal
    wrap_depth: int = 1
    seen_called_in_files: int = 0
    pct_of_candidates: float = 0.0
    suggested_kind: str = "strong"
    suggested_weight_hint: int = 20


class HelperRegistry:
    def __init__(self) -> None:
        self.helpers: Dict[str, HelperEntry] = {}
        self._call_counts: Dict[str, int] = {}

    # ── Build phase ──────────────────────────────────────────────────────────

    def build_from_files(self, file_paths: List[str], root_path: str) -> None:
        """Pass 1: scan all PHP files and register qualifying helper functions."""
        for path in file_paths:
            self._scan_file(path, root_path)

    def _scan_file(self, file_path: str, root_path: str) -> None:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            return

        lines = content.splitlines()
        for i, line in enumerate(lines):
            m = _FUNC_DEF_RE.search(line)
            if not m:
                continue
            func_name = m.group(1)
            # Skip class methods: they have access modifiers before "function"
            # on the same line (e.g. "public function index(")
            if _METHOD_MODIFIER_RE.search(line):
                continue
            # Skip already-registered helpers and PHP built-ins
            if func_name in self.helpers:
                continue

            # Scan body: up to 60 lines (avoids reading entire large files)
            body = "\n".join(lines[i : min(i + 60, len(lines))])

            for pat, display_name in _SIGNAL_DISPLAY.items():
                if pat.search(body):
                    rel_path = os.path.relpath(file_path, root_path)
                    self.helpers[func_name] = HelperEntry(
                        helper_name=func_name,
                        defined_in=f"{rel_path}:{i + 1}",
                        wraps_signal=display_name,
                        wrap_depth=1,
                    )
                    break

    # ── Counting phase (called during pass 2) ────────────────────────────────

    def count_calls_in_content(self, content: str) -> None:
        """Record that a helper was called in the current file (for stats)."""
        for name in self.helpers:
            pat = re.compile(rf"\b{re.escape(name)}\s*\(")
            if pat.search(content):
                self._call_counts[name] = self._call_counts.get(name, 0) + 1

    # ── Finalise stats ───────────────────────────────────────────────────────

    def finalize_stats(self, total_candidate_files: int) -> None:
        for name, entry in self.helpers.items():
            count = self._call_counts.get(name, 0)
            entry.seen_called_in_files = count
            if total_candidate_files > 0:
                entry.pct_of_candidates = round(
                    count / total_candidate_files * 100, 1
                )

    # ── Query helpers ────────────────────────────────────────────────────────

    def get_call_pattern(self) -> Optional[re.Pattern]:
        """Returns a regex that matches any call to a registered helper, or None."""
        if not self.helpers:
            return None
        names = "|".join(re.escape(n) for n in self.helpers)
        return re.compile(rf"\b({names})\s*\(")

    def get_wrap_depth(self, helper_name: str) -> int:
        entry = self.helpers.get(helper_name)
        return entry.wrap_depth if entry else 1

    def get_wraps_signal(self, helper_name: str) -> str:
        entry = self.helpers.get(helper_name)
        return entry.wraps_signal if entry else "json_encode("

    # ── Serialisation ────────────────────────────────────────────────────────

    def to_jsonl_list(self) -> List[dict]:
        return [
            {
                "helper_name": e.helper_name,
                "defined_in": e.defined_in,
                "wraps_signal": e.wraps_signal,
                "wrap_depth": e.wrap_depth,
                "seen_called_in_files": e.seen_called_in_files,
                "pct_of_candidates": e.pct_of_candidates,
                "suggested_kind": e.suggested_kind,
                "suggested_weight_hint": e.suggested_weight_hint,
            }
            for e in self.helpers.values()
        ]
