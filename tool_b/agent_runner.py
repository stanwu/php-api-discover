"""agent_runner.py — Dispatch prompt to selected agent adapter; handle timeout + retry."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from typing import Any

from .agents.base import AgentAdapter, AgentError
from .agents.mock import MockAdapter
from .response_parser import extract_json_from_text


def check_agent_available(agent_name: str) -> bool:
    """Return True if the agent CLI is available in PATH."""
    if agent_name == "mock":
        return True
    return shutil.which(agent_name) is not None


def _call_real_agent(
    adapter: AgentAdapter,
    prompt: str,
    model: str | None,
    timeout: int,
) -> str:
    """
    Call the agent CLI subprocess and return the raw text response.
    Raises AgentError or SystemExit(3) on timeout.
    """
    argv = adapter.build_command(prompt, model)
    start = time.monotonic()
    print(f"[ToolB] Subprocess: {argv[0]} … (press Ctrl-C to abort)", file=sys.stderr)

    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        print(
            f"Error: Agent '{adapter.name}' timed out after {elapsed:.0f}s "
            f"(limit: {timeout}s). Use --agent-timeout to increase the limit.",
            file=sys.stderr,
        )
        sys.exit(3)

    elapsed = time.monotonic() - start
    print(f"[ToolB] Agent responded in {elapsed:.1f}s", file=sys.stderr)
    return adapter.parse_response(proc.stdout, proc.stderr, proc.returncode)


def _call_mock_agent(adapter: MockAdapter) -> str:
    """Return mock response file contents."""
    return adapter.read_response_file()


def _build_repair_prompt(raw_response: str, parse_error: str) -> str:
    return (
        f"The following text was your previous response. It contains JSON that failed to parse.\n"
        f"Error: {parse_error}\n\n"
        f"Your response:\n---\n{raw_response[:2000]}\n---\n\n"
        f"Please output ONLY the corrected JSON object. No prose, no fences. Begin with {{ end with }}."
    )


def _build_correction_prompt(
    validation_errors: list[str],
    toolc_schema_block: str,
) -> str:
    numbered = "\n".join(f"{i+1}. {e}" for i, e in enumerate(validation_errors[:10]))
    return (
        f"Your previous response was valid JSON but failed ToolC schema validation.\n"
        f"Validation errors:\n{numbered}\n\n"
        f"The original schema constraints are repeated below.\n"
        f"{toolc_schema_block}\n\n"
        f"Please output a corrected JSON object addressing all validation errors."
    )


def run_agent(
    adapter: AgentAdapter,
    prompt: str,
    model: str | None,
    timeout: int,
    global_stats: dict[str, Any],
    raw_response_path: str | None,
    skip_validation: bool,
    toolc_schema_block: str,
) -> tuple[dict[str, Any], int]:
    """
    Dispatch prompt to the agent, parse JSON, validate, and return
    (parsed_pattern_dict, retry_count).

    Raises SystemExit on unrecoverable errors.
    """
    from toolchain.toolchain_validator import validate_pattern_json

    retry_count = 0

    # ── Initial call ──────────────────────────────────────────────────────────
    try:
        if isinstance(adapter, MockAdapter):
            raw_text = _call_mock_agent(adapter)
        else:
            raw_text = _call_real_agent(adapter, prompt, model, timeout)
    except AgentError as exc:
        print(f"Error: Agent call failed: {exc}", file=sys.stderr)
        sys.exit(4)

    # Save raw response if requested
    if raw_response_path:
        try:
            from pathlib import Path
            Path(raw_response_path).write_text(raw_text, encoding="utf-8")
            print(f"Raw response saved to: {raw_response_path}")
        except OSError as exc:
            print(f"Warning: could not save raw response: {exc}", file=sys.stderr)

    # ── Parse JSON (with one repair retry on failure) ─────────────────────────
    parsed, retry_count = _parse_with_retry(
        adapter, raw_text, prompt, model, timeout, retry_count
    )

    if parsed is None:
        print("Error: Agent returned unparseable JSON after repair retry.", file=sys.stderr)
        sys.exit(4)

    # ── Validate (with one correction retry on failure) ───────────────────────
    if not skip_validation:
        parsed, retry_count = _validate_with_retry(
            adapter, parsed, global_stats, toolc_schema_block,
            prompt, model, timeout, retry_count
        )

    return parsed, retry_count


def _parse_with_retry(
    adapter: AgentAdapter,
    raw_text: str,
    prompt: str,
    model: str | None,
    timeout: int,
    retry_count: int,
) -> tuple[dict | None, int]:
    """Attempt to parse JSON from raw_text; retry once with repair prompt."""
    parsed = extract_json_from_text(raw_text)
    if parsed is not None:
        return parsed, retry_count

    # First parse failed — send repair prompt
    print("Warning: JSON parse failed, sending repair prompt...", file=sys.stderr)
    parse_error = _get_parse_error(raw_text)
    repair_prompt = _build_repair_prompt(raw_text, parse_error)
    retry_count += 1

    try:
        if isinstance(adapter, MockAdapter):
            # Mock agent always returns the same file, so repair will also fail.
            # Return the same content to trigger the exit(4) path.
            repair_text = adapter.read_response_file()
        else:
            repair_text = _call_real_agent(adapter, repair_prompt, model, timeout)
    except AgentError as exc:
        print(f"Error: Repair call failed: {exc}", file=sys.stderr)
        return None, retry_count

    repaired = extract_json_from_text(repair_text)
    return repaired, retry_count


def _validate_with_retry(
    adapter: AgentAdapter,
    parsed: dict,
    global_stats: dict,
    toolc_schema_block: str,
    prompt: str,
    model: str | None,
    timeout: int,
    retry_count: int,
) -> tuple[dict, int]:
    """Validate parsed pattern; retry once with correction prompt on hard failures."""
    from toolchain.toolchain_validator import validate_pattern_json

    result = validate_pattern_json(parsed, global_stats)

    for w in result.warnings:
        print(f"Warning: {w}", file=sys.stderr)

    if result.valid:
        return parsed, retry_count

    # Hard validation errors — send correction prompt
    print(
        f"Warning: Validation failed ({len(result.errors)} errors), "
        f"sending correction prompt...",
        file=sys.stderr,
    )
    correction_prompt = _build_correction_prompt(result.errors, toolc_schema_block)
    retry_count += 1

    try:
        if isinstance(adapter, MockAdapter):
            correction_text = adapter.read_response_file()
        else:
            correction_text = _call_real_agent(adapter, correction_prompt, model, timeout)
    except AgentError as exc:
        print(f"Error: Correction call failed: {exc}", file=sys.stderr)
        _write_partial_output_and_exit(parsed, result.errors)

    corrected = extract_json_from_text(correction_text)
    if corrected is None:
        print("Error: Correction response was not parseable JSON.", file=sys.stderr)
        _write_partial_output_and_exit(parsed, result.errors)

    result2 = validate_pattern_json(corrected, global_stats)
    for w in result2.warnings:
        print(f"Warning: {w}", file=sys.stderr)

    if result2.valid:
        return corrected, retry_count

    # Still failing after correction — partial output
    _write_partial_output_and_exit(corrected, result2.errors)


def _write_partial_output_and_exit(parsed: dict, errors: list[str]) -> None:
    """Attach validation errors to output object and exit with code 6."""
    parsed["_validation_errors"] = errors
    print(
        "Error: Validation failed after all retries. Partial output has _validation_errors field.",
        file=sys.stderr,
    )
    print("Use --skip-validation to force output despite errors.")
    sys.exit(6)


def _get_parse_error(text: str) -> str:
    """Return a short JSON parse error message for the given text."""
    import json
    try:
        json.loads(text)
        return "No error detected on re-parse"
    except json.JSONDecodeError as exc:
        return str(exc)
