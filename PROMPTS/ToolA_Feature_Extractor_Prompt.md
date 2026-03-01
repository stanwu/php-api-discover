# ToolA_Feature_Extractor_Prompt.md

You are a senior Python engineer building a codebase analysis utility.

Goal
Build a Python CLI tool ("tool_a") that scans a PHP project directory and produces a human-reviewable feature extraction report (Markdown) plus optional machine-readable raw features (JSONL). This tool must NOT attempt to fully classify endpoints; it only collects evidence and statistics to help a human (or another AI) author a rules file later.

Primary Use Case
I own the PHP codebase and it has consistent patterns. I want to discover common API/JSON-output fingerprints across the project and generate a report that makes those patterns obvious and reviewable.

Inputs
- Root path of a PHP project (local folder).
- Optional exclude directories (default exclude: vendor, node_modules, storage, cache, logs, tmp, .git).
- Optional include extensions (default: .php; optionally support .inc, .phtml).
- Optional max snippet lines and max files scanned.

Outputs
1) features_report.md
A structured Markdown report containing:
- Summary stats:
  - total files scanned
  - total PHP files scanned
  - top directories by PHP file count
  - top detected signals and their frequencies
  - top candidate endpoint files by score (score is only a heuristic)
- Per-file section for each scanned PHP file (or for files above a minimum score), including:
  - File path
  - Heuristic score (0–100), based on evidence only
  - Matched evidence list (signals):
    - JSON output signals (json_encode, application/json headers, exit/die(json), framework helpers like wp_send_json, response()->json, custom helpers like returnJson/apiResponse/outputJson if detected)
    - Input signals (use of $_GET, $_POST, $_REQUEST, php://input, json_decode(file_get_contents('php://input'), true))
    - Request-method checks ($_SERVER['REQUEST_METHOD'], etc.)
    - Negative/UI signals (<html, render, template, include view/header/footer, echo with HTML tags)
  - Extracted parameter hints:
    - keys used in $_GET['key'], $_POST['key'], $_REQUEST['key']
    - suspected JSON-body keys if array indexing is used (e.g., $body['key'])
  - Output envelope hints:
    - common response keys observed as string literals (ok, success, code, message, data, result, error, etc.)
  - Snippets (bounded):
    - A short snippet around each detected output point (echo/print/exit/die/returnJson-like call). Capture ±N lines around the match.
    - Keep snippets small (e.g., 30–80 lines per file total).
- Safety redaction:
  - If the tool detects patterns that look like secrets (API keys, tokens, passwords), redact values in report snippets (keep only key names and a placeholder like "REDACTED").

2) features_raw.jsonl (optional, controlled by a CLI flag)
Each line is one JSON object for a file with fields like:
- path
- score
- signals { strong:[], weak:[], negative:[] }
- input_params { get:[], post:[], request:[], json_body:[] }
- method_hints []
- envelope_keys []
- output_points [{kind, line_no, context_excerpt}]
- notes []

CLI Requirements
- Provide a CLI with argparse or typer.
- Example usage:
  - python tool_a.py scan --root /path/to/project --out features_report.md
  - python tool_a.py scan --root . --out features_report.md --raw features_raw.jsonl
  - python tool_a.py scan --root . --exclude vendor node_modules storage --max-files 20000
- Must run on macOS/Linux.
- Must be fast and memory-conscious:
  - Stream files; do not load the entire repo into memory.
  - Skip very large files beyond a configurable size limit (default e.g. 2–5 MB) but record that they were skipped.

Scoring (Heuristic Only)
Implement a simple, explainable scoring model:
- Strong JSON output evidence adds large points (e.g., application/json header, custom json helper, die/exit(json_encode(...))).
- Weak evidence adds smaller points (json_encode alone, Accept headers, etc.).
- Negative/UI evidence subtracts points.
Output the exact reasons for the score in the report so a human can audit the scoring.

Implementation Notes
- Use robust file reading with error handling for encoding issues.
- Use regex-based detection (acceptable), but structure the code so it can be extended later.
- Keep the code modular:
  - scanner (walk filesystem)
  - detector (signals + parameters + output points)
  - redactor (secrets masking)
  - reporter (markdown writer)
  - serializer (jsonl writer)

Deliverables
- tool_a.py (single-file is ok, multi-file module is better)
- README.md section embedded at top of the script or separate: how to run, examples
- A small test plan (not necessarily full unit tests, but at least a minimal sanity test script or guidance)

Non-Goals
- Do NOT attempt to generate Postman files.
- Do NOT attempt to fully resolve routing rules (treat each PHP file as a potential endpoint candidate by path only).
- Do NOT require internet access.

Quality Bar
- Deterministic output.
- Clear, human-auditable report.
- Conservative redaction.
- Avoid hallucinating patterns: only report what is actually found in code.

Now produce the full Python implementation and minimal documentation.

