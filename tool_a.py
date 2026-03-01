#!/usr/bin/env python3
"""
# PHP API Discovery Tool (Tool A)

This script is a CLI utility to scan a PHP codebase and extract features
indicative of API endpoints. It generates a human-readable Markdown report
and an optional machine-readable JSONL file with raw data.

## Features

- Scans PHP files in a given directory.
- Identifies signals for JSON output, data input, and request methods.
- Scores files based on a heuristic to estimate the likelihood of being an API endpoint.
- Extracts code snippets around potential output points.
- Redacts potential secrets in snippets.
- Generates a summary report and detailed per-file analysis.

## How to Run

The tool is structured as a Python module. You can run it directly.

### Prerequisites

- Python 3.7+

### Installation

No installation is required. Just run the script from the project root.

### Examples

1.  **Scan a project and generate a Markdown report:**
    ```bash
    python tool_a.py scan --root /path/to/your/php-project --out report.md
    ```

2.  **Scan the current directory and generate both Markdown and JSONL reports:**
    ```bash
    python tool_a.py scan --root . --out report.md --raw features.jsonl
    ```

3.  **Scan with custom exclusions and a higher file limit:**
    ```bash
    python tool_a.py scan --root . --out report.md --exclude vendor node_modules private --max-files 50000
    ```

## CLI Arguments (`scan` command)

- `--root`: (Required) The root path of the PHP project to scan.
- `--out`: (Required) The output path for the Markdown report file.
- `--raw`: (Optional) The output path for the raw JSONL features file.
- `--exclude`: (Optional) A space-separated list of directory names to exclude.
  - Default: `vendor node_modules storage cache logs tmp .git`
- `--extensions`: (Optional) A space-separated list of file extensions to include.
  - Default: `.php`
- `--max-files`: (Optional) The maximum number of files to scan before stopping.
  - Default: `20000`
- `--max-snippet-lines`: (Optional) The number of lines to include in code snippets.
  - Default: `10`
- `--max-file-size-mb`: (Optional) The maximum file size in MB to process.
  - Default: `5`
"""
import sys
from pathlib import Path

# Add the parent directory to the sys.path to allow for module imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tool_a.__main__ import main

if __name__ == "__main__":
    main()
