"""
JSONL serializer (v2).

Output layout (three-section format):
  Line 0     : global_stats  (record_type: "global_stats")
  Lines 1–N  : file records  (record_type: "file")
  Last line  : skipped_files_summary  (record_type: "skipped_files_summary")
"""

import json
import dataclasses
from typing import Any, Dict, List

from .models import FileRecord, SkippedFile


def _default(obj):
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _dump(obj: Any) -> str:
    return json.dumps(obj, default=_default, ensure_ascii=False)


def write_jsonl(
    global_stats: Dict[str, Any],
    file_records: List[FileRecord],
    skipped_files: List[SkippedFile],
    output_path: str,
) -> None:
    """Write the three-section JSONL output."""
    with open(output_path, "w", encoding="utf-8") as fh:
        # ── Line 0: global_stats ──────────────────────────────────────────────
        fh.write(_dump(global_stats) + "\n")

        # ── Lines 1-N: file records ───────────────────────────────────────────
        for record in file_records:
            fh.write(_dump(_file_record_to_dict(record)) + "\n")

        # ── Last line: skipped_files_summary ──────────────────────────────────
        skipped_list = [dataclasses.asdict(s) for s in skipped_files]
        fh.write(
            _dump(
                {
                    "record_type": "skipped_files_summary",
                    "skipped_files": skipped_list,
                }
            )
            + "\n"
        )


def _file_record_to_dict(record: FileRecord) -> Dict[str, Any]:
    d = dataclasses.asdict(record)

    # Normalise signal lists: each element is already a dict via asdict()
    # but we want to ensure the structure matches the spec exactly.
    # dataclasses.asdict() handles nested dataclasses recursively.
    return d
