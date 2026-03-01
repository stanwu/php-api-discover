"""tool_c.redactor — Secret redaction for Postman body and response examples.

Applies to:
  - request body.raw (JSON string)
  - response[].body (JSON string)

Pattern: key names matching (api_?key|token|secret|password) have their
         string values replaced with "REDACTED".
"""

from __future__ import annotations

import re

# Match JSON key-value pairs where the key is a secret-like name
# Group 1: the key + colon portion (preserved)
# Group 2: the value to replace
_SECRET_VALUE_RE = re.compile(
    r'("(?:api_?key|token|secret|password)[^"]*"\s*:\s*)"([^"]*)"',
    re.IGNORECASE,
)


def redact_body(body_str: str) -> tuple[str, bool]:
    """Redact secret-like string values in a JSON body string.

    Returns (possibly_redacted_string, was_redacted).
    """
    redacted, count = _SECRET_VALUE_RE.subn(r'\1"REDACTED"', body_str)
    return redacted, count > 0


def param_placeholder(key: str, redact_if_secret: bool = False) -> object:
    """Return a typed placeholder value for a parameter key.

    Key-name heuristics (from spec):
      ending in _id, id, count, page, limit  → 0
      ending in _at, date, time              → ""
      starting with is_, has_, or = enabled/active → True
      otherwise                              → ""

    If redact_if_secret=True and key matches a secret pattern, returns "REDACTED".
    """
    _SECRET_KEY_RE = re.compile(r'(?:api_?key|token|secret|password)', re.IGNORECASE)
    if redact_if_secret and _SECRET_KEY_RE.search(key):
        return "REDACTED"

    k = key.lower()
    if k == "id" or k.endswith(("_id", "count", "page", "limit")):
        return 0
    if k.endswith(("_at", "date", "time")):
        return ""
    if k.startswith(("is_", "has_")) or k in ("enabled", "active") or k.endswith(("_enabled", "_active")):
        return True
    return ""
