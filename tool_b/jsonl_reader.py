"""jsonl_reader.py — Read and parse features_raw.jsonl (schema_version 2.0)

Returns global_stats dict and a list of file-record dicts.
Raises SystemExit(8) if file unreadable, SystemExit(2) if schema version wrong.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def read_jsonl(path: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Read features_raw.jsonl produced by ToolA v2.

    Returns:
        (global_stats, file_records)

    Raises SystemExit:
        code 8 — file not found or unreadable
        code 2 — schema_version is not "2.0"
    """
    p = Path(path)
    if not p.exists():
        print(f"Error: JSONL file not found: {path}", file=sys.stderr)
        sys.exit(8)

    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"Error reading JSONL file: {exc}", file=sys.stderr)
        sys.exit(8)

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        print(f"Error: JSONL file is empty: {path}", file=sys.stderr)
        sys.exit(8)

    # Parse line 0 as global_stats
    try:
        global_stats: dict[str, Any] = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        print(f"Error: line 0 of JSONL is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(8)

    # Validate schema_version
    schema_ver = global_stats.get("schema_version")
    if schema_ver != "2.0":
        print(
            f"Error: JSONL schema_version is '{schema_ver}', expected '2.0'. "
            f"Re-run ToolA v2 to regenerate features_raw.jsonl.",
            file=sys.stderr,
        )
        sys.exit(2)

    record_type = global_stats.get("record_type")
    if record_type != "global_stats":
        print(
            f"Error: line 0 record_type is '{record_type}', expected 'global_stats'.",
            file=sys.stderr,
        )
        sys.exit(8)

    # Parse remaining lines as file records (skip skipped_files_summary)
    file_records: list[dict[str, Any]] = []
    for i, line in enumerate(lines[1:], start=1):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            # Skip unparseable lines with a warning
            print(f"Warning: skipping unparseable JSONL line {i}", file=sys.stderr)
            continue
        if obj.get("record_type") == "file":
            file_records.append(obj)
        # skipped_files_summary and other record_types are ignored

    return global_stats, file_records
