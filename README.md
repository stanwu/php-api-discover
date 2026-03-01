# PHP API Discovery Tool (Tool A)

## Description

This script is a command-line interface (CLI) utility designed to scan a PHP codebase to identify and extract features that are indicative of API endpoints. It generates both a human-readable Markdown report and an optional machine-readable JSONL file containing the raw extracted data.

## Features

- Scans PHP files within a specified directory.
- Identifies signals for JSON output, data input (`$_POST`, `$_GET`, `$_REQUEST`), and HTTP request methods (`$_SERVER['REQUEST_METHOD']`).
- Scores files using a heuristic to estimate the likelihood of them being an API endpoint.
- Extracts relevant code snippets surrounding potential API output points.
- Automatically redacts potential secrets found within the code snippets.
- Generates a summary report and a detailed per-file analysis.

## How to Run

The tool is structured as a Python module and can be run directly from the command line.

### Prerequisites

- Python 3.7 or newer.

### Installation

No installation is required. You can run the script directly from the project's root directory.

### Usage Examples

1.  **Basic Scan:** Scan a project located at `/path/to/your/php-project` and save the report to `report.md`.
    ```bash
    python tool_a.py scan --root /path/to/your/php-project --out report.md
    ```

2.  **Scan Current Directory with Raw Output:** Scan the current directory (`.`), generate a Markdown report, and also output the raw feature data to `features.jsonl`.
    ```bash
    python tool_a.py scan --root . --out report.md --raw features.jsonl
    ```

3.  **Scan with Custom Exclusions:** Scan the current directory but exclude the `vendor`, `node_modules`, and `private` directories from the scan.
    ```bash
    python tool_a.py scan --root . --out report.md --exclude vendor node_modules private
    ```

4.  **Scan with a Higher File Limit:** Increase the maximum number of files to scan to 50,000. This is useful for very large projects.
    ```bash
    python tool_a.py scan --root . --out report.md --max-files 50000
    ```

5.  **Scan for Specific File Extensions:** Scan only for files with `.php` and `.inc` extensions.
    ```bash
    python tool_a.py scan --root . --out report.md --extensions .php .inc
    ```

6.  **Quick Scan with Small Snippets:** Perform a quick scan on a limited number of files and reduce the snippet size to 5 lines for a faster overview.
    ```bash
    python tool_a.py scan --root . --out quick_report.md --max-files 100 --max-snippet-lines 5
    ```

7.  **Output to a Different Directory:** Place the generated report in a `reports/` subdirectory. (Ensure the directory exists first).
    ```bash
    mkdir -p reports
    python tool_a.py scan --root . --out reports/analysis.md
    ```


## CLI Arguments (`scan` command)

-   `--root`: (Required) The root path of the PHP project to scan.
-   `--out`: (Required) The output path for the Markdown report file.
-   `--raw`: (Optional) The output path for the raw JSONL features file.
-   `--exclude`: (Optional) A space-separated list of directory names to exclude.
    -   Default: `vendor node_modules storage cache logs tmp .git`
-   `--extensions`: (Optional) A space-separated list of file extensions to include.
    -   Default: `.php`
-   `--max-files`: (Optional) The maximum number of files to scan before stopping.
    -   Default: `20000`
-   `--max-snippet-lines`: (Optional) The number of lines to include in code snippets.
    -   Default: `10`
-   `--max-file-size-mb`: (Optional) The maximum file size in MB to process.
    -   Default: `5`

## License

MIT. See `LICENSE`.
