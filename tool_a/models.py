from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional


@dataclasses.dataclass
class SignalMatch:
    name: str
    occurrences: int = 0
    line_nos: List[int] = dataclasses.field(default_factory=list)
    global_seen_in_files: int = 0
    false_positive_risk: str = "unknown"


@dataclasses.dataclass
class ScoreBreakdownItem:
    signal: str
    kind: str   # "strong" | "weak" | "negative"
    delta: int
    line_no: Optional[int] = None


@dataclasses.dataclass
class RouteHint:
    method: str
    uri: str
    source_file: str
    source_line: int
    confidence: str  # "high" | "low"
    controller_method: Optional[str] = None


@dataclasses.dataclass
class DynamicNote:
    type: str   # "variable_dispatch" | "concatenated_header" | "deep_indirection"
    line_no: int
    note: str
    raw_line: str


@dataclasses.dataclass
class InputParam:
    key: str
    line_no: int


@dataclasses.dataclass
class EnvelopeKey:
    key: str
    line_no: int


@dataclasses.dataclass
class OutputPoint:
    kind: str
    line_no: int
    context_excerpt: str


@dataclasses.dataclass
class CustomHelperCall:
    name: str
    line_no: int
    resolved_to: str
    wrap_depth: int


@dataclasses.dataclass
class SkippedFile:
    path: str
    reason: str
    size_mb: Optional[float] = None
    encoding_detected: Optional[str] = None


@dataclasses.dataclass
class FileRecord:
    record_type: str = "file"
    schema_version: str = "2.0"
    path: str = ""
    framework: str = "plain"
    score: int = 0
    score_breakdown: List[ScoreBreakdownItem] = dataclasses.field(default_factory=list)
    signals: Dict[str, List[SignalMatch]] = dataclasses.field(
        default_factory=lambda: {"strong": [], "weak": [], "negative": []}
    )
    dynamic_notes: List[DynamicNote] = dataclasses.field(default_factory=list)
    route_hints: List[RouteHint] = dataclasses.field(default_factory=list)
    input_params: Dict[str, List[InputParam]] = dataclasses.field(
        default_factory=lambda: {"get": [], "post": [], "request": [], "json_body": []}
    )
    method_hints: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    envelope_keys: List[EnvelopeKey] = dataclasses.field(default_factory=list)
    output_points: List[OutputPoint] = dataclasses.field(default_factory=list)
    custom_helpers_called: List[CustomHelperCall] = dataclasses.field(default_factory=list)
    redaction_count: int = 0
    skipped: bool = False
    skip_reason: Optional[str] = None
    encoding_note: Optional[str] = None
    notes: List[str] = dataclasses.field(default_factory=list)
