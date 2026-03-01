"""context_selector.py — Select top-N signals and file records for prompt context.

Selection is deterministic: sort by score DESC, path ASC for files;
seen_in_files DESC, signal ASC for signals.
"""

from __future__ import annotations

from typing import Any


def select_signals(
    global_stats: dict[str, Any],
    max_signals: int,
) -> list[dict[str, Any]]:
    """Return top-N signals from signal_frequency_table sorted by seen_in_files DESC."""
    table = global_stats.get("signal_frequency_table", [])
    sorted_signals = sorted(
        table,
        key=lambda s: (-s.get("seen_in_files", 0), s.get("signal", "")),
    )
    return sorted_signals[:max_signals]


def select_file_records(
    file_records: list[dict[str, Any]],
    max_files: int,
) -> list[dict[str, Any]]:
    """
    Return top-N file records sorted by score DESC, path ASC.
    Deterministic: same JSONL always produces same context.
    """
    sorted_records = sorted(
        file_records,
        key=lambda r: (-r.get("score", 0), r.get("path", "")),
    )
    return sorted_records[:max_files]


def estimate_tokens(text: str) -> int:
    """Simple heuristic: 1 token ≈ 4 characters."""
    return len(text) // 4


def get_agent_token_limit(agent: str) -> int:
    limits = {
        "claude": 150_000,
        "codex":  100_000,
        "gemini": 800_000,
        "mock":   800_000,
    }
    return limits.get(agent, 150_000)


def truncate_context(
    global_stats: dict[str, Any],
    file_records: list[dict[str, Any]],
    prompt_fn,                  # callable(global_stats, signals, files, ...) -> str
    agent: str,
    max_signals: int,
    max_files: int,
    extra_kwargs: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """
    Iteratively reduce context until prompt fits within agent token limit.
    Returns (selected_signals, selected_files, assembled_prompt).
    Raises SystemExit(5) if still over limit after full reduction.
    """
    import sys

    limit = get_agent_token_limit(agent)

    current_max_files   = max_files
    current_max_signals = max_signals

    while True:
        signals = select_signals(global_stats, current_max_signals)
        files   = select_file_records(file_records, current_max_files)
        prompt  = prompt_fn(global_stats, signals, files, **extra_kwargs)
        tokens  = estimate_tokens(prompt)

        if tokens <= limit:
            return signals, files, prompt

        # Truncation priority order:
        # 1. Reduce files by 5
        if current_max_files > 5:
            current_max_files = max(5, current_max_files - 5)
            continue

        # 2. Reduce signals
        if current_max_signals > 10:
            current_max_signals = max(10, current_max_signals - 5)
            continue

        # 3. Truncate human_notes (handled in prompt_assembler via extra_kwargs)
        human_notes = extra_kwargs.get("human_notes", "")
        if human_notes and len(human_notes) > 1500:
            extra_kwargs = {**extra_kwargs, "human_notes": human_notes[:1500] + "\n[... truncated ...]"}
            continue

        # 4. Still over limit
        print(
            f"Error: Prompt exceeds {agent} context limit ({limit} tokens) even after "
            f"maximum truncation. Use --max-context-files and --max-context-signals to "
            f"reduce context manually.",
            file=sys.stderr,
        )
        sys.exit(5)
