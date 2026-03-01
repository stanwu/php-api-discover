"""tool_b.__main__ — CLI entry point for ToolB AI Agent Pattern Generator.

Subcommands:
  generate      Generate pattern.json from features_raw.jsonl
  check-agents  Check which agent CLIs are available in PATH

Usage:
  python tool_b.py generate --jsonl features_raw.jsonl --out pattern.json
  python -m tool_b generate --jsonl features_raw.jsonl --out pattern.json
  python tool_b.py check-agents
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def _get_adapter(agent: str, mock_response_file: str | None):
    """Return the appropriate AgentAdapter instance."""
    from tool_b.agents.claude  import ClaudeAdapter
    from tool_b.agents.codex   import CodexAdapter
    from tool_b.agents.gemini  import GeminiAdapter
    from tool_b.agents.mock    import MockAdapter

    if agent == "claude":
        return ClaudeAdapter()
    if agent == "codex":
        return CodexAdapter()
    if agent == "gemini":
        return GeminiAdapter()
    if agent == "mock":
        return MockAdapter(response_file=mock_response_file)
    print(f"Error: Unknown agent '{agent}'. Choices: claude, codex, gemini, mock", file=sys.stderr)
    sys.exit(1)


def cmd_generate(args: argparse.Namespace) -> None:
    from tool_b.jsonl_reader       import read_jsonl
    from tool_b.context_selector   import (
        select_signals, select_file_records, estimate_tokens,
        get_agent_token_limit, truncate_context,
    )
    from tool_b.prompt_assembler   import assemble_prompt, _TOOLC_SCHEMA_BLOCK
    from tool_b.agent_runner       import check_agent_available, run_agent
    from tool_b.output_writer      import write_pattern_json

    agent_name = args.agent

    # ── V-pre: Check agent CLI availability ───────────────────────────────────
    if not check_agent_available(agent_name):
        print(
            f"Error: Agent CLI '{agent_name}' not found in PATH.\n"
            f"Install it or use --agent to select a different agent.",
            file=sys.stderr,
        )
        sys.exit(7)

    # ── Read JSONL ────────────────────────────────────────────────────────────
    global_stats, file_records = read_jsonl(args.jsonl)

    # ── Read human notes ──────────────────────────────────────────────────────
    human_notes = ""
    if args.human_notes:
        p = Path(args.human_notes)
        if not p.exists():
            print(f"Error: --human-notes file not found: {args.human_notes}", file=sys.stderr)
            sys.exit(8)
        human_notes = p.read_text(encoding="utf-8")

    # ── Build adapter ─────────────────────────────────────────────────────────
    adapter = _get_adapter(agent_name, getattr(args, "mock_response_file", None))
    model   = args.agent_model or adapter.default_model

    # ── Assemble prompt with truncation if needed ─────────────────────────────
    extra_kwargs = dict(
        collection_name  = args.collection_name,
        base_url_variable= args.base_url,
        human_notes      = human_notes,
        max_signals      = args.max_context_signals,
        max_files        = args.max_context_files,
    )

    selected_signals, selected_files, prompt = truncate_context(
        global_stats      = global_stats,
        file_records      = file_records,
        prompt_fn         = assemble_prompt,
        agent             = agent_name,
        max_signals       = args.max_context_signals,
        max_files         = args.max_context_files,
        extra_kwargs      = extra_kwargs,
    )

    estimated_tokens = estimate_tokens(prompt)

    # ── Dry-run mode ──────────────────────────────────────────────────────────
    if args.dry_run:
        fw = global_stats.get("framework", {})
        limit = get_agent_token_limit(agent_name)
        within = "OK" if estimated_tokens <= limit else "EXCEEDS LIMIT"
        print("=== ToolB Dry Run ===")
        print(f"Agent              : {agent_name} ({model})")
        print(f"JSONL              : {args.jsonl}")
        print(f"JSONL schema       : {global_stats.get('schema_version','?')} OK")
        print(f"Framework (JSONL)  : {fw.get('detected','?')} (confidence: {fw.get('confidence','?')})")
        print(f"Output             : {args.out} (not written — dry run)")
        print()
        print("Context assembled:")
        print(f"  Signals in prompt  : {len(selected_signals)} (max: {args.max_context_signals})")
        print(f"  File records       : {len(selected_files)} (max: {args.max_context_files})")
        print(f"  Human notes        : {'yes (' + str(len(human_notes)) + ' chars)' if human_notes else 'no'}")
        print(f"  Estimated tokens   : ~{estimated_tokens:,} (limit: {limit:,}) {within}")
        print()
        print("Prompt preview (first 500 chars):")
        print("---")
        print(prompt[:500])
        print("---")
        print()
        print("Full prompt would be written to stdout with --dry-run --verbose")
        print("Agent would NOT be called. Remove --dry-run to execute.")
        sys.exit(0)

    # ── Call agent ────────────────────────────────────────────────────────────
    print(
        f"[ToolB] Calling {agent_name} ({model}) — "
        f"~{estimated_tokens:,} tokens, {len(selected_signals)} signals, "
        f"{len(selected_files)} files — timeout {args.agent_timeout}s …"
    )
    print("[ToolB] Waiting for agent response, this may take a while …")
    parsed, retry_count = run_agent(
        adapter           = adapter,
        prompt            = prompt,
        model             = model,
        timeout           = args.agent_timeout,
        global_stats      = global_stats,
        raw_response_path = args.raw_response,
        skip_validation   = args.skip_validation,
        toolc_schema_block= _TOOLC_SCHEMA_BLOCK,
    )

    # ── Write output ──────────────────────────────────────────────────────────
    retry_note = f" ({retry_count} retry)" if retry_count else ""
    print(f"[ToolB] Parsing and validating response{retry_note} …")
    write_pattern_json(
        parsed,
        args.out,
        agent                   = agent_name,
        agent_model             = model,
        source_jsonl            = args.jsonl,
        jsonl_schema_version    = global_stats.get("schema_version", "2.0"),
        context_signals_used    = len(selected_signals),
        context_files_used      = len(selected_files),
        human_notes_provided    = bool(human_notes),
        validation_passed       = not args.skip_validation,
        retry_count             = retry_count,
        prompt_estimated_tokens = estimated_tokens,
    )
    print(f"[ToolB] Done — pattern.json written to: {args.out}")


def cmd_check_agents(args: argparse.Namespace) -> None:
    agents = ["claude", "codex", "gemini"]
    print("=== ToolB Agent Availability Check ===")
    for agent in agents:
        path = shutil.which(agent)
        if path:
            # Try to get version
            import subprocess
            try:
                result = subprocess.run(
                    [agent, "--version"],
                    capture_output=True, text=True, timeout=5,
                )
                version = (result.stdout or result.stderr).strip().split("\n")[0]
                version = version[:60] if version else "unknown version"
            except Exception:
                version = "version unknown"
            print(f"{agent:<8}: available ({version})")
        else:
            print(f"{agent:<8}: not found ({agent} not in PATH)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tool_b",
        description="ToolB — AI Agent Pattern Generator for PHP API Discovery toolchain",
    )
    sub = parser.add_subparsers(dest="command")

    # ── generate subcommand ───────────────────────────────────────────────────
    gen = sub.add_parser("generate", help="Generate pattern.json from features_raw.jsonl")
    gen.add_argument("--jsonl",               required=True,  help="Path to features_raw.jsonl from ToolA v2")
    gen.add_argument("--out",                 required=True,  help="Output path for generated pattern.json")
    gen.add_argument("--agent",               default="claude", choices=["claude","codex","gemini","mock"],
                     help="AI agent to use (default: claude)")
    gen.add_argument("--agent-model",         default=None,   help="Override model name")
    gen.add_argument("--agent-timeout",       default=120,    type=int, help="Max seconds to wait for agent response (default: 120)")
    gen.add_argument("--max-context-signals", default=50,     type=int, help="Max signals in prompt context (default: 50)")
    gen.add_argument("--max-context-files",   default=20,     type=int, help="Max file records in prompt context (default: 20)")
    gen.add_argument("--human-notes",         default=None,   help="Path to human reviewer notes file")
    gen.add_argument("--dry-run",             action="store_true", help="Print assembled prompt only; do not call agent")
    gen.add_argument("--raw-response",        default=None,   help="Save raw agent response to this path")
    gen.add_argument("--skip-validation",     action="store_true", help="Skip ToolC schema validation (not recommended)")
    gen.add_argument("--collection-name",     default="API Collection", help='Sets postman_defaults.collection_name (default: "API Collection")')
    gen.add_argument("--base-url",            default="baseUrl", help='Sets postman_defaults.base_url_variable (default: "baseUrl")')
    gen.add_argument("--mock-response-file",  default=None,   help="Response file for --agent mock (test only)")

    # ── check-agents subcommand ───────────────────────────────────────────────
    sub.add_parser("check-agents", help="Check which agent CLIs are available in PATH")

    return parser


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)
    elif args.command == "generate":
        cmd_generate(args)
    elif args.command == "check-agents":
        cmd_check_agents(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
