"""response_parser.py — Extract JSON from agent stdout.

Handles:
- Plain JSON responses
- JSON wrapped in markdown fences (```json ... ```)
- Multiple JSON blocks (use the largest)
"""

from __future__ import annotations

import json
import re


_FENCE_PATTERN = re.compile(
    r"```(?:json)?\s*\n(.*?)\n```",
    re.DOTALL | re.IGNORECASE,
)


def extract_json_from_text(text: str) -> dict | None:
    """
    Extract and parse a JSON object from agent response text.

    Strategy:
    1. Try all fenced JSON blocks, return the largest valid dict.
    2. Try entire text stripped.
    3. Try to find a {...} span.
    Returns None if nothing parses as a JSON object.
    """
    candidates: list[str] = []

    # Collect fenced blocks
    for match in _FENCE_PATTERN.finditer(text):
        candidates.append(match.group(1).strip())

    # Also try the whole text
    candidates.append(text.strip())

    # Try to extract {...} span if present
    brace_span = _extract_brace_span(text)
    if brace_span:
        candidates.append(brace_span)

    parsed_candidates: list[dict] = []
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                parsed_candidates.append(obj)
        except (json.JSONDecodeError, ValueError):
            continue

    if not parsed_candidates:
        return None

    # Return the largest dict (by JSON serialisation length)
    return max(parsed_candidates, key=lambda d: len(json.dumps(d)))


def _extract_brace_span(text: str) -> str | None:
    """Find the first outermost {...} span in text."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None
