"""tool_c.postman_validator — Validates Postman Collection v2.1 output.

Uses an embedded schema (no network access required at runtime).
Returns True if valid, False + printed errors if invalid.
"""

from __future__ import annotations

import sys
from typing import Any

try:
    import jsonschema
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False

# ── Embedded minimal Postman Collection v2.1 schema ───────────────────────────
# Validates the essential structure without deep item-level checking.
# Keys prefixed with _ are allowed via additionalProperties.

_POSTMAN_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["info", "item"],
    "additionalProperties": True,
    "properties": {
        "info": {
            "type": "object",
            "required": ["name", "schema"],
            "additionalProperties": True,
            "properties": {
                "name":   {"type": "string"},
                "schema": {
                    "type": "string",
                    "pattern": "schema\\.getpostman\\.com",
                },
            },
        },
        "variable": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": True,
                "required": ["key"],
                "properties": {
                    "key":   {"type": "string"},
                    "value": {},
                    "type":  {"type": "string"},
                },
            },
        },
        "item": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": True,
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "request": {
                        "type": "object",
                        "additionalProperties": True,
                        "required": ["method"],
                        "properties": {
                            "method": {
                                "type": "string",
                                "enum": ["GET", "POST", "PUT", "PATCH", "DELETE",
                                         "HEAD", "OPTIONS", "TRACE", "CONNECT"],
                            },
                        },
                    },
                    # Folders have "item" instead of "request"
                    "item": {"type": "array"},
                },
            },
        },
    },
}


def validate_postman_collection(collection: dict[str, Any]) -> bool:
    """Validate a Postman collection dict against the embedded schema.

    Prints errors to stderr.  Returns True if valid.
    """
    if not _HAS_JSONSCHEMA:
        # Minimal manual check
        if "info" not in collection or "item" not in collection:
            print(
                "Error: Postman validation: missing required field 'info' or 'item'",
                file=sys.stderr,
            )
            return False
        info = collection["info"]
        if not isinstance(info.get("name"), str):
            print("Error: Postman validation: info.name must be a string", file=sys.stderr)
            return False
        schema_url = info.get("schema", "")
        if "schema.getpostman.com" not in schema_url:
            print(
                "Error: Postman validation: info.schema does not reference "
                "schema.getpostman.com",
                file=sys.stderr,
            )
            return False
        return True

    try:
        jsonschema.validate(collection, _POSTMAN_SCHEMA)
        return True
    except jsonschema.ValidationError as exc:
        print(
            f"Error: Postman schema validation failed: {exc.message} "
            f"(path: {list(exc.absolute_path)})",
            file=sys.stderr,
        )
        return False
    except jsonschema.SchemaError as exc:
        print(f"Error: Internal Postman schema error: {exc.message}", file=sys.stderr)
        return False
