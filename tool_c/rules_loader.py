"""tool_c.rules_loader — Load and validate pattern.json for ToolC.

Strips _-prefixed extension fields before validation (V11).
Delegates to toolchain.toolchain_validator for V1–V13 checks.
Prints warnings to stderr; exits 1 on hard validation errors.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from toolchain.toolchain_validator import validate_pattern_json


def load_rules(
    rules_path: str,
    global_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load and validate pattern.json.

    Returns the cleaned pattern dict (without _-prefixed keys).
    Prints warnings to stderr; exits 1 on validation errors; exits 3 on I/O.
    """
    try:
        raw = Path(rules_path).read_text(encoding="utf-8")
        pattern: dict[str, Any] = json.loads(raw)
    except OSError as exc:
        print(f"Error: Cannot read rules file '{rules_path}': {exc}", file=sys.stderr)
        sys.exit(3)
    except json.JSONDecodeError as exc:
        print(f"Error: '{rules_path}' is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    # V11: log _-prefixed extension fields at DEBUG level
    debug = os.environ.get("TOOLC_DEBUG")
    for key in list(pattern.keys()):
        if key.startswith("_"):
            if debug:
                print(f"DEBUG: Ignored extension field: {key}", file=sys.stderr)

    # Validate — the validator strips _-prefixed keys internally
    result = validate_pattern_json(pattern, global_stats)

    for warning in result.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)

    if not result.valid:
        for error in result.errors:
            print(f"Error: {error}", file=sys.stderr)
        print(
            f"Validation failed with {len(result.errors)} error(s). "
            "Fix pattern.json and retry.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Return clean dict
    return {k: v for k, v in pattern.items() if not k.startswith("_")}
