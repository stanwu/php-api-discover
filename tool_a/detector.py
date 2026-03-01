import re
from typing import List, Tuple
from .models import FileFeatures, OutputPoint
from .redactor import redact_secrets

# Signal Definitions
# Using tuples of (description, regex_pattern)
SIGNALS = {
    "strong": [
        ("header('Content-Type: application/json')", re.compile(r"header\s*\(\s*['\"]Content-Type:\s*application/json['\"]\s*\)", re.IGNORECASE)),
        ("wp_send_json", re.compile(r"wp_send_json(?:_success|_error)?\s*\(")),
        ("response()->json()", re.compile(r"response\s*\(.*\?\)\s*->\s*json\s*\(")),
        ("custom json helper", re.compile(r"\b(returnJson|apiResponse|outputJson)\s*\(")),
        ("exit/die with json_encode", re.compile(r"(?:exit|die)\s*\(\s*json_encode\s*\(")),
    ],
    "weak": [
        ("json_encode", re.compile(r"json_encode\s*\(")),
        ("Accept: application/json", re.compile(r"HTTP_ACCEPT.*application/json", re.IGNORECASE)),
    ],
    "negative": [
        ("HTML tag", re.compile(r"<\s*(?:html|body|head|div|p|h[1-6])", re.IGNORECASE)),
        ("render/template", re.compile(r"->\s*(?:render|display|view)\s*\(|include\s*['\"](?:view|header|footer)\.php['\"]")),
        ("echo HTML", re.compile(r"echo\s*['\"]+.*<[a-zA-Z]", re.IGNORECASE)),
    ]
}

INPUT_SIGNALS = {
    "get": re.compile(r"\$_GET\s*\[\s*['\"]([^’\"]+?)['\"]\s*\]"),
    "post": re.compile(r"\$_POST\s*\[\s*['\"]([^’\"]+?)['\"]\s*\]"),
    "request": re.compile(r"\$_REQUEST\s*\[\s*['\"]([^’\"]+?)['\"]\s*\]"),
    "json_body": re.compile(r"json_decode\s*\(\s*file_get_contents\s*\(\s*['\"]php:\/\/input['\"]\s*\)\s*(?:,\s*true)?\s*\)"),
    "json_body_keys": re.compile(r"\$([a-zA-Z0-9_]+)\s*\[\s*['\"]([^’\"]+?)['\"]\s*\]"),
}

METHOD_HINTS = re.compile(r"\$_SERVER\s*\[\s*['\"]REQUEST_METHOD['\"]\s*\]\s*(?:===|==)\s*['\"](GET|POST|PUT|DELETE|PATCH)['\"]", re.IGNORECASE)

ENVELOPE_KEYS = re.compile(r"['\"](ok|success|code|message|data|result|error|status)['\"]\s*=>", re.IGNORECASE)

OUTPUT_POINTS = re.compile(r"\b(echo|print|exit|die|return|wp_send_json(?:_success|_error)?|response\s*\(.*\?\)\s*->\s*json|returnJson|apiResponse|outputJson)\b", re.IGNORECASE)

class Detector:
    def __init__(self, max_snippet_lines: int = 10):
        self.max_snippet_lines = max_snippet_lines

    def analyze_file(self, file_path: str) -> FileFeatures:
        features = FileFeatures(path=file_path)
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                lines = content.splitlines()
        except Exception as e:
            features.error = f"Error reading file: {e}"
            return features

        self._detect_signals_and_score(content, features)
        self._extract_inputs(content, features)
        self._extract_method_hints(content, features)
        self._extract_envelope_keys(content, features)
        self._extract_output_points(lines, features)

        return features

    def _detect_signals_and_score(self, content: str, features: FileFeatures):
        score = 50  # Start from a neutral score

        for category, signals in SIGNALS.items():
            for name, pattern in signals:
                if pattern.search(content):
                    features.signals[category].append(name)
                    if category == "strong":
                        score += 20
                    elif category == "weak":
                        score += 5
                    elif category == "negative":
                        score -= 15
        
        features.score = max(0, min(100, score))

    def _extract_inputs(self, content: str, features: FileFeatures):
        features.input_params["get"] = sorted(list(set(INPUT_SIGNALS["get"].findall(content))))
        features.input_params["post"] = sorted(list(set(INPUT_SIGNALS["post"].findall(content))))
        features.input_params["request"] = sorted(list(set(INPUT_SIGNALS["request"].findall(content))))
        
        if INPUT_SIGNALS["json_body"].search(content):
            features.signals["weak"].append("php://input")
            # Simple heuristic: find array access on variables that were assigned from json_decode
            json_body_vars = re.findall(r"\$([a-zA-Z0-9_]+)\s*=\s*json_decode", content)
            if json_body_vars:
                # Create a regex to find usages of these variables as arrays
                # e.g. $data['key'] or $input['field']
                var_pattern_str = r"\$(" + "|".join(re.escape(v) for v in json_body_vars) + r")\s*\[\s*['\"]([^’\"]+?)['\"]\s*\]"
                var_pattern = re.compile(var_pattern_str)
                keys = var_pattern.findall(content)
                features.input_params["json_body"] = sorted(list(set(keys)))


    def _extract_method_hints(self, content: str, features: FileFeatures):
        features.method_hints = sorted(list(set(m.upper() for m in METHOD_HINTS.findall(content))))

    def _extract_envelope_keys(self, content: str, features: FileFeatures):
        features.envelope_keys = sorted(list(set(k.lower() for k in ENVELOPE_KEYS.findall(content))))

    def _extract_output_points(self, lines: List[str], features: FileFeatures):
        matches = []
        # First, find all potential output points and their line indices
        for i, line in enumerate(lines):
            for match in OUTPUT_POINTS.finditer(line):
                matches.append({'line_index': i, 'match': match})

        last_snippet_end_index = -1
        for m_info in matches:
            line_index = m_info['line_index']
            
            # If this line is within the bounds of the last snippet created, skip it
            # to avoid creating overlapping snippets.
            if line_index <= last_snippet_end_index:
                continue

            match = m_info['match']
            kind = match.group(1).strip()
            
            # Avoid capturing 'return' in 'returnJson' as a separate point
            if kind.lower() == 'return' and 'returnJson' in lines[line_index]:
                continue

            # Define the snippet boundaries
            start_index = max(0, line_index - self.max_snippet_lines // 2)
            end_index = min(len(lines), line_index + self.max_snippet_lines // 2 + 1)
            
            # Record the end of this snippet's range to prevent overlaps
            last_snippet_end_index = end_index -1

            snippet_lines = lines[start_index:end_index]
            redacted_snippet = redact_secrets("\n".join(snippet_lines))
            
            features.output_points.append(OutputPoint(
                kind=kind,
                line_no=line_index + 1, # Convert 0-based index to 1-based line number
                context_excerpt=redacted_snippet
            ))