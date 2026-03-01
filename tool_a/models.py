import dataclasses
from typing import List, Dict, Any, Optional

@dataclasses.dataclass
class OutputPoint:
    kind: str
    line_no: int
    context_excerpt: str

@dataclasses.dataclass
class FileFeatures:
    path: str
    score: int = 0
    signals: Dict[str, List[str]] = dataclasses.field(default_factory=lambda: {"strong": [], "weak": [], "negative": []})
    input_params: Dict[str, List[str]] = dataclasses.field(default_factory=lambda: {"get": [], "post": [], "request": [], "json_body": []})
    method_hints: List[str] = dataclasses.field(default_factory=list)
    envelope_keys: List[str] = dataclasses.field(default_factory=list)
    output_points: List[OutputPoint] = dataclasses.field(default_factory=list)
    notes: List[str] = dataclasses.field(default_factory=list)
    error: Optional[str] = None
