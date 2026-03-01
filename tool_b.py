#!/usr/bin/env python3
"""
tool_b — AI Agent Pattern Generator (ToolB)

Entry point wrapper. Delegates to the tool_b package's main function.

Usage:
  python tool_b.py generate --jsonl features_raw.jsonl --out pattern.json
  python tool_b.py check-agents
  python -m tool_b generate --jsonl features_raw.jsonl --out pattern.json
"""

from tool_b.__main__ import main

if __name__ == "__main__":
    main()
