"""tool_c.envelope_matcher — Envelope template matching.

Matches file.envelope_keys against pattern.json endpoint_envelopes.templates.
Returns the first matching template or None.
"""

from __future__ import annotations

from typing import Any


def match_envelope(
    file_record: dict[str, Any],
    pattern: dict[str, Any],
) -> dict[str, Any] | None:
    """Return the first matching template or None.

    Match rules:
      all(k in file_keys for k in keys_all_of)   — all-of constraint
      any(k in file_keys for k in keys_any_of)   — any-of constraint
                                                    (satisfied if keys_any_of is empty)
    """
    templates = pattern.get("endpoint_envelopes", {}).get("templates", [])
    key_set = {e.get("key", "") for e in file_record.get("envelope_keys", [])}

    for template in templates:
        keys_all = template.get("keys_all_of", [])
        keys_any = template.get("keys_any_of", [])

        all_present = all(k in key_set for k in keys_all)
        any_present = (not keys_any) or any(k in key_set for k in keys_any)

        if all_present and any_present:
            return template

    return None
