# PHP API Discovery Toolchain

A two-tool pipeline for discovering and classifying PHP API endpoints.

| Tool | Purpose | Output |
|---|---|---|
| **tool_a** | Scans a PHP project and extracts scored API endpoint evidence | Markdown report + JSONL |
| **tool_b** | Feeds the JSONL into an AI agent to generate a `pattern.json` classification file | `pattern.json` |

---

## Table of Contents

### tool_a — PHP API Feature Extractor
- [How It Works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
- [Framework Detection](#framework-detection)
- [Scoring System](#scoring-system)
- [Signal Catalogue](#signal-catalogue)
- [Output: Markdown Report](#output-markdown-report)
- [Output: JSONL File](#output-jsonl-file)
- [Secret Redaction](#secret-redaction)
- [Custom Helper Discovery](#custom-helper-discovery)
- [Examples](#examples)
- [Score Interpretation Guide](#score-interpretation-guide)

### tool_b — AI Agent Pattern Generator
- [tool_b: How It Works](#tool_b-how-it-works)
- [tool_b: Requirements](#tool_b-requirements)
- [tool_b: Quick Start](#tool_b-quick-start)
- [tool_b: CLI Reference](#tool_b-cli-reference)
- [tool_b: Supported Agents](#tool_b-supported-agents)
- [tool_b: Exit Codes](#tool_b-exit-codes)
- [tool_b: Examples](#tool_b-examples)

---

# tool_a — PHP API Feature Extractor

Scans a PHP project and extracts evidence that a file is an **API endpoint** (JSON-returning) rather than a UI page (HTML-returning). Produces a scored Markdown report and an optional structured JSONL file for downstream tooling.

---

## How It Works

The scanner runs in **two passes**:

1. **Pass 1 — Discovery**
   - Walks the directory tree and collects PHP files (skipping `vendor/`, `node_modules/`, etc.).
   - Detects the PHP framework from filesystem fingerprints.
   - Builds a **custom helper registry**: finds any project-defined wrapper functions that internally call known JSON signals (e.g. a `send_json()` helper that calls `json_encode()`).
   - Counts global signal frequencies across all files.

2. **Pass 2 — Analysis**
   - Loads route definitions (Laravel routes file, WordPress AJAX hooks).
   - Analyzes every file with the full signal profile: matched signals, input parameters, output envelopes, dynamic dispatch patterns.
   - Computes a heuristic score `[0–100]` for each file.

Results are written to a **Markdown report** (human-readable) and optionally a **JSONL file** (machine-readable) for use by downstream classification tools.

---

## Requirements

- Python 3.9 or later
- No third-party dependencies (standard library only)

---

## Installation

```bash
git clone <repo-url>
cd php-api-discover
# No pip install required — run directly
python tool_a.py --help
```

---

## Quick Start

```bash
# Scan a project, write report to features_report.md
python tool_a.py scan --root /path/to/project

# Specify output paths explicitly
python tool_a.py scan --root /path/to/project --out report.md --raw raw.jsonl

# Short form (the 'scan' subcommand is implied)
python tool_a.py --root /path/to/project --out report.md

# Run as a module
python -m tool_a scan --root /path/to/project --out report.md
```

---

## CLI Reference

```
python tool_a.py scan [OPTIONS]
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--root PATH` | path | *(required)* | PHP project root directory to scan. |
| `--out PATH` | path | `features_report.md` | Destination for the Markdown report. |
| `--raw PATH` | path | *(none)* | Destination for the JSONL output (optional). |
| `--framework NAME` | choice | *(auto)* | Force a specific framework profile. Choices: `laravel`, `wordpress`, `codeigniter`, `symfony`, `slim`, `plain`. Skips auto-detection. |
| `--exclude DIR …` | list | `vendor node_modules storage cache logs tmp .git` | Directory names to exclude from the walk. Replaces the default list entirely when specified. |
| `--ext EXT …` | list | `.php` | File extensions to include. Replaces the default. |
| `--max-files N` | int | `0` (unlimited) | Stop after collecting N files. Useful for quick spot-checks on large codebases. |
| `--max-file-size MB` | float | `3` | Skip files larger than this size in megabytes. |
| `--max-snippet-lines N` | int | `80` | Maximum total snippet lines written per file into the report. |
| `--min-score N` | int | `0` | Exclude files with a score below N from the Markdown report. Does not affect JSONL output. |

---

## Framework Detection

The tool auto-detects the PHP framework by inspecting the project root for known files and directories. Detection is performed in priority order:

| Framework | Detection criteria | Confidence |
|---|---|---|
| **Laravel** | `artisan` file **and** `app/Http/Controllers/` directory | high |
| **WordPress** | `wp-config.php` **or** `wp-includes/` directory | high |
| **Symfony** | `symfony.lock` **or** `src/Kernel.php` | high |
| **CodeIgniter** | `system/core/CodeIgniter.php` | high |
| **CodeIgniter** | `application/` directory | medium |
| **Slim / Lumen** | `slim/slim` or `laravel/lumen-framework` in `composer.json` | high |
| **Plain PHP** | None of the above matched | low |

To override auto-detection:

```bash
python tool_a.py scan --root /path/to/project --framework wordpress
```

---

## Scoring System

Each file starts at **0** and accumulates points based on matched signals. The final score is clamped to `[0, 100]`.

Every signal contributes a signed **delta**:

| Signal category | Effect | Typical delta |
|---|---|---|
| Strong | Positive | +20 to +35 |
| Weak | Positive | +5 to +10 |
| Negative | Negative | −5 to −20 |
| Custom helper call | Positive | +20 |

The score breakdown (which signal added/subtracted how many points, and on which line) is recorded for every file and included in both output formats.

**Interpretation thresholds** (recommended, data-driven — the report suggests values based on actual score distribution):

| Score range | Interpretation |
|---|---|
| 0 | No API evidence found |
| 1–29 | Weak or ambiguous signal — likely a UI or utility file |
| 30–59 | Moderate evidence — probable API endpoint |
| 60–100 | Strong evidence — very likely an API endpoint |

---

## Signal Catalogue

Signals are framework-specific. The table below shows representative examples.

### Plain PHP

| Signal | Kind | Delta | FP Risk |
|---|---|---|---|
| `header('Content-Type: application/json')` literal | strong | +35 | low |
| `header("Content-Type: application/json")` literal | strong | +35 | low |
| `die(json_encode(` | strong | +25 | low |
| `exit(json_encode(` | strong | +25 | low |
| `json_encode(` | weak | +10 | medium |
| `$_SERVER['HTTP_ACCEPT']` | weak | +5 | low |
| `<html` literal | negative | −20 | n/a |
| `echo` HTML tag | negative | −5 | n/a |
| `include header.php` | negative | −10 | n/a |
| `include footer.php` | negative | −10 | n/a |

### Laravel

| Signal | Kind | Delta |
|---|---|---|
| `response()->json(` | strong | +30 |
| `JsonResource` | strong | +30 |
| `->toResponse(` | strong | +30 |
| `Illuminate\Http\JsonResponse` | weak | +10 |
| `json_encode(` | weak | +10 |
| `return view(` | negative | −15 |
| `->render(` | negative | −15 |
| `Blade::` | negative | −15 |

### WordPress

| Signal | Kind | Delta |
|---|---|---|
| `wp_send_json(` | strong | +30 |
| `wp_send_json_success(` | strong | +30 |
| `wp_send_json_error(` | strong | +30 |
| `add_action('wp_ajax_'` | strong | +30 |
| `json_encode(` | weak | +10 |
| `wp_die(` | weak | +5 |
| `get_template_part(` | negative | −15 |
| `echo get_header(` | negative | −15 |

### Symfony

| Signal | Kind | Delta |
|---|---|---|
| `new JsonResponse(` | strong | +30 |
| `$this->json(` | strong | +30 |
| `JsonResponse::HTTP_` | strong | +20 |
| `Request $request` | weak | +5 |
| `$this->render(` | negative | −15 |
| `$this->renderView(` | negative | −15 |

### Slim / Lumen

| Signal | Kind | Delta |
|---|---|---|
| `$response->withHeader Content-Type application/json` | strong | +35 |
| `$response->withJson(` | strong | +30 |
| `response()->json(` | strong | +30 |
| `json_encode(` | weak | +10 |
| `return view(` | negative | −15 |

### CodeIgniter

| Signal | Kind | Delta |
|---|---|---|
| `$this->output->set_content_type('application/json')` | strong | +30 |
| `$this->response(` | strong | +30 |
| `json_encode(` | weak | +10 |
| `$this->input->post(` | weak | +5 |
| `$this->load->view(` | negative | −15 |

---

## Output: Markdown Report

The Markdown report (`--out`) contains five sections:

### 1. Header
Detected framework name, confidence level, and the evidence used for detection.

### 2. Scan Summary
- Total files scanned and skipped (with skip reasons).
- Candidate file counts at score thresholds: > 0, ≥ 30, ≥ 60.
- **Top directories** by PHP file count.
- **Signal frequency table** — how many files triggered each signal, percentage of candidates, and false-positive risk.
- **Envelope key frequency** — common JSON response keys seen across files (e.g. `data`, `status`, `error`).

### 3. Custom Helper Registry
A table of project-specific helper functions discovered in Pass 1, showing which signal they wrap and how many files call them.

### 4. Top Candidate Files
A ranked table of the top 20 files by score.

### 5. File Details
For each file above `--min-score`, a detailed breakdown including:
- Heuristic score and score breakdown (per-signal deltas with line numbers).
- Matched signals (strong / weak / negative) with occurrence counts, line numbers, and FP risk.
- Dynamic pattern notes (variable dispatch, concatenated headers, deep indirection).
- Route hints from the route mapper (HTTP method + URI + source location).
- Parameter hints (`$_GET`, `$_POST`, `$_REQUEST`, JSON body keys).
- Request method hints inferred from code.
- Output envelope hints (JSON response key names).
- Custom helpers called in this file.
- Code snippets around output points (with secrets redacted).
- Redaction notice if any values were masked.

---

## Output: JSONL File

When `--raw` is specified, a JSONL file is written with **three sections**:

```
Line 0       : global_stats record
Lines 1–N    : one file record per scanned file
Last line    : skipped_files_summary record
```

All records carry `schema_version: "2.0"`.

### global_stats record (line 0)

```jsonc
{
  "record_type": "global_stats",
  "schema_version": "2.0",
  "generated_at": "2026-03-01T10:00:00+00:00",
  "framework": {
    "detected": "laravel",
    "confidence": "high",
    "evidence": ["artisan file found", "app/Http/Controllers/ directory found"]
  },
  "scan_summary": {
    "total_files_scanned": 142,
    "total_files_skipped": 3,
    "skip_reasons": { "too_large": 3 },
    "candidate_files_above_score_0": 47,
    "candidate_files_above_score_30": 28,
    "candidate_files_above_score_60": 14
  },
  "signal_frequency_table": [
    {
      "signal": "response()->json(",
      "kind": "strong",
      "seen_in_files": 22,
      "pct_of_candidates": 46.8,
      "false_positive_risk": "low",
      "false_positive_risk_reason": "Framework-native signal; rarely appears in non-API files"
    }
    // ...
  ],
  "custom_helper_registry": [
    {
      "helper_name": "api_response",
      "defined_in": "app/Helpers/ApiHelper.php:12",
      "wraps_signal": "response()->json(",
      "wrap_depth": 1,
      "seen_called_in_files": 8,
      "pct_of_candidates": 17.0,
      "suggested_kind": "strong",
      "suggested_weight_hint": 20
    }
  ],
  "envelope_key_frequency": [
    { "key": "data", "seen_in_files": 18, "pct_of_candidates": 38.3 },
    { "key": "status", "seen_in_files": 12, "pct_of_candidates": 25.5 }
  ],
  "method_distribution": { "GET": 10, "POST": 14, "unknown": 23 },
  "co_occurrence_patterns": [
    {
      "signals": ["response()->json(", "json_encode("],
      "files_count": 7,
      "note": "These two signals co-occur in 7 candidate file(s)"
    }
  ],
  "pattern_json_generation_hints": {
    "recommended_strong_signals": ["response()->json(", "JsonResource"],
    "recommended_weak_signals": ["json_encode("],
    "recommended_negative_signals": ["return view("],
    "recommended_endpoint_threshold": 40,
    "recommended_uncertain_threshold": 20,
    "minimum_threshold_gap": 10,
    "score_distribution_summary": { "p25": 10, "p50": 35, "p75": 60, "p90": 80 },
    "recommended_envelope_template": {
      "keys_all_of": ["data"],
      "keys_any_of": ["status", "message"]
    },
    "warning": "These are suggestions … Human review is required."
  }
}
```

### file record (lines 1–N)

```jsonc
{
  "record_type": "file",
  "schema_version": "2.0",
  "path": "app/Http/Controllers/Api/UserController.php",
  "framework": "laravel",
  "score": 60,
  "score_breakdown": [
    { "signal": "response()->json(", "kind": "strong", "delta": 30, "line_no": 24 },
    { "signal": "json_encode(", "kind": "weak", "delta": 10, "line_no": 41 },
    { "signal": "return view(", "kind": "negative", "delta": -15, "line_no": null }
  ],
  "signals": {
    "strong": [
      {
        "name": "response()->json(",
        "occurrences": 2,
        "line_nos": [24, 58],
        "global_seen_in_files": 22,
        "false_positive_risk": "low"
      }
    ],
    "weak": [ /* ... */ ],
    "negative": [ /* ... */ ]
  },
  "dynamic_notes": [
    {
      "type": "variable_dispatch",
      "line_no": 77,
      "note": "Response dispatched via variable — cannot statically resolve type",
      "raw_line": "  return $response($data);"
    }
  ],
  "route_hints": [
    {
      "method": "GET",
      "uri": "/api/users/{id}",
      "source_file": "routes/api.php",
      "source_line": 14,
      "confidence": "high",
      "controller_method": "UserController@show"
    }
  ],
  "input_params": {
    "get": [],
    "post": [{ "key": "email", "line_no": 32 }],
    "request": [],
    "json_body": [{ "key": "name", "line_no": 34 }]
  },
  "method_hints": [{ "method": "POST" }],
  "envelope_keys": [
    { "key": "data", "line_no": 25 },
    { "key": "message", "line_no": 59 }
  ],
  "output_points": [
    {
      "kind": "json_response",
      "line_no": 24,
      "context_excerpt": "return response()->json(['data' => $user, 'message' => 'ok']);"
    }
  ],
  "custom_helpers_called": [
    {
      "name": "api_response",
      "line_no": 42,
      "resolved_to": "response()->json(",
      "wrap_depth": 1
    }
  ],
  "redaction_count": 0,
  "skipped": false,
  "skip_reason": null,
  "encoding_note": null,
  "notes": []
}
```

### skipped_files_summary (last line)

```jsonc
{
  "record_type": "skipped_files_summary",
  "skipped_files": [
    { "path": "storage/dumps/legacy.php", "reason": "too_large", "size_mb": 5.2 }
  ]
}
```

---

## Secret Redaction

All code snippets embedded in the report and JSONL output are passed through the secret redactor before writing. Four ordered rules apply:

1. **Assignment / dict entries** — values of keys named `api_key`, `token`, `secret`, `password`, `passwd`, `auth` (≥ 8 chars) are replaced with `REDACTED`.
2. **Long alphanumeric strings** — any quoted string of 32+ characters (matching a token/hash pattern) is replaced with `REDACTED`.
3. **Bearer tokens** — `Bearer <token>` values are replaced with `Bearer REDACTED`.
4. **`getenv()` calls** — preserved as-is and flagged safe (the value is not hardcoded).

The `redaction_count` field on each file record counts how many substitutions were made. The Markdown report displays a notice when redactions occurred.

---

## Custom Helper Discovery

During Pass 1 the scanner looks for **standalone PHP functions** (not class methods) whose bodies contain at least one known JSON-output signal within the first 60 lines after the `function` keyword. Examples of wrappable signals:

- `json_encode(`
- `wp_send_json(`, `wp_send_json_success(`, `wp_send_json_error(`
- `response()->json(`
- `new JsonResponse(`
- `$this->json(`
- `header('Content-Type: application/json'`
- `die/exit(json_encode(`
- `$this->output->set_content_type(`
- `$response->withJson(`

Discovered helpers are recorded in the **Custom Helper Registry** and treated as strong signals (+20) during Pass 2. The registry is written to both output formats with statistics on how often each helper is called across the codebase.

---

## Examples

### Example 1 — Basic scan of a Laravel project

```bash
python tool_a.py scan \
  --root ~/projects/my-laravel-app \
  --out laravel_report.md
```

Console output:
```
[framework] Detected: laravel (confidence: high)
            artisan file found
            app/Http/Controllers/ directory found
[scanner]   Collecting file paths …
            142 files to scan, 3 skipped.
[pass 1]    Building helper registry …
            2 custom helpers found.
[pass 1]    Counting global signal frequencies …
[routes]    Loading route definitions …
[pass 2]    Analysing files …
[report]    Writing Markdown report to 'laravel_report.md' …
            Done.

[done]      Total: 142 scanned, 3 skipped, 47 candidates (score>0), 28 above 30, 14 above 60.
```

---

### Example 2 — Laravel scan with JSONL output for downstream tools

```bash
python tool_a.py scan \
  --root ~/projects/my-laravel-app \
  --out report.md \
  --raw raw.jsonl
```

Parse the JSONL in Python:

```python
import json

records = []
with open("raw.jsonl") as f:
    for line in f:
        records.append(json.loads(line))

global_stats = records[0]          # global_stats record
file_records = records[1:-1]       # file records
skipped = records[-1]              # skipped_files_summary

# Find all files with score >= 60
api_files = [r for r in file_records if r["score"] >= 60]
for f in api_files:
    print(f["path"], f["score"])
```

---

### Example 3 — WordPress scan showing only high-confidence files

```bash
python tool_a.py scan \
  --root ~/projects/my-wp-plugin \
  --framework wordpress \
  --min-score 60 \
  --out wp_api_report.md
```

Only files scoring ≥ 60 appear in the Markdown report. All files are still written to JSONL if `--raw` is specified.

---

### Example 4 — Large codebase: limit files and increase size threshold

```bash
python tool_a.py scan \
  --root ~/projects/big-legacy-app \
  --max-files 500 \
  --max-file-size 10 \
  --out report.md \
  --raw raw.jsonl
```

Scans at most 500 files and includes files up to 10 MB (default is 3 MB).

---

### Example 5 — Exclude additional directories

```bash
python tool_a.py scan \
  --root ~/projects/my-app \
  --exclude vendor node_modules tests fixtures \
  --out report.md
```

The `--exclude` list **replaces** the default exclusion list entirely. Include all directories you want to skip.

---

### Example 6 — Scan non-PHP files (e.g. module files)

```bash
python tool_a.py scan \
  --root ~/projects/my-app \
  --ext .php .module \
  --out report.md
```

---

### Example 7 — Quick spot-check with score filter

```bash
python tool_a.py scan \
  --root ~/projects/my-app \
  --max-files 50 \
  --min-score 30 \
  --out quick_check.md
```

Scans only the first 50 files found and reports only those with score ≥ 30.

---

## Score Interpretation Guide

| Score | Verdict | Action |
|---|---|---|
| **0** | No API evidence | Likely a UI page, config, or utility. Skip. |
| **1–9** | Noise / incidental | Usually a false positive from a weak signal alone. |
| **10–29** | Ambiguous | Contains some API-like code but also negative signals. Manual review recommended. |
| **30–59** | Probable endpoint | Strong evidence with no strong negative signals. Treat as an API endpoint candidate. |
| **60–100** | Confirmed endpoint | Multiple strong signals, no significant negative signals. High confidence API endpoint. |

The `pattern_json_generation_hints` section in the JSONL global stats provides **data-driven threshold recommendations** derived from the actual score distribution of the scanned project. These are starting points — always apply human judgment before using them in production classifiers.

---

# tool_b — AI Agent Pattern Generator

Reads the JSONL output produced by `tool_a` and invokes an AI agent (Claude, Codex, or Gemini) to generate a `pattern.json` classification file for use by downstream tools.

---

## tool_b: How It Works

1. **Read JSONL** — Loads the `global_stats` record and all `file` records from the `features_raw.jsonl` produced by `tool_a`. Exits with code `2` if the schema version is not `"2.0"`.
2. **Select context** — Deterministically picks the top signals (by frequency) and top file records (by score) that fit within the agent's token limit. Truncates automatically if the assembled prompt would be too large.
3. **Assemble prompt** — Builds a structured 7-block prompt containing framework info, signal frequency data, file evidence, envelope patterns, human reviewer notes (if provided), and the full `pattern.json` schema.
4. **Call agent** — Invokes the chosen AI agent CLI as a subprocess and captures its stdout.
5. **Parse & validate** — Extracts JSON from the response (fenced or bare). On a parse failure, issues one repair prompt. On a schema validation failure, issues one correction prompt.
6. **Write output** — Appends a `_tool_b_meta` block and writes the validated `pattern.json` to the specified path.

---

## tool_b: Requirements

- Python 3.9 or later
- No third-party Python dependencies (standard library only)
- At least one supported agent CLI in `PATH`: `claude`, `codex`, or `gemini`

---

## tool_b: Quick Start

```bash
# Step 1: run tool_a to produce features_raw.jsonl
python tool_a.py scan --root /path/to/project --raw features_raw.jsonl --out report.md

# Step 2: run tool_b to generate pattern.json
python tool_b.py generate --jsonl features_raw.jsonl --out pattern.json

# Check which agent CLIs are available
python tool_b.py check-agents

# Dry run — inspect the assembled prompt without calling the agent
python tool_b.py generate --jsonl features_raw.jsonl --out pattern.json --dry-run
```

---

## tool_b: CLI Reference

### `generate` subcommand

```
python tool_b.py generate [OPTIONS]
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--jsonl PATH` | path | *(required)* | Path to `features_raw.jsonl` produced by `tool_a`. |
| `--out PATH` | path | *(required)* | Output path for the generated `pattern.json`. |
| `--agent NAME` | choice | `claude` | AI agent to use. Choices: `claude`, `codex`, `gemini`, `mock`. |
| `--agent-model NAME` | string | *(agent default)* | Override the model name passed to the agent CLI. |
| `--agent-timeout N` | int | `120` | Maximum seconds to wait for the agent response. |
| `--max-context-signals N` | int | `50` | Maximum number of signals included in the prompt context. |
| `--max-context-files N` | int | `20` | Maximum number of file records included in the prompt context. |
| `--human-notes PATH` | path | *(none)* | Path to a plain-text file containing human reviewer notes appended to the prompt. |
| `--dry-run` | flag | — | Assemble and print the prompt; do not call the agent or write output. |
| `--raw-response PATH` | path | *(none)* | Save the raw agent response to this path (useful for debugging). |
| `--skip-validation` | flag | — | Skip schema validation of the agent response. Not recommended. |
| `--collection-name NAME` | string | `"API Collection"` | Sets `postman_defaults.collection_name` in the output. |
| `--base-url NAME` | string | `"baseUrl"` | Sets `postman_defaults.base_url_variable` in the output. |
| `--mock-response-file PATH` | path | *(none)* | Response file for `--agent mock` (test use only). |

### `check-agents` subcommand

```
python tool_b.py check-agents
```

Checks whether each supported agent CLI (`claude`, `codex`, `gemini`) is available in `PATH` and prints its version.

---

## tool_b: Supported Agents

| Agent | CLI binary | Notes |
|---|---|---|
| **claude** | `claude` | Default. Uses `--print` and `-p` flags. |
| **codex** | `codex` | Uses `--quiet --full-auto` flags. |
| **gemini** | `gemini` | Uses `-p` flag. |
| **mock** | *(none)* | Reads response from `--mock-response-file`. For testing only. |

Each agent has a default model. Override with `--agent-model`.

---

## tool_b: Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success — `pattern.json` written. |
| `2` | Wrong JSONL schema version (expected `"2.0"`). |
| `3` | Agent timed out. |
| `4` | Agent response was unparseable JSON after repair attempt. |
| `5` | Assembled prompt context too large even after truncation. |
| `6` | Agent response parsed but failed schema validation after correction attempt. |
| `7` | Agent CLI not found in `PATH`. |
| `8` | JSONL file unreadable or `--human-notes` file not found. |

---

## tool_b: Examples

### Example 1 — Full pipeline (Laravel project)

```bash
# Scan and extract features
python tool_a.py scan \
  --root ~/projects/my-laravel-app \
  --out report.md \
  --raw features_raw.jsonl

# Generate pattern.json with Claude
python tool_b.py generate \
  --jsonl features_raw.jsonl \
  --out pattern.json \
  --agent claude
```

---

### Example 2 — Dry run to inspect the prompt

```bash
python tool_b.py generate \
  --jsonl features_raw.jsonl \
  --out pattern.json \
  --agent claude \
  --dry-run
```

Prints context statistics and the first 500 characters of the prompt. No agent call is made and no file is written.

---

### Example 3 — Add human reviewer notes

```bash
python tool_b.py generate \
  --jsonl features_raw.jsonl \
  --out pattern.json \
  --agent claude \
  --human-notes my_notes.txt
```

The contents of `my_notes.txt` are injected into the prompt as a reviewer override block before the agent generates the pattern.

---

### Example 4 — Use Gemini with a specific model and save the raw response

```bash
python tool_b.py generate \
  --jsonl features_raw.jsonl \
  --out pattern.json \
  --agent gemini \
  --agent-model gemini-2.0-flash \
  --raw-response gemini_raw.txt
```

---

### Example 5 — Limit context size for a large project

```bash
python tool_b.py generate \
  --jsonl features_raw.jsonl \
  --out pattern.json \
  --max-context-signals 30 \
  --max-context-files 10
```

Reduces the prompt to at most 30 signals and 10 file records. Signals are ranked by frequency and files by score before truncation.

---

### Example 6 — Check agent availability

```bash
python tool_b.py check-agents
```

Sample output:
```
=== ToolB Agent Availability Check ===
claude  : available (claude 1.0.3)
codex   : not found (codex not in PATH)
gemini  : available (Gemini CLI 0.1.7)
```

---

### Example 7 — Customise Postman collection name and base URL variable

```bash
python tool_b.py generate \
  --jsonl features_raw.jsonl \
  --out pattern.json \
  --collection-name "My Laravel API" \
  --base-url "apiBaseUrl"
```

`--collection-name` sets `postman_defaults.collection_name` in the output `pattern.json`.
`--base-url` sets `postman_defaults.base_url_variable` — the Postman variable name that downstream tools will use to prefix all request URLs (e.g. `{{apiBaseUrl}}/users`).

---

### Example 8 — Use Codex agent

```bash
python tool_b.py generate \
  --jsonl features_raw.jsonl \
  --out pattern.json \
  --agent codex \
  --agent-model o4-mini
```

Codex is invoked with `--quiet --full-auto` flags. Use `--agent-model` to select a specific model; the default is the adapter's built-in model.

---

### Example 9 — Extend timeout for slow agents or large codebases

```bash
python tool_b.py generate \
  --jsonl features_raw.jsonl \
  --out pattern.json \
  --agent claude \
  --agent-timeout 300
```

Raises the response deadline to 5 minutes. If the agent still does not respond in time, tool_b exits with code `3`. The default is 120 seconds.

---

### Example 10 — Use mock agent in CI / automated tests

```bash
python tool_b.py generate \
  --jsonl fixtures/fixture_global_stats_laravel.jsonl \
  --out /tmp/pattern_test.json \
  --agent mock \
  --mock-response-file fixtures/fixture_mock_agent_valid.json
```

The mock agent reads its response from `--mock-response-file` instead of calling any external CLI. No network access or API keys are required, making it suitable for offline CI pipelines and unit tests.

---

### Example 11 — Troubleshoot a failed run (exit codes 4 and 6)

If `tool_b` exits with code `4` (unparseable JSON) or `6` (schema validation failed), save the raw agent response to inspect it:

```bash
python tool_b.py generate \
  --jsonl features_raw.jsonl \
  --out pattern.json \
  --agent claude \
  --raw-response raw_response.txt
```

Examine `raw_response.txt` to understand what the agent returned. Common causes:

| Exit code | Likely cause | Suggested fix |
|---|---|---|
| `4` | Agent prefixed the JSON with prose or wrapped it in unexpected tags | Try a different `--agent-model`; use `--dry-run` to review the prompt |
| `6` | Agent produced valid JSON but violated the `pattern.json` schema | Check `raw_response.txt` for the field that failed; add `--human-notes` to guide the agent |

If you need the raw output immediately despite a validation failure, use `--skip-validation` to bypass schema checking (not recommended for production):

```bash
python tool_b.py generate \
  --jsonl features_raw.jsonl \
  --out pattern_unvalidated.json \
  --agent claude \
  --skip-validation \
  --raw-response raw_response.txt
```
