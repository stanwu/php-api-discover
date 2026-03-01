"""
Secret redactor — applies ordered pattern rules and returns
(redacted_text, redaction_count).

Rules (applied in order per spec):
  1. Assignment/dict entries  — key = "value"  →  key = "REDACTED"
  2. Long alphanumeric strings (≥ 32 chars)    →  "REDACTED"
  3. Bearer / Authorization header values      →  Bearer REDACTED
  4. getenv() calls                             →  preserved; flagged as safe
"""

import re
from typing import Tuple

# ── Pattern 1: assignment with quoted value ───────────────────────────────────
# Matches: api_key = 'abc...', token: "xyz...", password => 'secret'
# Value must be ≥ 8 characters (to avoid redacting short test values)
_ASSIGN_RE = re.compile(
    r"""(?i)(api_?key|token|secret|password|passwd|auth)\s*[=:>]+\s*(['"])[^\'"]{8,}\2""",
    re.VERBOSE,
)

# ── Pattern 2: long alphanumeric strings (≥ 32 chars) ────────────────────────
_LONG_STR_RE = re.compile(r"""(['"])[A-Za-z0-9+/=_\-]{32,}\1""")

# ── Pattern 3: Bearer tokens ──────────────────────────────────────────────────
_BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*")

# ── Pattern 4: getenv (safe — do not redact, just flag) ──────────────────────
_GETENV_RE = re.compile(r"""getenv\(['"][^'"]+['"]\)""")


def redact_secrets(content: str) -> Tuple[str, int]:
    """
    Returns (redacted_content, total_redaction_count).

    Applies patterns in order.  getenv() calls are left as-is; every other
    match increments the count.
    """
    count = 0
    result = content

    # 1. Assignment pattern — preserve key, redact value only
    def _sub_assign(m: re.Match) -> str:
        nonlocal count
        count += 1
        key = m.group(1)
        quote = m.group(2)
        return f'{key} = {quote}REDACTED{quote}'

    result = _ASSIGN_RE.sub(_sub_assign, result)

    # 2. Long alphanumeric string literals
    def _sub_long(m: re.Match) -> str:
        nonlocal count
        count += 1
        quote = m.group(1)
        return f'{quote}REDACTED{quote}'

    result = _LONG_STR_RE.sub(_sub_long, result)

    # 3. Bearer tokens
    def _sub_bearer(m: re.Match) -> str:
        nonlocal count
        count += 1
        return f'{m.group(1)}REDACTED'

    result = _BEARER_RE.sub(_sub_bearer, result)

    # 4. getenv — no substitution, left as-is
    return result, count
