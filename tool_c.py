#!/usr/bin/env python3
"""
tool_c — Rules-Based API Endpoint Classifier and Postman Collection Generator

Entry point wrapper. Delegates to the tool_c package's main function.

Usage:
  python tool_c.py generate --jsonl features_raw.jsonl --rules pattern.json --out postman.json
  python tool_c.py dry-run  --jsonl features_raw.jsonl --rules pattern.json
  python tool_c.py validate-rules --rules pattern.json --jsonl features_raw.jsonl
  python -m tool_c generate --jsonl features_raw.jsonl --rules pattern.json --out postman.json
"""

from tool_c.__main__ import main

if __name__ == "__main__":
    main()
