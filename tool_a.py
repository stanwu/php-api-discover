#!/usr/bin/env python3
"""
tool_a — PHP API Feature Extractor  (v2)

Entry point wrapper.  Delegates to the tool_a package's main function.

Usage:
  python tool_a.py scan --root /path/to/project --out report.md
  python tool_a.py scan --root . --out report.md --raw raw.jsonl
  python -m tool_a  scan --root . --out report.md
"""

from tool_a.__main__ import main

if __name__ == "__main__":
    main()
