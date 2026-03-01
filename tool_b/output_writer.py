"""output_writer.py — Write validated pattern.json with _tool_b_meta appended."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_pattern_json(
    pattern: dict[str, Any],
    out_path: str,
    *,
    agent: str,
    agent_model: str,
    source_jsonl: str,
    jsonl_schema_version: str,
    context_signals_used: int,
    context_files_used: int,
    human_notes_provided: bool,
    validation_passed: bool,
    retry_count: int,
    prompt_estimated_tokens: int,
) -> None:
    """
    Append _tool_b_meta to pattern and write to out_path.

    _tool_b_meta is appended AFTER validation — never included during validation.
    """
    output = dict(pattern)  # shallow copy

    output["_tool_b_meta"] = {
        "generated_by":            "tool_b",
        "tool_b_version":          "1.0",
        "agent":                   agent,
        "agent_model":             agent_model,
        "generated_at":            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_jsonl":            source_jsonl,
        "jsonl_schema_version":    jsonl_schema_version,
        "context_signals_used":    context_signals_used,
        "context_files_used":      context_files_used,
        "human_notes_provided":    human_notes_provided,
        "validation_passed":       validation_passed,
        "retry_count":             retry_count,
        "prompt_estimated_tokens": prompt_estimated_tokens,
    }

    p = Path(out_path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        print(f"Error: could not write output file '{out_path}': {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"pattern.json written to: {out_path}")
