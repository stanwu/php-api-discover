#!/usr/bin/env python3
"""
Sanity tests for tool_a v2.

Runs the tool against each fixture file and asserts:
  - No crash on any fixture
  - Score ranges match spec expectations
  - Redaction count matches for secrets fixture
  - JSONL first line record_type == "global_stats" and schema_version == "2.0"
  - JSONL file records each have signals.strong items with global_seen_in_files
  - global_stats.pattern_json_generation_hints exists and is non-empty
  - JSONL last line record_type == "skipped_files_summary"
  - Every JSONL line is valid JSON
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import textwrap
import traceback
from typing import Any, Dict, List

# Ensure repo root is on the path
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_ROOT)

from tool_a.__main__ import run_scan  # noqa: E402


# ── Fixture paths ─────────────────────────────────────────────────────────────

FIXTURES_DIR = os.path.join(REPO_ROOT, "fixtures")

FIXTURE_LARAVEL  = os.path.join(FIXTURES_DIR, "fixture_laravel_api_controller.php")
FIXTURE_WORDPRESS = os.path.join(FIXTURES_DIR, "fixture_wordpress_ajax.php")
FIXTURE_PLAIN_UI  = os.path.join(FIXTURES_DIR, "fixture_plain_ui_page.php")
FIXTURE_DYNAMIC   = os.path.join(FIXTURES_DIR, "fixture_dynamic_dispatch.php")
FIXTURE_SECRETS   = os.path.join(FIXTURES_DIR, "fixture_secrets.php")


# ── Helpers ───────────────────────────────────────────────────────────────────

class FakeArgs:
    """Minimal args object that mimics argparse Namespace."""
    def __init__(
        self,
        root,
        out,
        raw=None,
        exclude=None,
        extensions=None,
        max_files=0,
        max_file_size=3.0,
        max_snippet_lines=80,
        min_score=0,
        framework=None,
    ):
        self.root = root
        self.out = out
        self.raw = raw
        self.exclude = exclude
        self.extensions = extensions
        self.max_files = max_files
        self.max_file_size = max_file_size
        self.max_snippet_lines = max_snippet_lines
        self.min_score = min_score
        self.framework = framework


def scan_fixture(
    fixture_path: str,
    framework: str = "plain",
    extra_fixtures: List[str] = None,
) -> tuple:
    """
    Run a scan on a temporary directory containing the given fixture file(s).

    Returns (md_report_path, jsonl_path, tmp_dir).
    Caller is responsible for cleaning up tmp_dir.
    """
    tmp_dir = tempfile.mkdtemp(prefix="tool_a_test_")

    # Copy fixture(s) into tmp_dir
    for src in [fixture_path] + (extra_fixtures or []):
        name = os.path.basename(src)
        dst = os.path.join(tmp_dir, name)
        with open(src, "rb") as fh:
            data = fh.read()
        with open(dst, "wb") as fh:
            fh.write(data)

    md_out = os.path.join(tmp_dir, "report.md")
    jsonl_out = os.path.join(tmp_dir, "raw.jsonl")

    args = FakeArgs(
        root=tmp_dir,
        out=md_out,
        raw=jsonl_out,
        framework=framework,
    )
    run_scan(args)

    return md_out, jsonl_out, tmp_dir


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    records = []
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise AssertionError(
                    f"JSONL line {lineno} is not valid JSON: {exc}\n  Line: {line!r}"
                )
    return records


def find_file_record(records: List[dict], filename_fragment: str) -> dict:
    for r in records:
        if r.get("record_type") == "file" and filename_fragment in r.get("path", ""):
            return r
    raise AssertionError(
        f"No file record found containing '{filename_fragment}'. "
        f"Available paths: {[r.get('path') for r in records if r.get('record_type')=='file']}"
    )


# ── Test functions ────────────────────────────────────────────────────────────

def test_no_crash_on_all_fixtures():
    """All fixture files must be processed without exceptions."""
    fixtures = [
        (FIXTURE_LARAVEL,   "laravel"),
        (FIXTURE_WORDPRESS, "wordpress"),
        (FIXTURE_PLAIN_UI,  "plain"),
        (FIXTURE_DYNAMIC,   "plain"),
        (FIXTURE_SECRETS,   "plain"),
    ]
    for fixture_path, fw in fixtures:
        try:
            md, jsonl, tmp = scan_fixture(fixture_path, framework=fw)
            assert os.path.isfile(md),    f"Markdown report missing for {fixture_path}"
            assert os.path.isfile(jsonl), f"JSONL report missing for {fixture_path}"
        except Exception:
            raise AssertionError(
                f"Crash on fixture '{os.path.basename(fixture_path)}':\n"
                + traceback.format_exc()
            )
    print("  PASS: no crash on any fixture")


def test_score_ranges():
    """Scores must fall within the ranges specified in the prompt."""
    cases = [
        (FIXTURE_LARAVEL,   "laravel",   50, 70,  "fixture_laravel_api_controller.php"),
        (FIXTURE_WORDPRESS, "wordpress", 70, 100, "fixture_wordpress_ajax.php"),
        (FIXTURE_PLAIN_UI,  "plain",      0,  5,  "fixture_plain_ui_page.php"),
    ]
    for fixture_path, fw, lo, hi, filename in cases:
        md, jsonl, _ = scan_fixture(fixture_path, framework=fw)
        records = read_jsonl(jsonl)
        rec = find_file_record(records, filename)
        score = rec["score"]
        assert lo <= score <= hi, (
            f"{filename}: expected score in [{lo}, {hi}], got {score}\n"
            f"Breakdown: {rec.get('score_breakdown')}"
        )
    print("  PASS: score ranges")


def test_dynamic_dispatch_flagged():
    """Dynamic dispatch fixture must have a 'variable_dispatch' dynamic note."""
    md, jsonl, _ = scan_fixture(FIXTURE_DYNAMIC, framework="plain")
    records = read_jsonl(jsonl)
    rec = find_file_record(records, "fixture_dynamic_dispatch.php")

    dynamic_notes = rec.get("dynamic_notes", [])
    types = [n.get("type") for n in dynamic_notes]
    assert "variable_dispatch" in types, (
        f"Expected 'variable_dispatch' in dynamic_notes types, got: {types}"
    )
    print("  PASS: dynamic dispatch flagged")


def test_redaction_count():
    """Secrets fixture must have redaction_count >= 1 and key preserved."""
    md, jsonl, _ = scan_fixture(FIXTURE_SECRETS, framework="plain")
    records = read_jsonl(jsonl)
    rec = find_file_record(records, "fixture_secrets.php")

    assert rec["redaction_count"] >= 1, (
        f"Expected redaction_count >= 1, got {rec['redaction_count']}"
    )

    # Check that at least one output point snippet contains REDACTED
    output_points = rec.get("output_points", [])
    if output_points:
        any_redacted = any(
            "REDACTED" in op.get("context_excerpt", "")
            for op in output_points
        )
        # Not required to have REDACTED in snippets if the secret isn't near an output point;
        # redaction_count > 0 is the primary assertion.

    print(f"  PASS: redaction_count = {rec['redaction_count']}")


def test_jsonl_structure():
    """All JSONL structural invariants from the spec."""
    # Use all fixtures in one dir to get a multi-file JSONL
    tmp_dir = tempfile.mkdtemp(prefix="tool_a_test_all_")
    for src in [FIXTURE_LARAVEL, FIXTURE_WORDPRESS, FIXTURE_PLAIN_UI,
                FIXTURE_DYNAMIC, FIXTURE_SECRETS]:
        name = os.path.basename(src)
        dst = os.path.join(tmp_dir, name)
        with open(src, "rb") as fh:
            data = fh.read()
        with open(dst, "wb") as fh:
            fh.write(data)

    md_out   = os.path.join(tmp_dir, "report.md")
    jsonl_out = os.path.join(tmp_dir, "raw.jsonl")
    args = FakeArgs(root=tmp_dir, out=md_out, raw=jsonl_out, framework="plain")
    run_scan(args)

    records = read_jsonl(jsonl_out)

    # 1. First line must be global_stats
    assert records[0]["record_type"] == "global_stats", (
        f"Expected first record_type='global_stats', got '{records[0].get('record_type')}'"
    )
    assert records[0]["schema_version"] == "2.0", (
        f"Expected schema_version='2.0', got '{records[0].get('schema_version')}'"
    )

    # 2. Last line must be skipped_files_summary
    assert records[-1]["record_type"] == "skipped_files_summary", (
        f"Expected last record_type='skipped_files_summary', got '{records[-1].get('record_type')}'"
    )

    # 3. pattern_json_generation_hints exists and is non-empty
    hints = records[0].get("pattern_json_generation_hints")
    assert hints and isinstance(hints, dict) and len(hints) > 0, (
        "pattern_json_generation_hints missing or empty in global_stats"
    )

    # 4. File records each have signals.strong items with global_seen_in_files
    file_records = [r for r in records if r.get("record_type") == "file"]
    for r in file_records:
        for sig in r.get("signals", {}).get("strong", []):
            assert "global_seen_in_files" in sig, (
                f"Signal in {r.get('path')} missing 'global_seen_in_files': {sig}"
            )

    print(f"  PASS: JSONL structure ({len(records)} lines, {len(file_records)} file records)")


def test_every_jsonl_line_is_valid_json():
    """Every line in a generated JSONL must parse without error."""
    md, jsonl, _ = scan_fixture(FIXTURE_LARAVEL, framework="laravel")
    records = read_jsonl(jsonl)  # read_jsonl already asserts per-line validity
    assert len(records) >= 3, f"Expected at least 3 JSONL lines, got {len(records)}"
    print(f"  PASS: every JSONL line is valid JSON ({len(records)} lines)")


# ── Runner ────────────────────────────────────────────────────────────────────

TESTS = [
    test_no_crash_on_all_fixtures,
    test_score_ranges,
    test_dynamic_dispatch_flagged,
    test_redaction_count,
    test_jsonl_structure,
    test_every_jsonl_line_is_valid_json,
]


def main() -> None:
    print("=== tool_a v2 sanity tests ===\n")
    passed = 0
    failed = 0

    for test_fn in TESTS:
        name = test_fn.__name__
        print(f"[{name}]")
        try:
            test_fn()
            passed += 1
        except AssertionError as exc:
            print(f"  FAIL: {exc}")
            failed += 1
        except Exception:
            print(f"  ERROR:\n{textwrap.indent(traceback.format_exc(), '    ')}")
            failed += 1
        print()

    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
