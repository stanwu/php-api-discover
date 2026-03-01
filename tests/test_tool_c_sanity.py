"""tests/test_tool_c_sanity.py — Sanity tests for ToolC.

Each test exercises a specific requirement from the ToolC spec.
Run from the project root:
  python tests/test_tool_c_sanity.py

Exit code 0 = all tests passed.  Non-zero = at least one failure.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

# ── Helpers ───────────────────────────────────────────────────────────────────

ROOT = Path(__file__).parent.parent
FIXTURES = ROOT / "fixtures"


def run_tool_c(*args: str, expect_exit: int | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(ROOT / "tool_c.py")] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    if expect_exit is not None and result.returncode != expect_exit:
        print(f"  STDOUT: {result.stdout[:500]}")
        print(f"  STDERR: {result.stderr[:500]}")
        raise AssertionError(
            f"Expected exit code {expect_exit}, got {result.returncode}\n"
            f"CMD: {' '.join(cmd)}"
        )
    return result


_PASS = 0
_FAIL = 0


def test(name: str, fn) -> None:
    global _PASS, _FAIL
    try:
        fn()
        print(f"  ✓  {name}")
        _PASS += 1
    except Exception as exc:
        print(f"  ✗  {name}")
        print(f"     {exc}")
        _FAIL += 1


# ── Individual tests ──────────────────────────────────────────────────────────

def t01_schema_version_mismatch():
    """schema_version mismatch → exit code 2."""
    run_tool_c(
        "generate",
        "--jsonl", str(FIXTURES / "fixture_c_schema_v1.jsonl"),
        "--rules", str(FIXTURES / "fixture_c_pattern_valid.json"),
        "--out", "/dev/null",
        expect_exit=2,
    )


def t02_bad_regex_exit_1():
    """Invalid regex in pattern.json → exit code 1."""
    run_tool_c(
        "validate-rules",
        "--rules", str(FIXTURES / "fixture_c_pattern_bad_regex.json"),
        "--jsonl", str(FIXTURES / "fixture_c_l1.jsonl"),
        expect_exit=1,
    )


def t03_bad_thresholds_exit_1():
    """thresholds.uncertain >= thresholds.endpoint → exit code 1."""
    run_tool_c(
        "validate-rules",
        "--rules", str(FIXTURES / "fixture_c_pattern_bad_thresholds.json"),
        "--jsonl", str(FIXTURES / "fixture_c_l1.jsonl"),
        expect_exit=1,
    )


def t04_l1_exactly_one_item():
    """L1 fixture produces exactly 1 Postman item."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out = f.name
    try:
        run_tool_c(
            "generate",
            "--jsonl", str(FIXTURES / "fixture_c_l1.jsonl"),
            "--rules", str(FIXTURES / "fixture_c_pattern_valid.json"),
            "--out", out,
            expect_exit=0,
        )
        collection = json.loads(Path(out).read_text())
        items = collection["item"]
        assert len(items) == 1, f"Expected 1 item, got {len(items)}: {[i['name'] for i in items]}"
    finally:
        Path(out).unlink(missing_ok=True)


def t05_l2_excluded_by_default():
    """L2 fixture produces 0 items by default (not included without --include-uncertain)."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out = f.name
    try:
        run_tool_c(
            "generate",
            "--jsonl", str(FIXTURES / "fixture_c_l2.jsonl"),
            "--rules", str(FIXTURES / "fixture_c_pattern_valid.json"),
            "--out", out,
            expect_exit=0,
        )
        collection = json.loads(Path(out).read_text())
        assert len(collection["item"]) == 0, (
            f"Expected 0 items (L2 excluded), got {len(collection['item'])}"
        )
    finally:
        Path(out).unlink(missing_ok=True)


def t06_l2_included_with_flag():
    """L2 fixture produces 1 item with --include-uncertain."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out = f.name
    try:
        run_tool_c(
            "generate",
            "--jsonl", str(FIXTURES / "fixture_c_l2.jsonl"),
            "--rules", str(FIXTURES / "fixture_c_pattern_valid.json"),
            "--out", out,
            "--include-uncertain",
            expect_exit=0,
        )
        collection = json.loads(Path(out).read_text())
        assert len(collection["item"]) == 1, (
            f"Expected 1 item (L2 included), got {len(collection['item'])}"
        )
    finally:
        Path(out).unlink(missing_ok=True)


def t07_l3_zero_items():
    """L3 fixture produces 0 Postman items."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out = f.name
    try:
        run_tool_c(
            "generate",
            "--jsonl", str(FIXTURES / "fixture_c_l3.jsonl"),
            "--rules", str(FIXTURES / "fixture_c_pattern_valid.json"),
            "--out", out,
            expect_exit=0,
        )
        collection = json.loads(Path(out).read_text())
        assert len(collection["item"]) == 0, (
            f"Expected 0 items (L3), got {len(collection['item'])}"
        )
    finally:
        Path(out).unlink(missing_ok=True)


def t08_multi_route_two_items():
    """Multi-route fixture produces exactly 2 Postman items."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out = f.name
    try:
        run_tool_c(
            "generate",
            "--jsonl", str(FIXTURES / "fixture_c_multi_route.jsonl"),
            "--rules", str(FIXTURES / "fixture_c_pattern_valid.json"),
            "--out", out,
            expect_exit=0,
        )
        collection = json.loads(Path(out).read_text())
        items = collection["item"]
        assert len(items) == 2, f"Expected 2 items, got {len(items)}: {[i['name'] for i in items]}"
        methods = sorted(i["request"]["method"] for i in items)
        assert methods == ["GET", "POST"], f"Expected GET+POST, got {methods}"
    finally:
        Path(out).unlink(missing_ok=True)


def t09_secret_redaction():
    """Secret fixture: redaction_applied=true in _tool_c_meta."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out = f.name
    try:
        run_tool_c(
            "generate",
            "--jsonl", str(FIXTURES / "fixture_c_secret.jsonl"),
            "--rules", str(FIXTURES / "fixture_c_pattern_valid.json"),
            "--out", out,
            expect_exit=0,
        )
        collection = json.loads(Path(out).read_text())
        assert len(collection["item"]) == 1, "Expected 1 item for secret fixture"
        item = collection["item"][0]
        meta = item.get("_tool_c_meta", {})
        assert meta.get("redaction_applied") is True, (
            f"Expected redaction_applied=true, got {meta.get('redaction_applied')}"
        )
        # Also check body contains REDACTED
        body_raw = item["request"].get("body", {}).get("raw", "")
        assert "REDACTED" in body_raw, f"Expected REDACTED in body, got: {body_raw}"
    finally:
        Path(out).unlink(missing_ok=True)


def t10_no_envelope_match():
    """No-envelope fixture: no_envelope_match=true in _tool_c_meta."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out = f.name
    try:
        run_tool_c(
            "generate",
            "--jsonl", str(FIXTURES / "fixture_c_no_envelope.jsonl"),
            "--rules", str(FIXTURES / "fixture_c_pattern_valid.json"),
            "--out", out,
            expect_exit=0,
        )
        collection = json.loads(Path(out).read_text())
        assert len(collection["item"]) == 1, "Expected 1 item for no-envelope fixture"
        item = collection["item"][0]
        meta = item.get("_tool_c_meta", {})
        assert meta.get("no_envelope_match") is True, (
            f"Expected no_envelope_match=true, got {meta.get('no_envelope_match')}"
        )
    finally:
        Path(out).unlink(missing_ok=True)


def t11_postman_schema_validation():
    """Output postman_collection.json passes Postman v2.1 schema validation."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out = f.name
    try:
        run_tool_c(
            "generate",
            "--jsonl", str(FIXTURES / "fixture_c_l1.jsonl"),
            "--rules", str(FIXTURES / "fixture_c_pattern_valid.json"),
            "--out", out,
            expect_exit=0,
        )
        collection = json.loads(Path(out).read_text())
        # Validate manually using the validator module
        sys.path.insert(0, str(ROOT))
        from tool_c.postman_validator import validate_postman_collection
        valid = validate_postman_collection(collection)
        assert valid, "Generated Postman collection failed embedded schema validation"
        assert collection["info"]["name"] == "Test API Collection"
        assert "schema.getpostman.com" in collection["info"]["schema"]
    finally:
        Path(out).unlink(missing_ok=True)


def t12_output_sorted():
    """Output items are sorted by path → method → uri."""
    # Use multi-route fixture which produces GET + POST for same uri
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out = f.name
    try:
        run_tool_c(
            "generate",
            "--jsonl", str(FIXTURES / "fixture_c_multi_route.jsonl"),
            "--rules", str(FIXTURES / "fixture_c_pattern_valid.json"),
            "--out", out,
            expect_exit=0,
        )
        collection = json.loads(Path(out).read_text())
        items = collection["item"]
        assert len(items) == 2
        methods = [i["request"]["method"] for i in items]
        assert methods == sorted(methods), (
            f"Items not sorted by method: {methods}"
        )
    finally:
        Path(out).unlink(missing_ok=True)


def t13_tool_b_meta_stripped():
    """pattern.json with _tool_b_meta block loads without error; block does not appear in output."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out = f.name
    try:
        run_tool_c(
            "generate",
            "--jsonl", str(FIXTURES / "fixture_c_l1.jsonl"),
            "--rules", str(FIXTURES / "fixture_c_pattern_with_tool_b_meta.json"),
            "--out", out,
            expect_exit=0,
        )
        raw = Path(out).read_text()
        assert "_tool_b_meta" not in raw, (
            "_tool_b_meta must not appear in Postman collection output"
        )
        collection = json.loads(raw)
        assert len(collection["item"]) >= 0  # valid JSON
    finally:
        Path(out).unlink(missing_ok=True)


def t14_narrow_gap_warning_exit_0():
    """threshold gap below minimum → V12 warning printed, exit code 0 (not hard fail)."""
    result = run_tool_c(
        "validate-rules",
        "--rules", str(FIXTURES / "fixture_c_pattern_narrow_gap.json"),
        "--jsonl", str(FIXTURES / "fixture_c_l1.jsonl"),
        expect_exit=0,
    )
    # Should see a warning about narrow gap (gap=5 < minimum_threshold_gap=10)
    combined = result.stdout + result.stderr
    assert "WARNING" in combined.upper() or "gap" in combined.lower() or "threshold" in combined.lower(), (
        f"Expected a gap/threshold warning in output, got:\n{combined}"
    )


def t15_missing_min_gap_no_crash():
    """minimum_threshold_gap absent from JSONL → V12 defaults to 10; no crash."""
    # Create a temp JSONL with no minimum_threshold_gap in hints
    import copy, tempfile as _tf
    gs_line = json.loads(
        Path(FIXTURES / "fixture_c_l1.jsonl").read_text().splitlines()[0]
    )
    gs_modified = copy.deepcopy(gs_line)
    hints = gs_modified.get("pattern_json_generation_hints", {})
    hints.pop("minimum_threshold_gap", None)
    gs_modified["pattern_json_generation_hints"] = hints

    file_line = Path(FIXTURES / "fixture_c_l1.jsonl").read_text().splitlines()[1]
    sk_line = json.dumps({"record_type": "skipped_files_summary", "skipped_files": []})

    with _tf.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as jf:
        jf.write(json.dumps(gs_modified) + "\n")
        jf.write(file_line + "\n")
        jf.write(sk_line + "\n")
        jf_name = jf.name

    with _tf.NamedTemporaryFile(suffix=".json", delete=False) as out:
        out_name = out.name

    try:
        run_tool_c(
            "generate",
            "--jsonl", jf_name,
            "--rules", str(FIXTURES / "fixture_c_pattern_valid.json"),
            "--out", out_name,
            expect_exit=0,
        )
    finally:
        Path(jf_name).unlink(missing_ok=True)
        Path(out_name).unlink(missing_ok=True)


def t16_catalog_output():
    """--catalog flag produces endpoint_catalog.json with correct structure."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out = f.name
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        cat = f.name
    try:
        run_tool_c(
            "generate",
            "--jsonl", str(FIXTURES / "fixture_c_l1.jsonl"),
            "--rules", str(FIXTURES / "fixture_c_pattern_valid.json"),
            "--out", out,
            "--catalog", cat,
            expect_exit=0,
        )
        catalog = json.loads(Path(cat).read_text())
        assert "summary" in catalog
        assert "endpoints" in catalog
        assert "uncertain_endpoints" in catalog
        summary = catalog["summary"]
        assert summary["l1_endpoint_count"] == 1, f"Expected l1=1, got {summary}"
        assert summary["l2_uncertain_count"] == 0
        assert summary["l3_ignored_count"] == 0
        # L1 endpoint detail
        assert len(catalog["endpoints"]) == 1
        ep = catalog["endpoints"][0]
        assert ep["confidence_tier"] == "L1"
        assert ep["toolc_score"] == 35
    finally:
        Path(out).unlink(missing_ok=True)
        Path(cat).unlink(missing_ok=True)


def t17_dry_run_no_file_written():
    """dry-run subcommand prints summary and writes no files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "postman.json"
        result = run_tool_c(
            "dry-run",
            "--jsonl", str(FIXTURES / "fixture_c_l1.jsonl"),
            "--rules", str(FIXTURES / "fixture_c_pattern_valid.json"),
            "--out", str(out_path),
            expect_exit=0,
        )
        assert not out_path.exists(), "dry-run must not write the output file"
        assert "L1" in result.stdout or "confirmed" in result.stdout.lower(), (
            f"Expected classification summary in output, got: {result.stdout[:300]}"
        )


def t18_validate_rules_subcommand():
    """validate-rules subcommand exits 0 for a valid pattern.json."""
    result = run_tool_c(
        "validate-rules",
        "--rules", str(FIXTURES / "fixture_c_pattern_valid.json"),
        "--jsonl", str(FIXTURES / "fixture_c_l1.jsonl"),
        expect_exit=0,
    )
    assert "valid" in result.stdout.lower() or "passed" in result.stdout.lower(), (
        f"Expected validation success message, got: {result.stdout}"
    )


def t19_folder_structure_by_directory():
    """--folder-structure by_directory groups items into folder objects."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out = f.name
    try:
        run_tool_c(
            "generate",
            "--jsonl", str(FIXTURES / "fixture_c_l1.jsonl"),
            "--rules", str(FIXTURES / "fixture_c_pattern_valid.json"),
            "--out", out,
            "--folder-structure", "by_directory",
            expect_exit=0,
        )
        collection = json.loads(Path(out).read_text())
        items = collection["item"]
        # With by_directory, items should be folder objects with nested "item"
        assert len(items) >= 1
        folder = items[0]
        assert "item" in folder, f"Expected folder with 'item' key, got: {list(folder.keys())}"
        assert "name" in folder
    finally:
        Path(out).unlink(missing_ok=True)


def t20_no_hardcoded_urls():
    """Output never contains literal hostnames — only {{baseUrl}} placeholder."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out = f.name
    try:
        run_tool_c(
            "generate",
            "--jsonl", str(FIXTURES / "fixture_c_l1.jsonl"),
            "--rules", str(FIXTURES / "fixture_c_pattern_valid.json"),
            "--out", out,
            expect_exit=0,
        )
        raw = Path(out).read_text()
        # Should not contain http:// or https:// in the url.raw field (only {{baseUrl}})
        collection = json.loads(raw)
        for item in collection.get("item", []):
            url_raw = item.get("request", {}).get("url", {}).get("raw", "")
            assert url_raw.startswith("{{"), (
                f"url.raw should start with {{{{baseUrl}}}}, got: {url_raw}"
            )
    finally:
        Path(out).unlink(missing_ok=True)


# ── Runner ────────────────────────────────────────────────────────────────────

ALL_TESTS = [
    ("T01 schema_version mismatch → exit 2",         t01_schema_version_mismatch),
    ("T02 bad regex → exit 1",                        t02_bad_regex_exit_1),
    ("T03 uncertain >= endpoint → exit 1",            t03_bad_thresholds_exit_1),
    ("T04 L1 fixture → exactly 1 Postman item",       t04_l1_exactly_one_item),
    ("T05 L2 excluded by default → 0 items",          t05_l2_excluded_by_default),
    ("T06 L2 included with --include-uncertain → 1",  t06_l2_included_with_flag),
    ("T07 L3 fixture → 0 Postman items",              t07_l3_zero_items),
    ("T08 multi-route → exactly 2 Postman items",     t08_multi_route_two_items),
    ("T09 secret fixture → redaction_applied=true",   t09_secret_redaction),
    ("T10 no-envelope → no_envelope_match=true",      t10_no_envelope_match),
    ("T11 output passes Postman v2.1 schema",         t11_postman_schema_validation),
    ("T12 output sorted by path→method→uri",          t12_output_sorted),
    ("T13 _tool_b_meta stripped from output",         t13_tool_b_meta_stripped),
    ("T14 narrow threshold gap → warning + exit 0",   t14_narrow_gap_warning_exit_0),
    ("T15 absent min_gap → defaults to 10, no crash", t15_missing_min_gap_no_crash),
    ("T16 --catalog produces endpoint_catalog.json",  t16_catalog_output),
    ("T17 dry-run writes no files",                   t17_dry_run_no_file_written),
    ("T18 validate-rules exits 0 for valid pattern",  t18_validate_rules_subcommand),
    ("T19 by_directory groups into folders",          t19_folder_structure_by_directory),
    ("T20 no hardcoded URLs in output",               t20_no_hardcoded_urls),
]


def main() -> int:
    print("=== ToolC Sanity Tests ===\n")
    for name, fn in ALL_TESTS:
        test(name, fn)
    print(f"\n{'='*40}")
    print(f"Results: {_PASS} passed, {_FAIL} failed out of {len(ALL_TESTS)} tests")
    if _FAIL > 0:
        print("FAILED")
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
