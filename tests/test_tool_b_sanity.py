"""tests/test_tool_b_sanity.py — Sanity tests for ToolB.

Runs tool_b.py as a subprocess to test CLI behavior end-to-end.
All tests are deterministic using --agent mock.

Run with: python -m pytest tests/test_tool_b_sanity.py -v
      or: python tests/test_tool_b_sanity.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────

ROOT     = Path(__file__).parent.parent
TOOL_B   = ROOT / "tool_b.py"
FIXTURES = ROOT / "fixtures"

JSONL_LARAVEL       = FIXTURES / "fixture_global_stats_laravel.jsonl"
JSONL_WORDPRESS     = FIXTURES / "fixture_global_stats_wordpress.jsonl"
MOCK_VALID          = FIXTURES / "fixture_mock_agent_valid.json"
MOCK_MALFORMED      = FIXTURES / "fixture_mock_agent_malformed.txt"
MOCK_INVALID_SCHEMA = FIXTURES / "fixture_mock_agent_invalid_schema.json"
HUMAN_NOTES         = FIXTURES / "fixture_human_notes.txt"

PYTHON = sys.executable


def _run(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run tool_b.py with the given arguments."""
    cmd = [PYTHON, str(TOOL_B)] + list(args)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd or str(ROOT),
    )


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_schema_version_1_exits_2() -> None:
    """JSONL with schema_version '1.0' -> exit code 2."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as f:
        f.write('{"record_type": "global_stats", "schema_version": "1.0", "framework": {}, "scan_summary": {}}\n')
        tmp_path = f.name

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            out = str(Path(tmpdir) / "pattern.json")
            result = _run("generate", "--jsonl", tmp_path, "--out", out)
        assert result.returncode == 2, (
            f"Expected exit 2 for schema_version 1.0, got {result.returncode}\n"
            f"stderr: {result.stderr}"
        )
        print("PASS test_schema_version_1_exits_2")
    finally:
        os.unlink(tmp_path)


def test_agent_not_in_path_exits_7() -> None:
    """Agent not in PATH -> exit code 7."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out = str(Path(tmpdir) / "pattern.json")
        result = _run(
            "generate",
            "--jsonl", str(JSONL_LARAVEL),
            "--out",   out,
            "--agent", "claude",  # likely not in PATH in CI
        )
    # Only assert exit 7 if claude is NOT in PATH
    import shutil
    if shutil.which("claude") is None:
        assert result.returncode == 7, (
            f"Expected exit 7 for missing agent, got {result.returncode}\n"
            f"stderr: {result.stderr}"
        )
        print("PASS test_agent_not_in_path_exits_7")
    else:
        print("SKIP test_agent_not_in_path_exits_7 (claude is in PATH)")


def test_mock_malformed_exits_4() -> None:
    """Mock agent returns malformed JSON -> repair retry triggered -> exit code 4."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out = str(Path(tmpdir) / "pattern.json")
        result = _run(
            "generate",
            "--jsonl",             str(JSONL_LARAVEL),
            "--out",               out,
            "--agent",             "mock",
            "--mock-response-file", str(MOCK_MALFORMED),
        )
    assert result.returncode == 4, (
        f"Expected exit 4 for malformed JSON, got {result.returncode}\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    print("PASS test_mock_malformed_exits_4")


def test_mock_valid_writes_pattern_json() -> None:
    """Mock agent returns valid response -> pattern.json written -> validation passes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out = str(Path(tmpdir) / "pattern.json")
        result = _run(
            "generate",
            "--jsonl",             str(JSONL_LARAVEL),
            "--out",               out,
            "--agent",             "mock",
            "--mock-response-file", str(MOCK_VALID),
        )
        assert result.returncode == 0, (
            f"Expected exit 0 for valid mock, got {result.returncode}\n"
            f"stderr: {result.stderr}\nstdout: {result.stdout}"
        )
        assert Path(out).exists(), "pattern.json was not written"
        data = json.loads(Path(out).read_text(encoding="utf-8"))
        assert "_tool_b_meta" in data, "pattern.json missing _tool_b_meta"
        assert "scoring" in data
        print("PASS test_mock_valid_writes_pattern_json")


def test_pattern_json_has_tool_b_meta_with_agent_name() -> None:
    """pattern.json must contain _tool_b_meta with correct agent name."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out = str(Path(tmpdir) / "pattern.json")
        result = _run(
            "generate",
            "--jsonl",             str(JSONL_LARAVEL),
            "--out",               out,
            "--agent",             "mock",
            "--mock-response-file", str(MOCK_VALID),
        )
        assert result.returncode == 0
        data = json.loads(Path(out).read_text(encoding="utf-8"))
        meta = data.get("_tool_b_meta", {})
        assert meta.get("agent") == "mock", f"Expected agent='mock', got {meta.get('agent')!r}"
        assert meta.get("generated_by") == "tool_b"
        assert meta.get("tool_b_version") == "1.0"
        print("PASS test_pattern_json_has_tool_b_meta_with_agent_name")


def test_thresholds_uncertain_lt_endpoint() -> None:
    """thresholds.uncertain < thresholds.endpoint in output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out = str(Path(tmpdir) / "pattern.json")
        result = _run(
            "generate",
            "--jsonl",             str(JSONL_LARAVEL),
            "--out",               out,
            "--agent",             "mock",
            "--mock-response-file", str(MOCK_VALID),
        )
        assert result.returncode == 0
        data = json.loads(Path(out).read_text(encoding="utf-8"))
        t = data["scoring"]["thresholds"]
        assert t["uncertain"] < t["endpoint"], (
            f"uncertain ({t['uncertain']}) must be < endpoint ({t['endpoint']})"
        )
        print("PASS test_thresholds_uncertain_lt_endpoint")


def test_all_signal_names_in_jsonl() -> None:
    """All signal names in output must exist in JSONL signal_frequency_table."""
    import json as _json

    global_stats = _json.loads(JSONL_LARAVEL.read_text(encoding="utf-8").splitlines()[0])
    known = {s["signal"] for s in global_stats.get("signal_frequency_table", [])}
    known |= {h["name"] for h in global_stats.get("custom_helper_registry", [])}

    with tempfile.TemporaryDirectory() as tmpdir:
        out = str(Path(tmpdir) / "pattern.json")
        result = _run(
            "generate",
            "--jsonl",             str(JSONL_LARAVEL),
            "--out",               out,
            "--agent",             "mock",
            "--mock-response-file", str(MOCK_VALID),
        )
        assert result.returncode == 0
        data = _json.loads(Path(out).read_text(encoding="utf-8"))

        scoring = data.get("scoring", {})
        all_sigs = (
            scoring.get("strong_signals",   []) +
            scoring.get("weak_signals",     []) +
            scoring.get("negative_signals", [])
        )
        for sig in all_sigs:
            name = sig.get("name", "")
            assert name in known, (
                f"Signal name '{name}' not found in JSONL signal_frequency_table"
            )
        print("PASS test_all_signal_names_in_jsonl")


def test_dry_run_no_output_file() -> None:
    """--dry-run -> no pattern.json written, exit code 0."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out = str(Path(tmpdir) / "pattern.json")
        result = _run(
            "generate",
            "--jsonl",             str(JSONL_LARAVEL),
            "--out",               out,
            "--agent",             "mock",
            "--mock-response-file", str(MOCK_VALID),
            "--dry-run",
        )
        assert result.returncode == 0, (
            f"Expected exit 0 for dry-run, got {result.returncode}\n"
            f"stderr: {result.stderr}"
        )
        assert not Path(out).exists(), "pattern.json should NOT be written in dry-run mode"
        assert "Dry Run" in result.stdout
        print("PASS test_dry_run_no_output_file")


def test_check_agents_exits_0() -> None:
    """check-agents subcommand -> prints availability table, exit code 0."""
    result = _run("check-agents")
    assert result.returncode == 0, (
        f"Expected exit 0 for check-agents, got {result.returncode}\n"
        f"stderr: {result.stderr}"
    )
    assert "Agent Availability" in result.stdout
    assert "claude" in result.stdout
    assert "codex"  in result.stdout
    assert "gemini" in result.stdout
    print("PASS test_check_agents_exits_0")


def test_mock_invalid_schema_exits_6() -> None:
    """Mock agent returns valid JSON with schema violations -> exit code 6 after correction retry."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out = str(Path(tmpdir) / "pattern.json")
        result = _run(
            "generate",
            "--jsonl",             str(JSONL_LARAVEL),
            "--out",               out,
            "--agent",             "mock",
            "--mock-response-file", str(MOCK_INVALID_SCHEMA),
        )
    # Should fail validation (V3: uncertain >= endpoint, V4: negative weight > 0)
    # After correction retry (also returns same invalid JSON), exits 6
    assert result.returncode == 6, (
        f"Expected exit 6 for invalid schema fixture, got {result.returncode}\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    print("PASS test_mock_invalid_schema_exits_6")


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_schema_version_1_exits_2,
        test_agent_not_in_path_exits_7,
        test_mock_malformed_exits_4,
        test_mock_valid_writes_pattern_json,
        test_pattern_json_has_tool_b_meta_with_agent_name,
        test_thresholds_uncertain_lt_endpoint,
        test_all_signal_names_in_jsonl,
        test_dry_run_no_output_file,
        test_check_agents_exits_0,
        test_mock_invalid_schema_exits_6,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as exc:
            print(f"FAIL {test.__name__}: {exc}")
            failed += 1
        except Exception as exc:
            print(f"ERROR {test.__name__}: {type(exc).__name__}: {exc}")
            failed += 1

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    sys.exit(0 if failed == 0 else 1)
