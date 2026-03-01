"""tool_c.jsonl_reader — Streaming JSONL reader for ToolC.

Reads features_raw.jsonl produced by ToolA v2.
  Line 0     : global_stats  (schema_version must be "2.0")
  Lines 1–N  : file records
  Last line  : skipped_files_summary

Exit codes:
  2: schema_version mismatch or invalid line 0
  3: I/O error
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def read_jsonl(
    path: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Read features_raw.jsonl.

    Returns (global_stats, file_records, skipped_summary).
    Exits with code 2 if schema_version != "2.0".
    Exits with code 3 on I/O error.
    Lines that fail JSON parsing are skipped with a warning.
    """
    try:
        raw_text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Error: Cannot read JSONL file '{path}': {exc}", file=sys.stderr)
        sys.exit(3)

    lines = raw_text.splitlines()
    # Filter blank lines but keep index tracking
    non_blank = [(i, ln) for i, ln in enumerate(lines) if ln.strip()]

    if not non_blank:
        print(f"Error: JSONL file '{path}' is empty", file=sys.stderr)
        sys.exit(2)

    # ── Line 0: global_stats ──────────────────────────────────────────────────
    line0_idx, line0 = non_blank[0]
    try:
        global_stats: dict[str, Any] = json.loads(line0)
    except json.JSONDecodeError as exc:
        print(
            f"Error: Line {line0_idx + 1} of '{path}' is not valid JSON: {exc}",
            file=sys.stderr,
        )
        sys.exit(2)

    record_type = global_stats.get("record_type")
    if record_type != "global_stats":
        print(
            f"Error: Line 0 record_type is {record_type!r}, expected 'global_stats'",
            file=sys.stderr,
        )
        sys.exit(2)

    schema_version = global_stats.get("schema_version")
    if schema_version != "2.0":
        print(
            f"Error: JSONL schema_version mismatch — expected '2.0', got {schema_version!r}.\n"
            f"This file may have been produced by a different version of ToolA.\n"
            f"Re-run ToolA v2 to generate a compatible features_raw.jsonl.",
            file=sys.stderr,
        )
        sys.exit(2)

    # ── Remaining lines: file records + skipped_files_summary ─────────────────
    file_records: list[dict[str, Any]] = []
    skipped_summary: dict[str, Any] = {"skipped_files": []}

    for line_idx, line in non_blank[1:]:
        try:
            record: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError as exc:
            print(
                f"WARNING: Line {line_idx + 1} of '{path}' is not valid JSON "
                f"(skipping): {exc}",
                file=sys.stderr,
            )
            continue

        rt = record.get("record_type")
        if rt == "file":
            file_records.append(record)
        elif rt == "skipped_files_summary":
            skipped_summary = record
        # other record_types silently ignored

    return global_stats, file_records, skipped_summary
