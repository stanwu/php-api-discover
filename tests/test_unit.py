"""
Unit tests for tool_a v2, tool_b v1, tool_c v1 — pytest edition.

Covers:
  tool_a:
  - scorer        : score_file() clamping and summation
  - redactor      : redact_secrets() all four pattern rules
  - scanner       : collect_files() filtering, max_files, size limit
  - framework_detector : detect_framework() forced / fingerprint / fallback
  - detector helpers   : _extract_params, _extract_envelope_keys,
                         _extract_method_hints, _classify_output
  - helper_registry    : build, count_calls, finalize_stats, get_call_pattern
  - __main__ helpers   : _fpr_reason, _score_percentiles, _compute_co_occurrence

  tool_b:
  - toolchain_validator : V1-V13 rules
  - context_selector    : select_signals, select_file_records, estimate_tokens
  - prompt_assembler    : assemble_prompt block presence

  tool_c:
  - classifier          : compute_toolc_score, classify_files, tiers
  - method_inferrer     : all 5 inference sources
  - envelope_matcher    : match_envelope template logic
  - redactor            : redact_body, param_placeholder
  - postman_builder     : build_collection, body generation, folder grouping
  - postman_validator   : validate_postman_collection
  - catalog_writer      : build_catalog structure
  - jsonl_reader        : read_jsonl schema validation
"""

from __future__ import annotations

import os
import re
import sys
import tempfile

import pytest

# ── ensure repo root is importable ───────────────────────────────────────────
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)


# =============================================================================
# scorer
# =============================================================================

from tool_a.scorer import score_file
from tool_a.models import ScoreBreakdownItem


class TestScoreFile:
    def _item(self, delta: int, kind: str = "strong") -> ScoreBreakdownItem:
        return ScoreBreakdownItem(signal="s", kind=kind, delta=delta, line_no=1)

    def test_empty_breakdown_returns_zero(self):
        assert score_file([]) == 0

    def test_single_delta(self):
        assert score_file([self._item(40)]) == 40

    def test_sum_of_multiple_deltas(self):
        items = [self._item(30), self._item(20), self._item(10)]
        assert score_file(items) == 60

    def test_clamped_to_100(self):
        items = [self._item(70), self._item(60)]
        assert score_file(items) == 100

    def test_clamped_to_zero_on_negative_sum(self):
        items = [self._item(-50), self._item(-40)]
        assert score_file(items) == 0

    def test_negative_delta_reduces_score(self):
        items = [self._item(50), self._item(-10, kind="negative")]
        assert score_file(items) == 40

    def test_exact_boundary_100(self):
        assert score_file([self._item(100)]) == 100

    def test_exact_boundary_0(self):
        assert score_file([self._item(0)]) == 0


# =============================================================================
# redactor
# =============================================================================

from tool_a.redactor import redact_secrets


class TestRedactSecrets:
    # Pattern 1 — assignment with quoted value (≥ 8 chars)
    def test_api_key_assignment_single_quotes(self):
        text = "api_key = 'mySecretValue123'"
        result, count = redact_secrets(text)
        assert count >= 1
        assert "REDACTED" in result
        assert "mySecretValue123" not in result

    def test_password_assignment_double_quotes(self):
        text = 'password = "hunter2hunter2"'
        result, count = redact_secrets(text)
        assert count >= 1
        assert "REDACTED" in result

    def test_short_value_not_redacted_by_pattern1(self):
        # Value < 8 chars should NOT be caught by pattern 1
        text = "token = 'abc'"
        result, count = redact_secrets(text)
        # 'abc' is 3 chars → not matched by pattern 1
        # also too short for pattern 2 (< 32 chars)
        assert "abc" in result

    # Pattern 2 — long alphanumeric string (≥ 32 chars)
    def test_long_alphanumeric_string_redacted(self):
        long_token = "A" * 32
        text = f'$token = "{long_token}";'
        result, count = redact_secrets(text)
        assert count >= 1
        assert long_token not in result
        assert "REDACTED" in result

    def test_31_char_string_not_redacted_by_pattern2(self):
        short_token = "B" * 31
        text = f'$val = "{short_token}";'
        result, _ = redact_secrets(text)
        assert short_token in result

    # Pattern 3 — Bearer token
    def test_bearer_token_redacted(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        result, count = redact_secrets(text)
        assert count >= 1
        assert "REDACTED" in result
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result

    def test_bearer_prefix_preserved(self):
        text = "Authorization: Bearer mytoken12345"
        result, _ = redact_secrets(text)
        assert result.startswith("Authorization: Bearer REDACTED")

    # Pattern 4 — getenv() left unchanged
    def test_getenv_not_redacted(self):
        text = "getenv('DATABASE_PASSWORD')"
        result, count = redact_secrets(text)
        assert result == text
        assert count == 0

    # Multiple patterns in same string
    def test_count_accumulates_across_patterns(self):
        long_str = "X" * 32
        text = f'api_key = "longlonglongvalue"; $t = "{long_str}";'
        _, count = redact_secrets(text)
        assert count >= 2

    def test_returns_tuple(self):
        result = redact_secrets("no secrets here")
        assert isinstance(result, tuple)
        assert len(result) == 2


# =============================================================================
# scanner
# =============================================================================

from tool_a.scanner import collect_files, DEFAULT_EXCLUDE_DIRS


class TestCollectFiles:
    def _make_php(self, directory: str, name: str, content: str = "<?php\n") -> str:
        path = os.path.join(directory, name)
        with open(path, "w") as fh:
            fh.write(content)
        return path

    def test_collects_php_files(self, tmp_path):
        self._make_php(str(tmp_path), "a.php")
        self._make_php(str(tmp_path), "b.php")
        paths, skipped = collect_files(str(tmp_path), None, None, 3.0)
        assert len(paths) == 2
        assert skipped == []

    def test_ignores_non_php_by_default(self, tmp_path):
        self._make_php(str(tmp_path), "a.php")
        (tmp_path / "readme.txt").write_text("hello")
        paths, _ = collect_files(str(tmp_path), None, None, 3.0)
        assert all(p.endswith(".php") for p in paths)

    def test_custom_extensions(self, tmp_path):
        self._make_php(str(tmp_path), "a.php")
        (tmp_path / "b.inc").write_text("<?php")
        paths, _ = collect_files(str(tmp_path), None, [".inc"], 3.0)
        assert len(paths) == 1
        assert paths[0].endswith("b.inc")

    def test_excludes_default_dirs(self, tmp_path):
        vendor = tmp_path / "vendor"
        vendor.mkdir()
        self._make_php(str(vendor), "lib.php")
        self._make_php(str(tmp_path), "main.php")
        paths, _ = collect_files(str(tmp_path), None, None, 3.0)
        assert len(paths) == 1
        assert "vendor" not in paths[0]

    def test_custom_exclude_dirs(self, tmp_path):
        skip_dir = tmp_path / "skip_me"
        skip_dir.mkdir()
        self._make_php(str(skip_dir), "hidden.php")
        self._make_php(str(tmp_path), "visible.php")
        paths, _ = collect_files(str(tmp_path), ["skip_me"], None, 3.0)
        assert len(paths) == 1
        assert "visible.php" in paths[0]

    def test_skips_files_over_size_limit(self, tmp_path):
        big = tmp_path / "big.php"
        big.write_bytes(b"x" * (4 * 1024 * 1024))  # 4 MB
        small_path = self._make_php(str(tmp_path), "small.php")
        paths, skipped = collect_files(str(tmp_path), [], None, 3.0)
        assert len(paths) == 1
        assert len(skipped) == 1
        assert skipped[0]["reason"] == "too_large"
        assert skipped[0]["size_mb"] > 3.0

    def test_max_files_limit(self, tmp_path):
        for i in range(5):
            self._make_php(str(tmp_path), f"f{i}.php")
        paths, _ = collect_files(str(tmp_path), [], None, 3.0, max_files=3)
        assert len(paths) == 3

    def test_empty_directory(self, tmp_path):
        paths, skipped = collect_files(str(tmp_path), None, None, 3.0)
        assert paths == []
        assert skipped == []

    def test_returned_paths_are_sorted(self, tmp_path):
        for name in ["c.php", "a.php", "b.php"]:
            self._make_php(str(tmp_path), name)
        paths, _ = collect_files(str(tmp_path), [], None, 3.0)
        basenames = [os.path.basename(p) for p in paths]
        assert basenames == sorted(basenames)


# =============================================================================
# framework_detector
# =============================================================================

from tool_a.framework_detector import detect_framework


class TestDetectFramework:
    def test_forced_framework_returned_as_is(self, tmp_path):
        fw, conf, evidence = detect_framework(str(tmp_path), "laravel")
        assert fw == "laravel"
        assert conf == "forced"
        assert any("forced" in e for e in evidence)

    def test_forced_invalid_framework_falls_back_to_plain(self, tmp_path):
        fw, conf, _ = detect_framework(str(tmp_path), "nonexistent")
        assert fw == "plain"
        assert conf == "forced"

    def test_detects_laravel_by_artisan_and_controllers(self, tmp_path):
        (tmp_path / "artisan").write_text("#!/usr/bin/env php")
        (tmp_path / "app" / "Http" / "Controllers").mkdir(parents=True)
        fw, conf, _ = detect_framework(str(tmp_path))
        assert fw == "laravel"
        assert conf == "high"

    def test_detects_wordpress_by_wp_config(self, tmp_path):
        (tmp_path / "wp-config.php").write_text("<?php")
        fw, conf, _ = detect_framework(str(tmp_path))
        assert fw == "wordpress"
        assert conf == "high"

    def test_detects_wordpress_by_wp_includes_dir(self, tmp_path):
        (tmp_path / "wp-includes").mkdir()
        fw, conf, _ = detect_framework(str(tmp_path))
        assert fw == "wordpress"
        assert conf == "high"

    def test_detects_symfony_by_lock_file(self, tmp_path):
        (tmp_path / "symfony.lock").write_text("{}")
        fw, conf, _ = detect_framework(str(tmp_path))
        assert fw == "symfony"
        assert conf == "high"

    def test_detects_codeigniter_by_core_file(self, tmp_path):
        (tmp_path / "system" / "core").mkdir(parents=True)
        (tmp_path / "system" / "core" / "CodeIgniter.php").write_text("<?php")
        fw, conf, _ = detect_framework(str(tmp_path))
        assert fw == "codeigniter"
        assert conf == "high"

    def test_detects_slim_from_composer_json(self, tmp_path):
        import json
        composer = {"require": {"slim/slim": "^4.0"}}
        (tmp_path / "composer.json").write_text(json.dumps(composer))
        fw, conf, _ = detect_framework(str(tmp_path))
        assert fw == "slim"
        assert conf == "high"

    def test_falls_back_to_plain_with_no_fingerprints(self, tmp_path):
        fw, conf, evidence = detect_framework(str(tmp_path))
        assert fw == "plain"
        assert conf == "low"


# =============================================================================
# detector — module-level helpers
# =============================================================================

from tool_a.detector import (
    _extract_params,
    _extract_envelope_keys,
    _extract_method_hints,
    _classify_output,
)
from tool_a.detector import _GET_RE, _POST_RE, _REQUEST_RE


class TestExtractParams:
    def test_extracts_get_param(self):
        lines = ['$id = $_GET["id"];']
        params = _extract_params(_GET_RE, lines)
        assert len(params) == 1
        assert params[0].key == "id"
        assert params[0].line_no == 1

    def test_extracts_post_param(self):
        lines = ["$name = $_POST['name'];"]
        params = _extract_params(_POST_RE, lines)
        assert params[0].key == "name"

    def test_extracts_multiple_params(self):
        lines = ['$a = $_GET["a"];', '$b = $_GET["b"];']
        params = _extract_params(_GET_RE, lines)
        assert {p.key for p in params} == {"a", "b"}

    def test_deduplicates_same_key(self):
        lines = ['$a = $_GET["x"];', '$b = $_GET["x"];']
        params = _extract_params(_GET_RE, lines)
        assert len(params) == 1

    def test_returns_empty_on_no_match(self):
        lines = ["echo 'hello';"]
        params = _extract_params(_GET_RE, lines)
        assert params == []

    def test_line_number_is_one_indexed(self):
        lines = ["", '$x = $_GET["y"];']
        params = _extract_params(_GET_RE, lines)
        assert params[0].line_no == 2


class TestExtractEnvelopeKeys:
    def test_detects_ok_key(self):
        lines = ["$resp = ['ok' => true];"]
        keys = _extract_envelope_keys(lines)
        assert any(k.key == "ok" for k in keys)

    def test_detects_multiple_keys(self):
        lines = ["return ['success' => true, 'data' => $data, 'message' => 'done'];"]
        keys = _extract_envelope_keys(lines)
        key_names = {k.key for k in keys}
        assert "success" in key_names
        assert "data" in key_names
        assert "message" in key_names

    def test_keys_lowercased(self):
        lines = ["['OK' => 1]"]
        keys = _extract_envelope_keys(lines)
        assert all(k.key == k.key.lower() for k in keys)

    def test_deduplicates_same_key_across_lines(self):
        lines = ["['ok' => 1]", "['ok' => 2]"]
        keys = _extract_envelope_keys(lines)
        assert len([k for k in keys if k.key == "ok"]) == 1

    def test_no_false_positive_on_unrelated_words(self):
        lines = ["$x = 'nothing';"]
        keys = _extract_envelope_keys(lines)
        assert keys == []


class TestExtractMethodHints:
    def test_detects_post_method(self):
        lines = ['if ($_SERVER["REQUEST_METHOD"] === "POST") {']
        hints = _extract_method_hints(lines)
        assert any(h["method"] == "POST" for h in hints)

    def test_detects_get_method(self):
        lines = ["if ($_SERVER['REQUEST_METHOD'] == 'GET') {"]
        hints = _extract_method_hints(lines)
        assert any(h["method"] == "GET" for h in hints)

    def test_deduplicates_same_method(self):
        lines = [
            "if ($_SERVER['REQUEST_METHOD'] == 'POST') {",
            "if ($_SERVER['REQUEST_METHOD'] === 'POST') {",
        ]
        hints = _extract_method_hints(lines)
        assert len([h for h in hints if h["method"] == "POST"]) == 1

    def test_no_match_on_unrelated_content(self):
        lines = ["echo 'hello';"]
        hints = _extract_method_hints(lines)
        assert hints == []


class TestClassifyOutput:
    def test_response_json(self):
        assert _classify_output("return response()->json($data);") == "response()->json("

    def test_wp_send_json_success(self):
        assert _classify_output("wp_send_json_success($data);") == "wp_send_json_success("

    def test_wp_send_json_error(self):
        assert _classify_output("wp_send_json_error($msg);") == "wp_send_json_error("

    def test_wp_send_json_generic(self):
        assert _classify_output("wp_send_json($data);") == "wp_send_json("

    def test_json_response_class(self):
        assert _classify_output("return new JsonResponse($data);") == "new JsonResponse("

    def test_this_json(self):
        assert _classify_output("return $this->json($data);") == "$this->json("

    def test_response_with_json(self):
        assert _classify_output("$response->withJson($data);") == "$response->withJson("

    def test_json_encode(self):
        assert _classify_output("echo json_encode($arr);") == "json_encode("

    def test_unknown_falls_back_to_output(self):
        assert _classify_output("echo $x;") == "output"


# =============================================================================
# helper_registry
# =============================================================================

from tool_a.helper_registry import HelperRegistry, HelperEntry


class TestHelperRegistry:
    def _write_php(self, directory: str, name: str, content: str) -> str:
        path = os.path.join(directory, name)
        with open(path, "w") as fh:
            fh.write(content)
        return path

    def test_empty_registry_has_no_helpers(self):
        reg = HelperRegistry()
        assert len(reg.helpers) == 0

    def test_build_detects_json_helper_function(self, tmp_path):
        php = "<?php\nfunction send_api_response($data) {\n    echo json_encode($data);\n}\n"
        path = self._write_php(str(tmp_path), "helpers.php", php)
        reg = HelperRegistry()
        reg.build_from_files([path], str(tmp_path))
        assert "send_api_response" in reg.helpers

    def test_build_skips_class_methods(self, tmp_path):
        php = "<?php\nclass Foo {\n    public function index($data) {\n        echo json_encode($data);\n    }\n}\n"
        path = self._write_php(str(tmp_path), "ctrl.php", php)
        reg = HelperRegistry()
        reg.build_from_files([path], str(tmp_path))
        assert "index" not in reg.helpers

    def test_get_call_pattern_returns_none_when_empty(self):
        reg = HelperRegistry()
        assert reg.get_call_pattern() is None

    def test_get_call_pattern_matches_helper(self, tmp_path):
        php = "<?php\nfunction my_json($d) {\n    echo json_encode($d);\n}\n"
        path = self._write_php(str(tmp_path), "h.php", php)
        reg = HelperRegistry()
        reg.build_from_files([path], str(tmp_path))
        pat = reg.get_call_pattern()
        assert pat is not None
        assert pat.search("my_json($result);")

    def test_count_calls_increments_per_file(self, tmp_path):
        php = "<?php\nfunction my_json($d) {\n    echo json_encode($d);\n}\n"
        path = self._write_php(str(tmp_path), "h.php", php)
        reg = HelperRegistry()
        reg.build_from_files([path], str(tmp_path))
        reg.count_calls_in_content("my_json($a); my_json($b);")
        assert reg._call_counts.get("my_json", 0) == 1  # one file, not two calls

    def test_finalize_stats_sets_seen_in_files(self, tmp_path):
        php = "<?php\nfunction my_json($d) {\n    echo json_encode($d);\n}\n"
        path = self._write_php(str(tmp_path), "h.php", php)
        reg = HelperRegistry()
        reg.build_from_files([path], str(tmp_path))
        reg.count_calls_in_content("my_json($a);")
        reg.finalize_stats(total_candidate_files=5)
        entry = reg.helpers["my_json"]
        assert entry.seen_called_in_files == 1
        assert entry.pct_of_candidates == 20.0

    def test_to_jsonl_list_contains_all_keys(self, tmp_path):
        php = "<?php\nfunction my_json($d) {\n    echo json_encode($d);\n}\n"
        path = self._write_php(str(tmp_path), "h.php", php)
        reg = HelperRegistry()
        reg.build_from_files([path], str(tmp_path))
        lst = reg.to_jsonl_list()
        assert len(lst) == 1
        expected_keys = {
            "helper_name", "defined_in", "wraps_signal", "wrap_depth",
            "seen_called_in_files", "pct_of_candidates",
            "suggested_kind", "suggested_weight_hint",
        }
        assert expected_keys == set(lst[0].keys())


# =============================================================================
# __main__ — pure stats helpers
# =============================================================================

from tool_a.__main__ import _fpr_reason, _score_percentiles, _compute_co_occurrence
from tool_a.models import FileRecord, SignalMatch


class TestFprReason:
    def test_low_risk_reason(self):
        reason = _fpr_reason("low", "some_signal")
        assert "rarely" in reason.lower() or "native" in reason.lower()

    def test_medium_risk_reason(self):
        reason = _fpr_reason("medium", "some_signal")
        assert reason != "n/a"

    def test_high_risk_reason(self):
        reason = _fpr_reason("high", "some_signal")
        assert "generic" in reason.lower() or "strong" in reason.lower()

    def test_unknown_risk_returns_na(self):
        reason = _fpr_reason("other", "signal")
        assert reason == "n/a"


class TestScorePercentiles:
    def test_empty_returns_zeros(self):
        result = _score_percentiles([])
        assert result == {"p25": 0, "p50": 0, "p75": 0, "p90": 0}

    def test_single_value(self):
        result = _score_percentiles([50])
        assert result["p50"] == 50

    def test_even_distribution(self):
        scores = list(range(0, 100, 10))  # [0,10,20,...,90]
        result = _score_percentiles(scores)
        assert result["p25"] <= result["p50"] <= result["p75"] <= result["p90"]

    def test_all_same_value(self):
        result = _score_percentiles([42] * 10)
        assert result["p25"] == 42
        assert result["p75"] == 42

    def test_returns_dict_with_four_keys(self):
        result = _score_percentiles([10, 20, 30])
        assert set(result.keys()) == {"p25", "p50", "p75", "p90"}


class TestComputeCoOccurrence:
    def _make_record(self, *signal_names: str) -> FileRecord:
        rec = FileRecord(path="test.php", framework="plain")
        for name in signal_names:
            rec.signals["strong"].append(
                SignalMatch(name=name, occurrences=1, line_nos=[1],
                            global_seen_in_files=1, false_positive_risk="low")
            )
        return rec

    def test_empty_records_returns_empty(self):
        assert _compute_co_occurrence([]) == []

    def test_single_signal_no_pairs(self):
        records = [self._make_record("sig_a")]
        result = _compute_co_occurrence(records)
        assert result == []

    def test_two_signals_one_pair(self):
        records = [self._make_record("sig_a", "sig_b")]
        result = _compute_co_occurrence(records)
        assert len(result) == 1
        assert set(result[0]["signals"]) == {"sig_a", "sig_b"}
        assert result[0]["files_count"] == 1

    def test_count_accumulates_across_files(self):
        records = [
            self._make_record("sig_a", "sig_b"),
            self._make_record("sig_a", "sig_b"),
        ]
        result = _compute_co_occurrence(records)
        assert result[0]["files_count"] == 2

    def test_returns_at_most_5_pairs(self):
        # 5 signals → 10 pairs; we expect only top 5
        records = [self._make_record("a", "b", "c", "d", "e")]
        result = _compute_co_occurrence(records)
        assert len(result) <= 5

    def test_result_sorted_by_count_descending(self):
        records = [
            self._make_record("x", "y"),
            self._make_record("x", "y"),
            self._make_record("x", "z"),
        ]
        result = _compute_co_occurrence(records)
        counts = [r["files_count"] for r in result]
        assert counts == sorted(counts, reverse=True)


# =============================================================================
# toolchain_validator — V1–V13 validation rules
# =============================================================================

import json as _json

from toolchain.toolchain_validator import validate_pattern_json, ValidationResult


def _valid_pattern() -> dict:
    return {
        "version": "1.0",
        "source_jsonl_schema_version": "2.0",
        "framework": "laravel",
        "scoring": {
            "strong_signals": [
                {"name": "return response()->json(", "pattern": r"return response\(\)->json\(", "weight": 35, "kind": "strong"},
            ],
            "weak_signals": [
                {"name": "json_encode(", "pattern": r"json_encode\(", "weight": 10, "kind": "weak"},
            ],
            "negative_signals": [
                {"name": "return view(", "pattern": r"return view\(", "weight": -15, "kind": "negative"},
            ],
            "thresholds": {"endpoint": 40, "uncertain": 20},
        },
        "endpoint_envelopes": {"templates": []},
        "method_inference": {
            "priority_order": ["route_hints", "request_method_check", "input_param_type", "signal_based", "default"],
            "rules": [],
            "default_method": "GET",
        },
        "postman_defaults": {
            "collection_name": "API Collection",
            "base_url_variable": "baseUrl",
            "auth_token_variable": "authToken",
            "default_headers": [{"key": "Accept", "value": "application/json", "disabled": False}],
            "auth_header": {"key": "Authorization", "value_template": "Bearer {{authToken}}"},
        },
    }


def _valid_global_stats() -> dict:
    return {
        "framework": {"detected": "laravel"},
        "signal_frequency_table": [
            {"signal": "return response()->json("},
            {"signal": "json_encode("},
            {"signal": "return view("},
        ],
        "custom_helper_registry": [],
        "pattern_json_generation_hints": {"minimum_threshold_gap": 10},
    }


class TestValidatorHappyPath:
    def test_valid_pattern_passes(self):
        result = validate_pattern_json(_valid_pattern(), _valid_global_stats())
        assert result.valid
        assert result.errors == []

    def test_returns_validation_result_instance(self):
        result = validate_pattern_json(_valid_pattern())
        assert isinstance(result, ValidationResult)

    def test_v11_underscore_keys_stripped_silently(self):
        p = _valid_pattern()
        p["_tool_b_meta"] = {"agent": "mock", "generated_by": "tool_b"}
        result = validate_pattern_json(p, _valid_global_stats())
        assert result.valid  # _tool_b_meta must not cause V1 failure

    def test_no_global_stats_still_validates_structure(self):
        result = validate_pattern_json(_valid_pattern(), None)
        # V6, V8, V12 are skipped — structural checks still run
        assert result.valid


class TestValidatorV1Structure:
    def test_missing_framework_field_fails(self):
        p = _valid_pattern()
        del p["framework"]
        result = validate_pattern_json(p)
        assert not result.valid
        assert any("V1" in e or "framework" in e.lower() for e in result.errors)

    def test_missing_scoring_field_fails(self):
        p = _valid_pattern()
        del p["scoring"]
        result = validate_pattern_json(p)
        assert not result.valid

    def test_wrong_framework_enum_fails(self):
        p = _valid_pattern()
        p["framework"] = "rails"
        result = validate_pattern_json(p)
        assert not result.valid

    def test_missing_thresholds_fails(self):
        p = _valid_pattern()
        del p["scoring"]["thresholds"]
        result = validate_pattern_json(p)
        assert not result.valid


class TestValidatorV2Regex:
    def test_bad_regex_in_strong_signal_fails(self):
        p = _valid_pattern()
        p["scoring"]["strong_signals"][0]["pattern"] = "["  # unclosed bracket
        result = validate_pattern_json(p)
        assert not result.valid
        assert any("V2" in e for e in result.errors)

    def test_bad_regex_in_negative_signal_fails(self):
        p = _valid_pattern()
        p["scoring"]["negative_signals"][0]["pattern"] = "(?P<bad"
        result = validate_pattern_json(p)
        assert not result.valid
        assert any("V2" in e for e in result.errors)

    def test_valid_regex_passes(self):
        p = _valid_pattern()
        p["scoring"]["weak_signals"][0]["pattern"] = r"json_encode\s*\("
        result = validate_pattern_json(p, _valid_global_stats())
        assert result.valid


class TestValidatorV3Thresholds:
    def test_uncertain_equals_endpoint_fails(self):
        p = _valid_pattern()
        p["scoring"]["thresholds"] = {"endpoint": 40, "uncertain": 40}
        result = validate_pattern_json(p)
        assert not result.valid
        assert any("V3" in e for e in result.errors)

    def test_uncertain_greater_than_endpoint_fails(self):
        p = _valid_pattern()
        p["scoring"]["thresholds"] = {"endpoint": 30, "uncertain": 50}
        result = validate_pattern_json(p)
        assert not result.valid
        assert any("V3" in e for e in result.errors)

    def test_uncertain_less_than_endpoint_passes(self):
        p = _valid_pattern()
        p["scoring"]["thresholds"] = {"endpoint": 40, "uncertain": 20}
        result = validate_pattern_json(p, _valid_global_stats())
        assert result.valid


class TestValidatorV4V5Weights:
    def test_negative_signal_with_positive_weight_fails_v4(self):
        p = _valid_pattern()
        p["scoring"]["negative_signals"][0]["weight"] = 5
        result = validate_pattern_json(p)
        assert not result.valid
        assert any("V4" in e for e in result.errors)

    def test_negative_signal_with_zero_weight_fails_v4(self):
        p = _valid_pattern()
        p["scoring"]["negative_signals"][0]["weight"] = 0
        result = validate_pattern_json(p)
        assert not result.valid
        assert any("V4" in e for e in result.errors)

    def test_strong_signal_with_zero_weight_fails_v5(self):
        p = _valid_pattern()
        p["scoring"]["strong_signals"][0]["weight"] = 0
        result = validate_pattern_json(p)
        assert not result.valid
        assert any("V5" in e for e in result.errors)

    def test_strong_signal_with_negative_weight_fails_v5(self):
        p = _valid_pattern()
        p["scoring"]["strong_signals"][0]["weight"] = -10
        result = validate_pattern_json(p)
        assert not result.valid
        assert any("V5" in e for e in result.errors)


class TestValidatorV6SignalNames:
    def test_unknown_signal_name_fails(self):
        p = _valid_pattern()
        p["scoring"]["strong_signals"][0]["name"] = "totally_invented_signal_xyz"
        result = validate_pattern_json(p, _valid_global_stats())
        assert not result.valid
        assert any("V6" in e for e in result.errors)

    def test_signal_from_custom_helper_registry_passes(self):
        p = _valid_pattern()
        p["scoring"]["weak_signals"].append(
            {"name": "my_helper", "pattern": r"my_helper\(", "weight": 5, "kind": "weak"}
        )
        gs = _valid_global_stats()
        gs["custom_helper_registry"].append({"name": "my_helper"})
        result = validate_pattern_json(p, gs)
        assert result.valid

    def test_v6_skipped_when_global_stats_is_none(self):
        p = _valid_pattern()
        p["scoring"]["strong_signals"][0]["name"] = "anything_not_in_jsonl"
        result = validate_pattern_json(p, None)
        assert not any("V6" in e for e in result.errors)


class TestValidatorV7Envelope:
    def test_example_key_outside_allowed_fails(self):
        p = _valid_pattern()
        p["endpoint_envelopes"]["templates"] = [{
            "name": "t1",
            "keys_all_of": ["data"],
            "keys_any_of": ["message"],
            "example": {"data": {}, "message": "", "extra_key": ""},
        }]
        result = validate_pattern_json(p, _valid_global_stats())
        assert not result.valid
        assert any("V7" in e for e in result.errors)

    def test_valid_example_keys_pass(self):
        p = _valid_pattern()
        p["endpoint_envelopes"]["templates"] = [{
            "name": "t1",
            "keys_all_of": ["data"],
            "keys_any_of": ["message"],
            "example": {"data": {}, "message": ""},
        }]
        result = validate_pattern_json(p, _valid_global_stats())
        assert result.valid


class TestValidatorV8V12V13Warnings:
    def test_v8_framework_mismatch_is_warning_only(self):
        p = _valid_pattern()
        p["framework"] = "wordpress"
        gs = _valid_global_stats()
        gs["framework"]["detected"] = "laravel"
        result = validate_pattern_json(p, gs)
        assert result.valid
        assert any("V8" in w for w in result.warnings)

    def test_v13_wrong_schema_version_is_warning_only(self):
        p = _valid_pattern()
        p["source_jsonl_schema_version"] = "1.0"
        result = validate_pattern_json(p, _valid_global_stats())
        assert result.valid
        assert any("V13" in w for w in result.warnings)

    def test_v12_gap_too_small_is_warning_only(self):
        p = _valid_pattern()
        p["scoring"]["thresholds"] = {"endpoint": 30, "uncertain": 25}  # gap=5, min=10
        gs = _valid_global_stats()
        gs["pattern_json_generation_hints"]["minimum_threshold_gap"] = 10
        result = validate_pattern_json(p, gs)
        assert result.valid
        assert any("V12" in w for w in result.warnings)


class TestValidatorV9V10:
    def test_v9_duplicate_template_names_fail(self):
        p = _valid_pattern()
        tmpl = {"name": "dup", "keys_all_of": ["data"], "keys_any_of": ["msg"], "example": {"data": {}, "msg": ""}}
        p["endpoint_envelopes"]["templates"] = [tmpl, dict(tmpl)]
        result = validate_pattern_json(p, _valid_global_stats())
        assert not result.valid
        assert any("V9" in e for e in result.errors)

    def test_v10_priority_order_not_ending_default_fails(self):
        p = _valid_pattern()
        p["method_inference"]["priority_order"] = ["route_hints", "signal_based"]
        result = validate_pattern_json(p)
        assert not result.valid
        assert any("V10" in e for e in result.errors)

    def test_v10_empty_priority_order_fails(self):
        p = _valid_pattern()
        p["method_inference"]["priority_order"] = []
        result = validate_pattern_json(p)
        assert not result.valid
        assert any("V10" in e for e in result.errors)


# =============================================================================
# tool_b.jsonl_reader
# =============================================================================

from tool_b.jsonl_reader import read_jsonl


class TestReadJsonl:
    def _write(self, tmp_path, lines: list[str]) -> str:
        p = tmp_path / "test.jsonl"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(p)

    def _gs(self, schema_version: str = "2.0") -> str:
        return _json.dumps({
            "record_type": "global_stats",
            "schema_version": schema_version,
            "framework": {"detected": "plain"},
            "scan_summary": {},
            "signal_frequency_table": [],
            "custom_helper_registry": [],
            "envelope_key_frequency": [],
            "method_distribution": {},
            "co_occurrence_patterns": [],
            "pattern_json_generation_hints": {},
        })

    def _rec(self, path: str = "api.php", score: int = 50) -> str:
        return _json.dumps({
            "record_type": "file",
            "schema_version": "2.0",
            "path": path,
            "score": score,
            "signals": {"strong": [], "weak": [], "negative": []},
        })

    def test_valid_jsonl_returns_global_stats_and_records(self, tmp_path):
        p = self._write(tmp_path, [self._gs(), self._rec("a.php", 60), self._rec("b.php", 30)])
        gs, records = read_jsonl(p)
        assert gs["record_type"] == "global_stats"
        assert len(records) == 2

    def test_schema_version_1_exits_2(self, tmp_path):
        p = self._write(tmp_path, [self._gs("1.0")])
        with pytest.raises(SystemExit) as exc:
            read_jsonl(p)
        assert exc.value.code == 2

    def test_missing_file_exits_8(self, tmp_path):
        with pytest.raises(SystemExit) as exc:
            read_jsonl(str(tmp_path / "no_such_file.jsonl"))
        assert exc.value.code == 8

    def test_empty_file_exits_8(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.write_text("", encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            read_jsonl(str(p))
        assert exc.value.code == 8

    def test_skipped_files_summary_excluded(self, tmp_path):
        p = self._write(tmp_path, [
            self._gs(),
            self._rec("api.php"),
            _json.dumps({"record_type": "skipped_files_summary", "skipped_files": []}),
        ])
        _, records = read_jsonl(p)
        assert len(records) == 1

    def test_zero_score_record_included(self, tmp_path):
        p = self._write(tmp_path, [self._gs(), self._rec("zero.php", score=0)])
        _, records = read_jsonl(p)
        assert len(records) == 1

    def test_only_file_records_returned(self, tmp_path):
        p = self._write(tmp_path, [
            self._gs(),
            self._rec("api.php"),
            _json.dumps({"record_type": "other_type", "data": 1}),
        ])
        _, records = read_jsonl(p)
        assert all(r["record_type"] == "file" for r in records)


# =============================================================================
# tool_b.context_selector
# =============================================================================

from tool_b.context_selector import (
    select_signals, select_file_records, estimate_tokens, get_agent_token_limit,
)


class TestSelectSignals:
    def _gs(self, counts: list[int]) -> dict:
        return {"signal_frequency_table": [
            {"signal": f"sig_{i}", "seen_in_files": c} for i, c in enumerate(counts)
        ]}

    def test_sorted_by_seen_in_files_desc(self):
        result = select_signals(self._gs([10, 50, 30]), max_signals=10)
        counts = [s["seen_in_files"] for s in result]
        assert counts == sorted(counts, reverse=True)

    def test_respects_max_signals(self):
        result = select_signals(self._gs([10, 20, 30, 40, 50]), max_signals=3)
        assert len(result) == 3

    def test_returns_all_when_under_limit(self):
        result = select_signals(self._gs([10, 20]), max_signals=50)
        assert len(result) == 2

    def test_empty_table_returns_empty(self):
        result = select_signals({"signal_frequency_table": []}, max_signals=10)
        assert result == []

    def test_tie_broken_by_signal_name_asc(self):
        gs = {"signal_frequency_table": [
            {"signal": "zzz_sig", "seen_in_files": 10},
            {"signal": "aaa_sig", "seen_in_files": 10},
        ]}
        result = select_signals(gs, max_signals=10)
        assert result[0]["signal"] == "aaa_sig"


class TestSelectFileRecords:
    def _r(self, path: str, score: int) -> dict:
        return {"path": path, "score": score}

    def test_sorted_by_score_desc_then_path_asc(self):
        records = [self._r("b.php", 50), self._r("a.php", 50), self._r("c.php", 80)]
        result = select_file_records(records, max_files=10)
        assert result[0]["path"] == "c.php"
        assert result[1]["path"] == "a.php"
        assert result[2]["path"] == "b.php"

    def test_respects_max_files(self):
        records = [self._r(f"f{i}.php", i) for i in range(10)]
        result = select_file_records(records, max_files=5)
        assert len(result) == 5

    def test_deterministic_with_same_input(self):
        records = [self._r(f"f{i}.php", i % 3) for i in range(6)]
        r1 = select_file_records(records, max_files=10)
        r2 = select_file_records(records, max_files=10)
        assert [r["path"] for r in r1] == [r["path"] for r in r2]

    def test_empty_returns_empty(self):
        assert select_file_records([], max_files=10) == []

    def test_top_scored_files_selected(self):
        records = [self._r(f"f{i}.php", i * 10) for i in range(10)]
        result = select_file_records(records, max_files=3)
        scores = [r["score"] for r in result]
        assert min(scores) >= 70


class TestEstimateTokens:
    def test_empty_string_is_zero(self):
        assert estimate_tokens("") == 0

    def test_four_chars_is_one_token(self):
        assert estimate_tokens("abcd") == 1

    def test_scales_linearly(self):
        assert estimate_tokens("a" * 400) == 100


class TestGetAgentTokenLimit:
    def test_claude(self):
        assert get_agent_token_limit("claude") == 150_000

    def test_codex(self):
        assert get_agent_token_limit("codex") == 100_000

    def test_gemini(self):
        assert get_agent_token_limit("gemini") == 800_000

    def test_unknown_defaults_to_claude_limit(self):
        assert get_agent_token_limit("unknown_agent") == 150_000


# =============================================================================
# tool_b.response_parser
# =============================================================================

from tool_b.response_parser import extract_json_from_text


class TestExtractJsonFromText:
    def test_bare_json_object(self):
        result = extract_json_from_text('{"version": "1.0", "framework": "laravel"}')
        assert result == {"version": "1.0", "framework": "laravel"}

    def test_json_in_fenced_json_block(self):
        text = 'Here is the output:\n```json\n{"version": "1.0"}\n```\nDone.'
        result = extract_json_from_text(text)
        assert result is not None
        assert result["version"] == "1.0"

    def test_json_in_plain_fenced_block(self):
        text = '```\n{"framework": "plain"}\n```'
        result = extract_json_from_text(text)
        assert result is not None
        assert result["framework"] == "plain"

    def test_returns_none_for_non_json(self):
        result = extract_json_from_text("Sorry, I cannot help with that.")
        assert result is None

    def test_returns_none_for_json_array(self):
        result = extract_json_from_text("[1, 2, 3]")
        assert result is None

    def test_returns_largest_block_when_multiple(self):
        small = '{"a": 1}'
        large = '{"version": "1.0", "framework": "laravel", "scoring": {"thresholds": {"endpoint": 40}}}'
        text = f'```json\n{small}\n```\n\nOr:\n```json\n{large}\n```'
        result = extract_json_from_text(text)
        assert result is not None
        assert "version" in result

    def test_prose_before_brace_span_parsed(self):
        text = 'Here is the pattern:\n{"version": "1.0"}\nEnd.'
        result = extract_json_from_text(text)
        assert result is not None
        assert result["version"] == "1.0"

    def test_malformed_json_returns_none(self):
        result = extract_json_from_text('{"version": "1.0", "incomplete"')
        assert result is None

    def test_nested_object_fully_parsed(self):
        text = '{"outer": {"inner": {"deep": true}}}'
        result = extract_json_from_text(text)
        assert result["outer"]["inner"]["deep"] is True


# =============================================================================
# tool_b.agents — adapters
# =============================================================================

from tool_b.agents.base import AgentError
from tool_b.agents.claude import ClaudeAdapter
from tool_b.agents.codex import CodexAdapter
from tool_b.agents.gemini import GeminiAdapter
from tool_b.agents.mock import MockAdapter


class TestClaudeAdapter:
    def test_build_command_has_print_and_model_flags(self):
        cmd = ClaudeAdapter().build_command("my prompt", "claude-sonnet-4-5")
        assert "claude" in cmd
        assert "--print" in cmd
        assert "--model" in cmd
        assert "claude-sonnet-4-5" in cmd
        assert "-p" in cmd
        assert "my prompt" in cmd

    def test_build_command_uses_default_model_when_none(self):
        cmd = ClaudeAdapter().build_command("p", None)
        assert "claude-opus-4-5" in cmd

    def test_parse_response_raises_on_nonzero_returncode(self):
        with pytest.raises(AgentError):
            ClaudeAdapter().parse_response("", "error", 1)

    def test_parse_response_raises_on_empty_stdout(self):
        with pytest.raises(AgentError):
            ClaudeAdapter().parse_response("   ", "", 0)

    def test_parse_response_returns_stdout_on_success(self):
        out = ClaudeAdapter().parse_response('{"version": "1.0"}', "", 0)
        assert '{"version": "1.0"}' in out


class TestCodexAdapter:
    def test_build_command_has_full_auto_and_quiet(self):
        cmd = CodexAdapter().build_command("p", None)
        assert "--quiet" in cmd
        assert "--full-auto" in cmd
        assert "--approval-policy" in cmd
        assert "auto-edit" in cmd

    def test_default_model_is_gpt4o(self):
        assert CodexAdapter().default_model == "gpt-4o"

    def test_parse_response_raises_on_nonzero_returncode(self):
        with pytest.raises(AgentError):
            CodexAdapter().parse_response("", "err", 2)


class TestGeminiAdapter:
    def test_build_command_has_model_and_p_flags(self):
        cmd = GeminiAdapter().build_command("p", "gemini-2.5-pro")
        assert "gemini" in cmd
        assert "--model" in cmd
        assert "gemini-2.5-pro" in cmd
        assert "-p" in cmd

    def test_default_model_is_flash(self):
        assert GeminiAdapter().default_model == "gemini-2.0-flash"

    def test_parse_response_raises_on_empty_stdout(self):
        with pytest.raises(AgentError):
            GeminiAdapter().parse_response("", "", 0)


class TestMockAdapter:
    def test_raises_when_no_response_file_set(self):
        with pytest.raises(AgentError):
            MockAdapter(response_file=None).read_response_file()

    def test_raises_when_response_file_missing(self, tmp_path):
        with pytest.raises(AgentError):
            MockAdapter(response_file=str(tmp_path / "missing.json")).read_response_file()

    def test_returns_file_content(self, tmp_path):
        f = tmp_path / "resp.json"
        f.write_text('{"version": "1.0"}', encoding="utf-8")
        content = MockAdapter(response_file=str(f)).read_response_file()
        assert '{"version": "1.0"}' in content

    def test_parse_response_raises_on_nonzero_returncode(self):
        with pytest.raises(AgentError):
            MockAdapter().parse_response("", "", 1)

    def test_name_is_mock(self):
        assert MockAdapter.name == "mock"


# =============================================================================
# tool_b.prompt_assembler
# =============================================================================

from tool_b.prompt_assembler import assemble_prompt


def _asm_global_stats() -> dict:
    return {
        "framework": {"detected": "laravel", "confidence": "high", "evidence": ["artisan found"]},
        "scan_summary": {
            "total_files_scanned": 100, "total_files_skipped": 5,
            "candidate_files_above_score_0": 60,
            "candidate_files_above_score_30": 30,
            "candidate_files_above_score_60": 10,
        },
        "signal_frequency_table": [
            {"signal": "return response()->json(", "kind": "strong", "seen_in_files": 40,
             "pct_of_candidates": 66.7, "false_positive_risk": "low",
             "false_positive_risk_reason": "native"},
        ],
        "custom_helper_registry": [],
        "envelope_key_frequency": [{"key": "data", "seen_in_files": 35, "pct_of_candidates": 58.3}],
        "method_distribution": {"GET": 20, "POST": 15},
        "co_occurrence_patterns": [],
        "pattern_json_generation_hints": {
            "recommended_strong_signals": ["return response()->json("],
            "recommended_weak_signals": [],
            "recommended_negative_signals": [],
            "recommended_endpoint_threshold": 40,
            "endpoint_threshold_basis": "cluster at 40",
            "recommended_uncertain_threshold": 20,
            "uncertain_threshold_basis": "weak-only below 20",
            "minimum_threshold_gap": 10,
            "minimum_threshold_gap_note": "enforce 10",
            "score_distribution_summary": {"p25": 10, "p50": 30, "p75": 50, "p90": 70, "note": "ok"},
            "recommended_envelope_template": {"keys_all_of": ["data"], "keys_any_of": ["message"]},
            "warning": "review required",
        },
    }


def _asm_signals() -> list[dict]:
    return [{"signal": "return response()->json(", "kind": "strong", "seen_in_files": 40,
              "pct_of_candidates": 66.7, "false_positive_risk": "low",
              "false_positive_risk_reason": "native"}]


def _asm_files() -> list[dict]:
    return [{"path": "app/Http/Controllers/Api/UserController.php", "score": 75,
             "signals": {"strong": [], "weak": [], "negative": []},
             "route_hints": [], "input_params": {"get": [], "post": [], "request": [], "json_body": []},
             "envelope_keys": [], "method_hints": [], "custom_helpers_called": [], "dynamic_notes": []}]


class TestAssemblePrompt:
    def test_contains_system_role_text(self):
        prompt = assemble_prompt(_asm_global_stats(), _asm_signals(), _asm_files())
        assert "senior API analyst" in prompt

    def test_contains_schema_block(self):
        prompt = assemble_prompt(_asm_global_stats(), _asm_signals(), _asm_files())
        assert "strong_signals" in prompt
        assert "pattern.json" in prompt

    def test_contains_evidence_block_with_framework(self):
        prompt = assemble_prompt(_asm_global_stats(), _asm_signals(), _asm_files())
        assert "laravel" in prompt
        assert "Signal Frequency" in prompt

    def test_contains_rules_block(self):
        prompt = assemble_prompt(_asm_global_stats(), _asm_signals(), _asm_files())
        assert "EVIDENCE-ONLY" in prompt or "R1" in prompt

    def test_contains_output_format_block(self):
        prompt = assemble_prompt(_asm_global_stats(), _asm_signals(), _asm_files())
        assert "Begin your response with {" in prompt or "json.loads" in prompt

    def test_human_notes_included_when_provided(self):
        prompt = assemble_prompt(
            _asm_global_stats(), _asm_signals(), _asm_files(),
            human_notes="EXCLUDE the signal foo_bar.",
        )
        assert "Human Reviewer Notes" in prompt
        assert "EXCLUDE" in prompt

    def test_human_notes_omitted_when_empty(self):
        prompt = assemble_prompt(_asm_global_stats(), _asm_signals(), _asm_files(), human_notes="")
        assert "Human Reviewer Notes" not in prompt

    def test_custom_collection_name_in_prompt(self):
        prompt = assemble_prompt(
            _asm_global_stats(), _asm_signals(), _asm_files(),
            collection_name="MyAwesomeAPI",
        )
        assert "MyAwesomeAPI" in prompt

    def test_human_notes_truncated_at_3000_chars(self):
        long_note = "Z" * 5000
        prompt = assemble_prompt(
            _asm_global_stats(), _asm_signals(), _asm_files(),
            human_notes=long_note,
        )
        assert prompt.count("Z") <= 3000

    def test_returns_string(self):
        result = assemble_prompt(_asm_global_stats(), _asm_signals(), _asm_files())
        assert isinstance(result, str)
        assert len(result) > 100


# =============================================================================
# tool_c — classifier
# =============================================================================

from tool_c.classifier import (
    compute_toolc_score,
    classify_files,
    find_signal_in_pattern,
    ClassifiedFile,
)


def _c_pattern(endpoint=30, uncertain=8, strong_weight=25, weak_weight=8, neg_weight=-15):
    """Minimal pattern.json dict for classifier tests."""
    return {
        "scoring": {
            "strong_signals": [
                {"name": "strong_sig", "pattern": r"strong", "weight": strong_weight, "kind": "strong"}
            ],
            "weak_signals": [
                {"name": "weak_sig", "pattern": r"weak", "weight": weak_weight, "kind": "weak"}
            ],
            "negative_signals": [
                {"name": "neg_sig", "pattern": r"neg", "weight": neg_weight, "kind": "negative"}
            ],
            "thresholds": {"endpoint": endpoint, "uncertain": uncertain},
        },
        "endpoint_envelopes": {"templates": []},
        "method_inference": {
            "priority_order": ["route_hints", "default"],
            "rules": [],
            "default_method": "GET",
        },
        "postman_defaults": {
            "collection_name": "Test", "base_url_variable": "baseUrl",
            "auth_token_variable": "authToken", "default_headers": [],
            "auth_header": {"key": "Authorization", "value_template": "Bearer {{authToken}}"},
        },
    }


def _c_file(path="api.php", strong=0, weak=0, neg=0, custom_helpers=None, score=None):
    """Build a minimal file record dict for classifier tests."""
    signals = {
        "strong": [{"name": "strong_sig", "occurrences": strong, "line_nos": []}] if strong else [],
        "weak":   [{"name": "weak_sig",   "occurrences": weak,   "line_nos": []}] if weak   else [],
        "negative": [{"name": "neg_sig",  "occurrences": neg,    "line_nos": []}] if neg    else [],
    }
    helpers = [{"name": h} for h in (custom_helpers or [])]
    return {
        "record_type": "file", "schema_version": "2.0",
        "path": path, "framework": "plain",
        "score": score if score is not None else 0,
        "score_breakdown": [],
        "signals": signals,
        "custom_helpers_called": helpers,
        "route_hints": [{"method": "unknown", "uri": f"/{path}", "source_file": path,
                         "source_line": 0, "confidence": "low", "controller_method": None}],
        "input_params": {"get": [], "post": [], "request": [], "json_body": []},
        "method_hints": [], "envelope_keys": [], "output_points": [],
        "redaction_count": 0, "skipped": False, "skip_reason": None,
        "encoding_note": None, "dynamic_notes": [], "notes": [],
    }


class TestFindSignalInPattern:
    def test_finds_existing_signal(self):
        sigs = [{"name": "foo", "weight": 10}, {"name": "bar", "weight": 5}]
        assert find_signal_in_pattern("foo", sigs)["weight"] == 10

    def test_returns_none_for_missing(self):
        sigs = [{"name": "foo", "weight": 10}]
        assert find_signal_in_pattern("baz", sigs) is None

    def test_exact_match_only(self):
        sigs = [{"name": "foo_bar", "weight": 10}]
        assert find_signal_in_pattern("foo", sigs) is None


class TestComputeToolcScore:
    def test_strong_signal_occurrences_capped_at_3(self):
        rec = _c_file(strong=5)
        score, _ = compute_toolc_score(rec, _c_pattern(strong_weight=10))
        # capped at min(5,3) * 10 = 30
        assert score == 30

    def test_strong_signal_occurrences_2(self):
        rec = _c_file(strong=2)
        score, _ = compute_toolc_score(rec, _c_pattern(strong_weight=20))
        assert score == 40

    def test_weak_signal_not_multiplied(self):
        rec = _c_file(weak=5)
        score, _ = compute_toolc_score(rec, _c_pattern(weak_weight=8))
        # weight added once regardless of occurrences
        assert score == 8

    def test_negative_signal_reduces_score(self):
        rec = _c_file(strong=2, neg=1)
        score, _ = compute_toolc_score(rec, _c_pattern(strong_weight=25, neg_weight=-15))
        assert score == 25 * 2 - 15

    def test_score_clamped_to_zero(self):
        rec = _c_file(neg=1)
        score, _ = compute_toolc_score(rec, _c_pattern(neg_weight=-50))
        assert score == 0

    def test_score_clamped_to_100(self):
        rec = _c_file(strong=3)
        score, _ = compute_toolc_score(rec, _c_pattern(strong_weight=50))
        # 50 * 3 = 150, clamped to 100
        assert score == 100

    def test_matched_signals_reported(self):
        rec = _c_file(strong=1, weak=1, neg=1)
        _, matched = compute_toolc_score(rec, _c_pattern())
        assert "strong_sig" in matched["strong"]
        assert "weak_sig"   in matched["weak"]
        assert "neg_sig"    in matched["negative"]

    def test_custom_helper_counted_as_strong(self):
        # strong_sig also registered in strong_patterns
        rec = _c_file(custom_helpers=["strong_sig", "strong_sig"])
        score, matched = compute_toolc_score(rec, _c_pattern(strong_weight=10))
        # call_count=2, min(2,3)*10 = 20
        assert score == 20
        assert "strong_sig" in matched["strong"]

    def test_double_count_guard(self):
        # strong_sig appears in both signals.strong (occ=1) and custom_helpers_called
        rec = _c_file(strong=1, custom_helpers=["strong_sig"])
        score, _ = compute_toolc_score(rec, _c_pattern(strong_weight=10))
        # Should count only once via signals.strong: min(1,3)*10 = 10
        assert score == 10

    def test_unknown_signal_ignored(self):
        rec = _c_file()
        rec["signals"]["strong"] = [{"name": "unknown_xyz", "occurrences": 3, "line_nos": []}]
        score, _ = compute_toolc_score(rec, _c_pattern())
        assert score == 0


class TestClassifyFiles:
    def test_l1_tier(self):
        rec = _c_file(strong=2, score=50)
        classified = classify_files([rec], _c_pattern(strong_weight=25, endpoint=30, uncertain=8))
        assert classified[0].tier == "L1"
        assert classified[0].confidence_label == "confirmed_endpoint"

    def test_l2_tier(self):
        rec = _c_file(weak=1, score=8)
        classified = classify_files([rec], _c_pattern(weak_weight=8, endpoint=30, uncertain=8))
        assert classified[0].tier == "L2"
        assert classified[0].confidence_label == "uncertain"

    def test_l3_tier(self):
        rec = _c_file(neg=1, score=0)
        classified = classify_files([rec], _c_pattern(neg_weight=-15, endpoint=30, uncertain=8))
        assert classified[0].tier == "L3"
        assert classified[0].confidence_label == "not_endpoint"

    def test_sorted_by_path(self):
        recs = [_c_file("z.php"), _c_file("a.php"), _c_file("m.php")]
        classified = classify_files(recs, _c_pattern())
        paths = [c.file_record["path"] for c in classified]
        assert paths == sorted(paths)

    def test_divergence_warning_triggered(self):
        rec = _c_file(strong=2, score=5)   # toolc=50, toola=5 → diff=45 > 30
        classified = classify_files([rec], _c_pattern(strong_weight=25, endpoint=30, uncertain=8))
        assert classified[0].score_divergence_warning is not None

    def test_no_divergence_warning_within_range(self):
        rec = _c_file(strong=2, score=50)
        classified = classify_files([rec], _c_pattern(strong_weight=25, endpoint=30, uncertain=8))
        assert classified[0].score_divergence_warning is None

    def test_exclude_paths_skips_matching(self):
        recs = [_c_file("vendor/foo.php", strong=3), _c_file("app/api.php", strong=3)]
        pattern = _c_pattern()
        pattern["exclude_paths"] = ["vendor/"]
        classified = classify_files(recs, pattern)
        paths = [c.file_record["path"] for c in classified]
        assert "vendor/foo.php" not in paths
        assert "app/api.php" in paths

    def test_include_extensions_filters_non_php(self):
        recs = [_c_file("script.js", strong=3), _c_file("api.php", strong=3)]
        pattern = _c_pattern()
        pattern["include_extensions"] = [".php"]
        classified = classify_files(recs, pattern)
        paths = [c.file_record["path"] for c in classified]
        assert "script.js" not in paths
        assert "api.php" in paths


# =============================================================================
# tool_c — method_inferrer
# =============================================================================

from tool_c.method_inferrer import infer_methods, MethodResult


def _route_hint(method="POST", uri="/api/x", confidence="high",
                src_file="routes/api.php", src_line=1, controller=None):
    return {"method": method, "uri": uri, "source_file": src_file,
            "source_line": src_line, "confidence": confidence,
            "controller_method": controller}


def _mi_file(path="api.php", route_hints=None, method_hints=None, params=None, strong_signals=None):
    """Minimal file record for method_inferrer tests."""
    return {
        "path": path,
        "route_hints": route_hints or [],
        "method_hints": method_hints or [],
        "input_params": params or {"get": [], "post": [], "request": [], "json_body": []},
        "signals": {
            "strong": [{"name": s, "occurrences": 1, "line_nos": []} for s in (strong_signals or [])],
            "weak": [], "negative": [],
        },
    }


def _mi_pattern(priority=None, rules=None, default="GET"):
    return {
        "method_inference": {
            "priority_order": priority or [
                "route_hints", "request_method_check",
                "input_param_type", "signal_based", "default",
            ],
            "rules": rules or [],
            "default_method": default,
        }
    }


class TestMethodInferrer:
    def test_source1_high_confidence_route_hint(self):
        rec = _mi_file(route_hints=[_route_hint("POST", "/api/users", "high")])
        results = infer_methods(rec, _mi_pattern())
        assert len(results) == 1
        assert results[0].method == "POST"
        assert results[0].inference_source == "route_hints"

    def test_source1_low_confidence_skipped(self):
        rec = _mi_file(route_hints=[_route_hint("POST", "/api/users", "low")])
        results = infer_methods(rec, _mi_pattern())
        # Falls through to default
        assert results[0].inference_source != "route_hints"

    def test_source1_multiple_high_hints_returns_multiple(self):
        hints = [
            _route_hint("GET",  "/api/x", "high"),
            _route_hint("POST", "/api/x", "high"),
        ]
        rec = _mi_file(route_hints=hints)
        results = infer_methods(rec, _mi_pattern())
        assert len(results) == 2
        methods = {r.method for r in results}
        assert methods == {"GET", "POST"}

    def test_source1_unknown_method_becomes_get(self):
        rec = _mi_file(route_hints=[_route_hint("UNKNOWN", "/api/x", "high")])
        results = infer_methods(rec, _mi_pattern())
        assert results[0].method == "GET"

    def test_source1_route_source_format(self):
        rec = _mi_file(route_hints=[_route_hint("GET", "/api/x", "high",
                                                 src_file="routes/api.php", src_line=14)])
        results = infer_methods(rec, _mi_pattern())
        assert results[0].route_source == "routes/api.php:14"

    def test_source2_request_method_check(self):
        hints = [{"method": "POST", "evidence": "if ($_SERVER['REQUEST_METHOD'] == 'POST') {",
                  "line_no": 3}]
        rec = _mi_file(method_hints=hints)
        results = infer_methods(rec, _mi_pattern())
        assert results[0].method == "POST"
        assert results[0].inference_source == "request_method_check"

    def test_source3_json_body_only_gives_post(self):
        params = {"get": [], "post": [], "request": [], "json_body": [{"key": "name", "line_no": 1}]}
        rec = _mi_file(params=params)
        results = infer_methods(rec, _mi_pattern())
        assert results[0].method == "POST"
        assert results[0].inference_source == "input_param_type"

    def test_source3_get_only_gives_get(self):
        params = {"get": [{"key": "id", "line_no": 1}], "post": [], "request": [], "json_body": []}
        rec = _mi_file(params=params)
        results = infer_methods(rec, _mi_pattern())
        assert results[0].method == "GET"

    def test_source3_both_json_and_get_gives_two_items(self):
        params = {"get": [{"key": "id", "line_no": 1}], "post": [],
                  "request": [], "json_body": [{"key": "body", "line_no": 2}]}
        rec = _mi_file(params=params)
        results = infer_methods(rec, _mi_pattern())
        assert len(results) == 2
        methods = {r.method for r in results}
        assert methods == {"GET", "POST"}

    def test_source4_signal_based(self):
        rules = [{"source": "signal_based", "condition": "AJAX",
                  "matched_signal_name": "wp_ajax", "method": "POST"}]
        rec = _mi_file(strong_signals=["wp_ajax"])
        results = infer_methods(rec, _mi_pattern(rules=rules))
        assert results[0].method == "POST"
        assert results[0].inference_source == "signal_based"

    def test_source5_default_method(self):
        rec = _mi_file()  # no route hints, no hints, no params, no signals
        results = infer_methods(rec, _mi_pattern(default="POST"))
        assert results[0].method == "POST"
        assert results[0].inference_source == "default"

    def test_controller_method_preserved(self):
        hint = _route_hint("GET", "/api/x", "high", controller="UserController@index")
        rec = _mi_file(route_hints=[hint])
        results = infer_methods(rec, _mi_pattern())
        assert results[0].controller_method == "UserController@index"


# =============================================================================
# tool_c — envelope_matcher
# =============================================================================

from tool_c.envelope_matcher import match_envelope


def _em_pattern(templates):
    return {"endpoint_envelopes": {"templates": templates}}


def _em_file(keys):
    return {"envelope_keys": [{"key": k, "line_no": i} for i, k in enumerate(keys)]}


class TestEnvelopeMatcher:
    def test_matches_keys_all_of(self):
        tmpl = {"name": "t1", "keys_all_of": ["success"], "keys_any_of": [], "example": {}}
        result = match_envelope(_em_file(["success", "data"]), _em_pattern([tmpl]))
        assert result is not None
        assert result["name"] == "t1"

    def test_fails_when_keys_all_of_missing(self):
        tmpl = {"name": "t1", "keys_all_of": ["success", "status"], "keys_any_of": []}
        result = match_envelope(_em_file(["success"]), _em_pattern([tmpl]))
        assert result is None

    def test_matches_keys_any_of(self):
        tmpl = {"name": "t1", "keys_all_of": ["success"], "keys_any_of": ["data", "items"]}
        result = match_envelope(_em_file(["success", "items"]), _em_pattern([tmpl]))
        assert result is not None

    def test_fails_when_keys_any_of_none_present(self):
        tmpl = {"name": "t1", "keys_all_of": ["success"], "keys_any_of": ["data", "items"]}
        result = match_envelope(_em_file(["success", "meta"]), _em_pattern([tmpl]))
        assert result is None

    def test_empty_keys_any_of_always_satisfied(self):
        tmpl = {"name": "t1", "keys_all_of": ["success"], "keys_any_of": []}
        result = match_envelope(_em_file(["success"]), _em_pattern([tmpl]))
        assert result is not None

    def test_no_templates_returns_none(self):
        result = match_envelope(_em_file(["success"]), _em_pattern([]))
        assert result is None

    def test_empty_envelope_keys_returns_none(self):
        tmpl = {"name": "t1", "keys_all_of": ["success"], "keys_any_of": []}
        result = match_envelope(_em_file([]), _em_pattern([tmpl]))
        assert result is None

    def test_returns_first_matching_template(self):
        templates = [
            {"name": "t1", "keys_all_of": ["status"], "keys_any_of": []},
            {"name": "t2", "keys_all_of": ["success"], "keys_any_of": []},
        ]
        result = match_envelope(_em_file(["success"]), _em_pattern(templates))
        assert result["name"] == "t2"


# =============================================================================
# tool_c — redactor
# =============================================================================

from tool_c.redactor import redact_body, param_placeholder


class TestRedactBody:
    def test_api_key_redacted(self):
        body = '{\n  "api_key": "abc123"\n}'
        result, was_redacted = redact_body(body)
        assert was_redacted
        assert "REDACTED" in result
        assert "abc123" not in result

    def test_token_redacted(self):
        body = '{"token": "secret_value"}'
        result, was_redacted = redact_body(body)
        assert was_redacted
        assert "REDACTED" in result

    def test_password_redacted(self):
        body = '{"password": "hunter2"}'
        result, was_redacted = redact_body(body)
        assert was_redacted

    def test_secret_redacted(self):
        body = '{"secret": "mysecret"}'
        result, was_redacted = redact_body(body)
        assert was_redacted

    def test_non_secret_not_redacted(self):
        body = '{"username": "alice", "user_id": 1}'
        result, was_redacted = redact_body(body)
        assert not was_redacted
        assert "alice" in result

    def test_empty_value_still_redacted(self):
        body = '{"api_key": ""}'
        result, was_redacted = redact_body(body)
        assert was_redacted
        assert "REDACTED" in result

    def test_non_string_value_not_affected(self):
        # Numbers/booleans not affected (regex only matches "...")
        body = '{"user_id": 0, "active": true}'
        result, was_redacted = redact_body(body)
        assert not was_redacted


class TestParamPlaceholder:
    def test_id_suffix_returns_zero(self):
        assert param_placeholder("user_id") == 0
        assert param_placeholder("id") == 0

    def test_count_suffix_returns_zero(self):
        assert param_placeholder("item_count") == 0

    def test_page_suffix_returns_zero(self):
        assert param_placeholder("page") == 0

    def test_limit_suffix_returns_zero(self):
        assert param_placeholder("limit") == 0

    def test_date_suffix_returns_empty_string(self):
        assert param_placeholder("created_at") == ""
        assert param_placeholder("birth_date") == ""

    def test_is_prefix_returns_true(self):
        assert param_placeholder("is_active") is True

    def test_has_prefix_returns_true(self):
        assert param_placeholder("has_access") is True

    def test_enabled_returns_true(self):
        assert param_placeholder("enabled") is True

    def test_active_returns_true(self):
        assert param_placeholder("active") is True

    def test_unknown_key_returns_empty_string(self):
        assert param_placeholder("username") == ""
        assert param_placeholder("email") == ""

    def test_secret_key_redacted_when_flag_set(self):
        assert param_placeholder("api_key", redact_if_secret=True) == "REDACTED"
        assert param_placeholder("token", redact_if_secret=True) == "REDACTED"

    def test_normal_key_not_redacted_when_flag_set(self):
        assert param_placeholder("username", redact_if_secret=True) == ""


# =============================================================================
# tool_c — postman_builder
# =============================================================================

from tool_c.postman_builder import build_collection
from tool_c.classifier import ClassifiedFile


def _cf(path="api.php", tier="L1", toolc_score=50, toola_score=50,
        route_hints=None, json_body=None, get_params=None, post_params=None,
        envelope_keys=None, strong_signals=None):
    """Build a ClassifiedFile for postman_builder tests."""
    rh = route_hints or [{"method": "GET", "uri": "/api/test", "source_file": "routes/api.php",
                          "source_line": 1, "confidence": "high", "controller_method": None}]
    file_record = {
        "record_type": "file", "schema_version": "2.0",
        "path": path, "framework": "laravel", "score": toola_score,
        "score_breakdown": [],
        "signals": {
            "strong": [{"name": s, "occurrences": 1, "line_nos": []} for s in (strong_signals or [])],
            "weak": [], "negative": [],
        },
        "dynamic_notes": [],
        "route_hints": rh,
        "input_params": {
            "get":       get_params or [],
            "post":      post_params or [],
            "request":   [],
            "json_body": json_body or [],
        },
        "method_hints": [],
        "envelope_keys": [{"key": k, "line_no": i} for i, k in enumerate(envelope_keys or [])],
        "output_points": [],
        "custom_helpers_called": [],
        "redaction_count": 0, "skipped": False, "skip_reason": None,
        "encoding_note": None, "notes": [],
    }
    return ClassifiedFile(
        file_record=file_record,
        toolc_score=toolc_score,
        toola_score=toola_score,
        tier=tier,
        confidence_label={"L1": "confirmed_endpoint", "L2": "uncertain", "L3": "not_endpoint"}[tier],
        matched_signals={"strong": list(strong_signals or []), "weak": [], "negative": []},
        score_divergence_warning=None,
    )


def _full_pattern(collection_name="API Test", default_method="GET",
                  templates=None, pre_script=False, test_script=False):
    return {
        "version": "1.0",
        "framework": "laravel",
        "scoring": {
            "strong_signals": [], "weak_signals": [], "negative_signals": [],
            "thresholds": {"endpoint": 30, "uncertain": 8},
        },
        "endpoint_envelopes": {"templates": templates or []},
        "method_inference": {
            "priority_order": ["route_hints", "default"],
            "rules": [], "default_method": default_method,
        },
        "postman_defaults": {
            "collection_name": collection_name,
            "base_url_variable": "baseUrl",
            "auth_token_variable": "authToken",
            "default_headers": [{"key": "Accept", "value": "application/json", "disabled": False}],
            "auth_header": {"key": "Authorization", "value_template": "Bearer {{authToken}}"},
            "generate_folder_per_directory": False,
            "include_pre_request_script": pre_script,
            "include_test_script": test_script,
        },
    }


class TestBuildCollection:
    def test_info_structure(self):
        collection = build_collection([], _full_pattern("My API"))
        assert collection["info"]["name"] == "My API"
        assert "schema.getpostman.com" in collection["info"]["schema"]
        assert collection["info"]["_tool_c_generated"] is True

    def test_variable_block_present(self):
        collection = build_collection([], _full_pattern())
        keys = [v["key"] for v in collection["variable"]]
        assert "baseUrl" in keys
        assert "authToken" in keys

    def test_l3_excluded(self):
        files = [_cf(tier="L3")]
        collection = build_collection(files, _full_pattern())
        assert len(collection["item"]) == 0

    def test_l2_excluded_by_default(self):
        files = [_cf(tier="L2")]
        collection = build_collection(files, _full_pattern())
        assert len(collection["item"]) == 0

    def test_l2_included_when_flag_set(self):
        files = [_cf(tier="L2")]
        collection = build_collection(files, _full_pattern(), include_uncertain=True)
        assert len(collection["item"]) == 1

    def test_l1_included_by_default(self):
        files = [_cf(tier="L1")]
        collection = build_collection(files, _full_pattern())
        assert len(collection["item"]) == 1

    def test_item_name_with_controller(self):
        rh = [{"method": "POST", "uri": "/api/users", "source_file": "routes/api.php",
               "source_line": 1, "confidence": "high", "controller_method": "UserController@store"}]
        files = [_cf(route_hints=rh)]
        collection = build_collection(files, _full_pattern())
        assert collection["item"][0]["name"] == "POST /api/users (UserController@store)"

    def test_item_name_without_controller(self):
        rh = [{"method": "GET", "uri": "/api/posts", "source_file": "routes/api.php",
               "source_line": 1, "confidence": "high", "controller_method": None}]
        files = [_cf(route_hints=rh)]
        collection = build_collection(files, _full_pattern())
        assert collection["item"][0]["name"] == "GET /api/posts"

    def test_url_uses_base_url_variable(self):
        files = [_cf()]
        collection = build_collection(files, _full_pattern())
        url_raw = collection["item"][0]["request"]["url"]["raw"]
        assert url_raw.startswith("{{baseUrl}}")

    def test_get_has_no_body(self):
        rh = [{"method": "GET", "uri": "/api/x", "source_file": "routes/api.php",
               "source_line": 1, "confidence": "high", "controller_method": None}]
        files = [_cf(route_hints=rh)]
        collection = build_collection(files, _full_pattern())
        assert "body" not in collection["item"][0]["request"]

    def test_post_with_json_body_params(self):
        rh = [{"method": "POST", "uri": "/api/x", "source_file": "routes/api.php",
               "source_line": 1, "confidence": "high", "controller_method": None}]
        files = [_cf(route_hints=rh, json_body=[{"key": "name", "line_no": 1},
                                                  {"key": "email", "line_no": 2}])]
        collection = build_collection(files, _full_pattern())
        body = collection["item"][0]["request"]["body"]
        assert body["mode"] == "raw"
        assert "name" in body["raw"]

    def test_post_with_post_params_gives_urlencoded(self):
        rh = [{"method": "POST", "uri": "/api/x", "source_file": "routes/api.php",
               "source_line": 1, "confidence": "high", "controller_method": None}]
        files = [_cf(route_hints=rh, post_params=[{"key": "field1", "line_no": 1}])]
        collection = build_collection(files, _full_pattern())
        body = collection["item"][0]["request"]["body"]
        assert body["mode"] == "urlencoded"

    def test_get_query_params_populated(self):
        rh = [{"method": "GET", "uri": "/api/x", "source_file": "routes/api.php",
               "source_line": 1, "confidence": "high", "controller_method": None}]
        files = [_cf(route_hints=rh, get_params=[{"key": "page", "line_no": 1}])]
        collection = build_collection(files, _full_pattern())
        url = collection["item"][0]["request"]["url"]
        assert len(url["query"]) == 1
        assert url["query"][0]["key"] == "page"

    def test_tool_c_meta_present(self):
        files = [_cf()]
        collection = build_collection(files, _full_pattern())
        meta = collection["item"][0]["_tool_c_meta"]
        assert "confidence_tier" in meta
        assert "toolc_score" in meta
        assert "method_inference_source" in meta

    def test_redaction_applied_for_secret_key(self):
        rh = [{"method": "POST", "uri": "/api/x", "source_file": "routes/api.php",
               "source_line": 1, "confidence": "high", "controller_method": None}]
        files = [_cf(route_hints=rh, json_body=[{"key": "api_key", "line_no": 1}])]
        collection = build_collection(files, _full_pattern())
        meta = collection["item"][0]["_tool_c_meta"]
        assert meta["redaction_applied"] is True
        body_raw = collection["item"][0]["request"]["body"]["raw"]
        assert "REDACTED" in body_raw

    def test_no_envelope_match_in_meta(self):
        files = [_cf(envelope_keys=["foo", "bar"])]  # no templates → no match
        collection = build_collection(files, _full_pattern())
        meta = collection["item"][0]["_tool_c_meta"]
        assert meta["no_envelope_match"] is True

    def test_envelope_match_in_meta(self):
        templates = [{"name": "success_data", "keys_all_of": ["success"],
                      "keys_any_of": ["data"], "example": {"success": True, "data": {}}}]
        files = [_cf(envelope_keys=["success", "data"])]
        collection = build_collection(files, _full_pattern(templates=templates))
        meta = collection["item"][0]["_tool_c_meta"]
        assert meta["no_envelope_match"] is False
        assert meta["matched_envelope_template"] == "success_data"

    def test_duplicate_names_disambiguated(self):
        # Two items with same name (same uri, same method via two files)
        rh = [{"method": "GET", "uri": "/api/x", "source_file": "routes/api.php",
               "source_line": 1, "confidence": "high", "controller_method": None}]
        files = [_cf("a.php", route_hints=rh), _cf("b.php", route_hints=rh)]
        collection = build_collection(files, _full_pattern())
        names = [i["name"] for i in collection["item"]]
        assert len(set(names)) == len(names), f"Duplicate names: {names}"

    def test_folder_structure_by_directory(self):
        rh = [{"method": "GET", "uri": "/api/x", "source_file": "routes/api.php",
               "source_line": 1, "confidence": "high", "controller_method": None}]
        files = [_cf("app/Http/Controllers/Api.php", route_hints=rh)]
        collection = build_collection(files, _full_pattern(), folder_structure="by_directory")
        item0 = collection["item"][0]
        assert "item" in item0   # it's a folder
        assert item0["name"] == "app/Http/Controllers"

    def test_pre_request_script_included(self):
        files = [_cf()]
        collection = build_collection(files, _full_pattern(pre_script=True))
        events = collection["item"][0].get("event", [])
        listens = [e["listen"] for e in events]
        assert "prerequest" in listens

    def test_test_script_included(self):
        files = [_cf()]
        collection = build_collection(files, _full_pattern(test_script=True))
        events = collection["item"][0].get("event", [])
        listens = [e["listen"] for e in events]
        assert "test" in listens

    def test_auth_header_in_request(self):
        files = [_cf()]
        collection = build_collection(files, _full_pattern())
        headers = collection["item"][0]["request"]["header"]
        auth = next((h for h in headers if h["key"] == "Authorization"), None)
        assert auth is not None
        assert "authToken" in auth["value"]


# =============================================================================
# tool_c — postman_validator
# =============================================================================

from tool_c.postman_validator import validate_postman_collection


class TestPostmanValidator:
    def _valid_collection(self):
        return {
            "info": {
                "name": "Test",
                "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            },
            "item": [],
            "variable": [],
        }

    def test_valid_collection_passes(self):
        assert validate_postman_collection(self._valid_collection()) is True

    def test_missing_info_fails(self):
        c = {"item": []}
        assert validate_postman_collection(c) is False

    def test_missing_item_fails(self):
        c = {"info": {"name": "x", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"}}
        assert validate_postman_collection(c) is False

    def test_schema_url_must_reference_getpostman(self):
        c = self._valid_collection()
        c["info"]["schema"] = "https://example.com/schema.json"
        assert validate_postman_collection(c) is False

    def test_item_with_valid_request_passes(self):
        c = self._valid_collection()
        c["item"] = [{
            "name": "GET /api/test",
            "request": {"method": "GET", "url": {"raw": "{{baseUrl}}/api/test"}},
            "response": [],
        }]
        assert validate_postman_collection(c) is True

    def test_underscore_keys_in_item_allowed(self):
        # _tool_c_meta should not cause validation failure
        c = self._valid_collection()
        c["item"] = [{
            "name": "test",
            "request": {"method": "GET"},
            "_tool_c_meta": {"source_file": "x.php"},
        }]
        assert validate_postman_collection(c) is True


# =============================================================================
# tool_c — jsonl_reader (via subprocess to test sys.exit codes)
# =============================================================================

import json as _json
import subprocess as _sp
import tempfile as _tf
from pathlib import Path as _Path


def _write_jsonl(lines):
    """Write lines to a temp JSONL file and return the path."""
    f = _tf.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False)
    for line in lines:
        f.write(_json.dumps(line) + "\n")
    f.close()
    return f.name


_VALID_GS = {
    "record_type": "global_stats", "schema_version": "2.0",
    "generated_at": "2025-01-01T00:00:00+00:00",
    "framework": {"detected": "plain", "confidence": "low", "evidence": []},
    "scan_summary": {"total_files_scanned": 1, "total_files_skipped": 0, "skip_reasons": {},
                     "candidate_files_above_score_0": 1, "candidate_files_above_score_30": 0,
                     "candidate_files_above_score_60": 0},
    "signal_frequency_table": [], "custom_helper_registry": [],
    "envelope_key_frequency": [], "method_distribution": {}, "co_occurrence_patterns": [],
    "pattern_json_generation_hints": {
        "recommended_endpoint_threshold": 30, "recommended_uncertain_threshold": 8,
        "minimum_threshold_gap": 10,
    },
    "top_dirs": [],
}
_VALID_SK = {"record_type": "skipped_files_summary", "skipped_files": []}


class TestJSONLReader:
    def test_valid_jsonl_returns_correct_types(self):
        from tool_c.jsonl_reader import read_jsonl
        path = _write_jsonl([_VALID_GS, _VALID_SK])
        try:
            gs, files, skipped = read_jsonl(path)
            assert gs["schema_version"] == "2.0"
            assert isinstance(files, list)
            assert "skipped_files" in skipped
        finally:
            _Path(path).unlink(missing_ok=True)

    def test_wrong_schema_version_causes_exit_2(self):
        bad_gs = dict(_VALID_GS, schema_version="1.0")
        path = _write_jsonl([bad_gs, _VALID_SK])
        try:
            result = _sp.run(
                ["python3", "-c",
                 f"from tool_c.jsonl_reader import read_jsonl; read_jsonl('{path}')"],
                capture_output=True, cwd=str(_Path(__file__).parent.parent),
            )
            assert result.returncode == 2
        finally:
            _Path(path).unlink(missing_ok=True)

    def test_file_records_parsed(self):
        from tool_c.jsonl_reader import read_jsonl
        file_rec = {
            "record_type": "file", "schema_version": "2.0",
            "path": "test.php", "framework": "plain", "score": 10,
            "score_breakdown": [], "signals": {"strong": [], "weak": [], "negative": []},
            "dynamic_notes": [], "route_hints": [], "input_params": {"get": [], "post": [], "request": [], "json_body": []},
            "method_hints": [], "envelope_keys": [], "output_points": [],
            "custom_helpers_called": [], "redaction_count": 0, "skipped": False,
            "skip_reason": None, "encoding_note": None, "notes": [],
        }
        path = _write_jsonl([_VALID_GS, file_rec, _VALID_SK])
        try:
            gs, files, skipped = read_jsonl(path)
            assert len(files) == 1
            assert files[0]["path"] == "test.php"
        finally:
            _Path(path).unlink(missing_ok=True)

    def test_skipped_files_summary_parsed(self):
        from tool_c.jsonl_reader import read_jsonl
        sk = {"record_type": "skipped_files_summary",
              "skipped_files": [{"file": "big.php", "reason": "too_large", "size_mb": 8.2}]}
        path = _write_jsonl([_VALID_GS, sk])
        try:
            _, _, skipped = read_jsonl(path)
            assert len(skipped["skipped_files"]) == 1
            assert skipped["skipped_files"][0]["file"] == "big.php"
        finally:
            _Path(path).unlink(missing_ok=True)

    def test_malformed_json_line_skipped(self, capsys):
        from tool_c.jsonl_reader import read_jsonl
        f = _tf.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False)
        f.write(_json.dumps(_VALID_GS) + "\n")
        f.write("{not valid json\n")
        f.write(_json.dumps(_VALID_SK) + "\n")
        f.close()
        try:
            _, files, _ = read_jsonl(f.name)
            assert files == []   # malformed line skipped, no crash
        finally:
            _Path(f.name).unlink(missing_ok=True)


# =============================================================================
# tool_c — catalog_writer
# =============================================================================

from tool_c.catalog_writer import build_catalog


class TestBuildCatalog:
    def _make_classified(self, tier, path="api.php", toolc=50, toola=50):
        fr = {
            "record_type": "file", "schema_version": "2.0",
            "path": path, "framework": "laravel", "score": toola,
            "score_breakdown": [],
            "signals": {"strong": [], "weak": [], "negative": []},
            "dynamic_notes": [], "route_hints": [],
            "input_params": {"get": [], "post": [], "request": [], "json_body": []},
            "method_hints": [], "envelope_keys": [], "output_points": [],
            "custom_helpers_called": [], "redaction_count": 0, "skipped": False,
            "skip_reason": None, "encoding_note": None, "notes": [],
        }
        label = {"L1": "confirmed_endpoint", "L2": "uncertain", "L3": "not_endpoint"}[tier]
        return ClassifiedFile(
            file_record=fr, toolc_score=toolc, toola_score=toola,
            tier=tier, confidence_label=label,
            matched_signals={"strong": [], "weak": [], "negative": []},
            score_divergence_warning=None,
        )

    def _global_stats(self):
        return {
            "signal_frequency_table": [],
            "custom_helper_registry": [],
            "pattern_json_generation_hints": {
                "recommended_endpoint_threshold": 30,
                "minimum_threshold_gap": 10,
            },
            "framework": {"detected": "laravel"},
        }

    def _pattern(self):
        return {
            "version": "1.0",
            "framework": "laravel",
            "scoring": {
                "strong_signals": [], "weak_signals": [], "negative_signals": [],
                "thresholds": {"endpoint": 30, "uncertain": 8},
            },
            "endpoint_envelopes": {"templates": []},
            "method_inference": {
                "priority_order": ["default"], "rules": [], "default_method": "GET",
            },
            "postman_defaults": {
                "collection_name": "T", "base_url_variable": "baseUrl",
                "auth_token_variable": "authToken", "default_headers": [],
                "auth_header": {"key": "Authorization", "value_template": "Bearer {{authToken}}"},
            },
        }

    def test_summary_counts_correct(self):
        classified = [
            self._make_classified("L1", "a.php"),
            self._make_classified("L2", "b.php"),
            self._make_classified("L3", "c.php"),
        ]
        catalog = build_catalog(classified, self._pattern(), self._global_stats(),
                                {"skipped_files": []})
        s = catalog["summary"]
        assert s["l1_endpoint_count"] == 1
        assert s["l2_uncertain_count"] == 1
        assert s["l3_ignored_count"] == 1
        assert s["total_file_records_in_jsonl"] == 3

    def test_endpoints_list_contains_l1_only(self):
        classified = [
            self._make_classified("L1", "a.php"),
            self._make_classified("L2", "b.php"),
        ]
        catalog = build_catalog(classified, self._pattern(), self._global_stats(),
                                {"skipped_files": []})
        assert len(catalog["endpoints"]) == 1
        assert catalog["endpoints"][0]["file"] == "a.php"
        assert len(catalog["uncertain_endpoints"]) == 1

    def test_skipped_files_carried_forward(self):
        skipped = {"skipped_files": [{"file": "big.php", "reason": "too_large", "size_mb": 8.2}]}
        catalog = build_catalog([], self._pattern(), self._global_stats(), skipped)
        assert len(catalog["skipped_from_jsonl"]) == 1

    def test_threshold_divergence_no_warning_within_15(self):
        catalog = build_catalog([], self._pattern(), self._global_stats(), {"skipped_files": []})
        check = catalog["threshold_divergence_check"]
        # recommended=30, actual=30, divergence=0 → no warning
        assert check["divergence"] == 0
        assert check["warning"] is None

    def test_threshold_divergence_warning_above_15(self):
        gs = self._global_stats()
        gs["pattern_json_generation_hints"]["recommended_endpoint_threshold"] = 50
        # actual=30, recommended=50 → divergence=20 > 15 → warning
        catalog = build_catalog([], self._pattern(), gs, {"skipped_files": []})
        check = catalog["threshold_divergence_check"]
        assert check["divergence"] == 20
        assert check["warning"] is not None

    def test_generated_at_field_present(self):
        catalog = build_catalog([], self._pattern(), self._global_stats(), {"skipped_files": []})
        assert "generated_at" in catalog
        assert "T" in catalog["generated_at"]  # ISO timestamp contains T

    def test_endpoint_entry_has_required_fields(self):
        classified = [self._make_classified("L1", "api.php", toolc=50, toola=50)]
        catalog = build_catalog(classified, self._pattern(), self._global_stats(),
                                {"skipped_files": []})
        ep = catalog["endpoints"][0]
        for field in ("file", "confidence_tier", "toolc_score", "toola_score",
                      "matched_signals", "inferred_methods", "extracted_params",
                      "no_envelope_match", "postman_items_generated"):
            assert field in ep, f"Missing field: {field}"
