# ToolA_Feature_Extractor_Prompt_v2.md

You are a senior Python engineer building a codebase analysis utility.

---

## Goal

Build a Python CLI tool ("tool_a") that scans a PHP project directory and produces:
1. A human-reviewable feature extraction report (Markdown)
2. Optional machine-readable raw features (JSONL)

This tool must **NOT** attempt to fully classify endpoints. It only collects evidence and statistics to help a human (or another AI) author a rules file later.

---

## Primary Use Case

I own the PHP codebase and it has consistent patterns. I want to discover common API/JSON-output fingerprints across the project and generate a report that makes those patterns obvious and reviewable.

---

## Framework-Aware Detection (NEW)

The tool must **auto-detect** the PHP framework in use before scanning, and load the corresponding signal profile. Detection is based on file/directory fingerprints:

| Framework | Detection Heuristic |
|---|---|
| Laravel | `artisan` file + `app/Http/Controllers/` directory |
| WordPress | `wp-config.php` or `wp-includes/` directory |
| CodeIgniter | `system/core/CodeIgniter.php` or `application/` directory |
| Symfony | `symfony.lock` or `src/Kernel.php` |
| Slim / Lumen | `composer.json` contains `"slim/slim"` or `"laravel/lumen-framework"` |
| Plain PHP | fallback if none of the above |

### Framework-Specific Signal Tables

Each framework has its own strong/weak/negative signal sets:

#### Laravel
- **Strong**: `response()->json(`, `return response()->json(`, `JsonResource`, `->toResponse(`, `Route::` (in `routes/api.php` only)
- **Weak**: `json_encode(`, `Illuminate\Http\JsonResponse`
- **Negative**: `return view(`, `->render(`, `Blade::`
- **Note**: Route definitions live in `routes/api.php` and `routes/web.php`; the scanner **must** parse these files to map controller methods to paths.

#### WordPress
- **Strong**: `wp_send_json(`, `wp_send_json_success(`, `wp_send_json_error(`, `add_action('wp_ajax_`
- **Weak**: `json_encode(`, `wp_die(`
- **Negative**: `get_template_part(`, `load_template(`, `echo get_header(`

#### CodeIgniter
- **Strong**: `$this->output->set_content_type('application/json')`, `$this->response(` (CI4)
- **Weak**: `json_encode(`, `$this->input->post(`
- **Negative**: `$this->load->view(`

#### Symfony
- **Strong**: `new JsonResponse(`, `$this->json(`, `JsonResponse::HTTP_`
- **Weak**: `json_encode(`, `Request $request`
- **Negative**: `$this->render(`, `$this->renderView(`

#### Plain PHP (fallback)
- **Strong**: `header('Content-Type: application/json')`, `header("Content-Type: application/json")`, `die(json_encode(`, `exit(json_encode(`
- **Weak**: `json_encode(`, `$_SERVER['HTTP_ACCEPT']`
- **Negative**: `<html`, `include.*header`, `include.*footer`, `echo.*<div`

---

## Inputs

- Root path of a PHP project (local folder).
- Optional exclude directories (default: `vendor`, `node_modules`, `storage`, `cache`, `logs`, `tmp`, `.git`).
- Optional include extensions (default: `.php`; optionally support `.inc`, `.phtml`).
- Optional max snippet lines and max files scanned.
- Optional max file size to scan (default: 3 MB; skip and log larger files).
- Optional `--framework` flag to force a specific framework profile (skip auto-detection).

---

## Dynamic PHP Pattern Handling (NEW)

Static regex analysis misses dynamic PHP patterns. The tool must include a **Dynamic Pattern Detector** module with the following capabilities:

### 1. Variable Function Calls
Detect cases where the function name is in a variable:
```php
$func = 'json_encode';
echo $func($data);
```
Strategy: When a variable is assigned a known JSON-output function name as a string literal, flag the subsequent call site as a **weak signal** with a note: `"Possible dynamic dispatch of json_encode via $func"`.

### 2. String-Concatenated Headers
Detect headers built via concatenation:
```php
$ct = 'application/' . 'json';
header('Content-Type: ' . $ct);
```
Strategy: Flag `header(` calls whose argument contains string concatenation as **weak candidates** and include the full line in the snippet with a note: `"Concatenated header — manual review required"`.

### 3. Aliased or Wrapped Helpers
Detect custom wrapper function definitions that internally call known JSON signals:
```php
function apiResponse($data) { echo json_encode($data); exit; }
```
Strategy: During a first-pass scan of the entire codebase, build a **custom helper registry**: any user-defined function that contains a strong signal in its body is recorded. In the main scan pass, calls to these registered helpers are treated as **strong signals**.

### 4. Indirection Limits
If more than 2 levels of indirection are detected (e.g., helper calls helper calls json_encode), record the pattern as a **note** in the report without escalating the score, to avoid false positives.

---

## Route Mapping (NEW — replaces file-path-only inference)

For frameworks with centralized routing, file path alone is insufficient. The tool must include a **Route Mapper** module:

### Laravel
- Parse `routes/api.php` and `routes/web.php` using regex to extract:
  - HTTP method (`GET`, `POST`, etc.)
  - URI pattern (e.g., `/api/users/{id}`)
  - Controller and method reference (e.g., `UserController@index`)
- Link each detected signal back to its route entry in the report.
- If no route entry is found for a controller file, label it `"No route mapping found — file path used as fallback"`.

### WordPress
- Parse `add_action('wp_ajax_<action>', ...)` and `add_action('wp_ajax_nopriv_<action>', ...)` calls.
- Map action name → handler function/method.

### Plain PHP
- Use file path as-is (existing behavior), with an explicit note in the report: `"No route parser available for Plain PHP — path is inferred from file location"`.

### Output
Add a `route_hints` field to each file entry in both the Markdown report and JSONL output.
**Format must be consistent with the JSONL file record schema** — use split fields, not a combined string:

```json
"route_hints": [
  {
    "method": "POST",
    "uri": "/api/users",
    "source_file": "routes/api.php",
    "source_line": 14,
    "confidence": "high"
  }
]
```

Field definitions:
- `method`: HTTP verb in uppercase (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`)
- `uri`: URI pattern as declared in the route file (e.g. `/api/users/{id}`)
- `source_file`: relative path to the route definition file
- `source_line`: line number of the route declaration
- `confidence`: `"high"` if parsed from explicit route file; `"low"` if inferred from file path only

---

## Secret Redaction — Explicit Rules (NEW)

The redactor module must apply the following concrete patterns (in order). Redact the **value only**; preserve the key name.

| Pattern Type | Regex (example) | Replacement |
|---|---|---|
| Assignment with quoted value | `(api_?key\|token\|secret\|password\|passwd\|auth)\s*[=:]\s*['"][^'"]{8,}['"]` | `key = "REDACTED"` |
| Long alphanumeric strings (≥32 chars) | `['"][A-Za-z0-9+/=_\-]{32,}['"]` | `"REDACTED"` |
| Bearer / Authorization headers | `Bearer\s+[A-Za-z0-9\-._~+/]+=*` | `Bearer REDACTED` |
| `.env`-style values in code | `getenv\(['"][^'"]+['"]\)` | preserve as-is (not redacted, but flagged as `"env-sourced secret — safe"`) |

If a pattern matches inside a snippet, the entire matched value is replaced with `REDACTED` before writing to the report or JSONL.

---

## Outputs

### 1. `features_report.md`

A structured Markdown report containing:

**Summary Section**
- Detected framework (with confidence note)
- Total files scanned / skipped (with skip reasons)
- Top directories by PHP file count
- Top detected signals and their frequencies
- Top candidate endpoint files by heuristic score
- Custom helper registry discovered (if any)

**Per-File Section** (for files above a minimum score threshold, default score ≥ 10)
- File path
- Heuristic score (0–100) with **full scoring breakdown** (each added/subtracted point listed)
- Matched signals (Strong / Weak / Negative)
- Dynamic pattern notes (variable dispatch, concatenated headers, etc.)
- Route hints (from Route Mapper, or fallback note)
- Extracted parameter hints:
  - Keys from `$_GET['key']`, `$_POST['key']`, `$_REQUEST['key']`
  - JSON body keys from `$body['key']`, `$data['key']`, `$input['key']`
- Output envelope hints (common response keys: `ok`, `success`, `code`, `message`, `data`, `result`, `error`)
- Bounded code snippets (±N lines around each output point, max 80 lines per file total)
- Redaction notices (how many values were redacted in this file)

### 2. `features_raw.jsonl` (optional, via `--raw` flag)

#### 設計原則：為 Claude Code 下游消費而設計

`features_raw.jsonl` 的主要下游消費者是 **Claude Code**，負責將掃描結果轉換成 `pattern.json`。因此 JSONL 的欄位設計必須滿足以下條件：

- **信號必須附帶可靠度指標**：Claude Code 需要知道一個信號是「整個專案普遍存在」還是「只出現一次」，才能判斷合理的 `weight` 值。
- **全域統計必須獨立輸出**：Claude Code 在生成 pattern.json 前需要先理解整個專案的信號分佈，不能只看單檔資料。
- **欄位語意必須自描述**：Claude Code 不會讀取本規格書，所有欄位必須讓 LLM 能從欄位名稱和值的結構直接理解意義。

---

#### 第 0 行：全域統計 Header（`record_type: "global_stats"`）

JSONL 的**第一行**固定輸出全域統計物件，供 Claude Code 在逐行讀取前先建立全域上下文。

```json
{
  "record_type": "global_stats",
  "schema_version": "2.0",
  "generated_at": "2025-03-01T10:00:00Z",
  "framework": {
    "detected": "laravel",
    "confidence": "high",
    "evidence": ["artisan file found", "app/Http/Controllers/ directory found"]
  },
  "scan_summary": {
    "total_files_scanned": 320,
    "total_files_skipped": 5,
    "skip_reasons": {
      "too_large": 3,
      "encoding_error": 2
    },
    "candidate_files_above_score_0": 89,
    "candidate_files_above_score_30": 42,
    "candidate_files_above_score_60": 18
  },
  "signal_frequency_table": [
    {
      "signal": "response()->json(",
      "kind": "strong",
      "seen_in_files": 42,
      "pct_of_candidates": 47.2,
      "false_positive_risk": "low",
      "false_positive_risk_reason": "Framework-native JSON helper; rarely appears in non-API files"
    },
    {
      "signal": "json_encode(",
      "kind": "weak",
      "seen_in_files": 87,
      "pct_of_candidates": 97.8,
      "false_positive_risk": "medium",
      "false_positive_risk_reason": "Appears in both API and non-API files; always co-check for negative signals"
    },
    {
      "signal": "return view(",
      "kind": "negative",
      "seen_in_files": 120,
      "pct_of_candidates": 37.5,
      "false_positive_risk": "n/a"
    }
  ],
  "custom_helper_registry": [
    {
      "helper_name": "apiResponse",
      "defined_in": "app/Helpers/ApiHelper.php:12",
      "wraps_signal": "json_encode(",
      "wrap_depth": 1,
      "seen_called_in_files": 15,
      "pct_of_candidates": 16.9,
      "suggested_kind": "strong",
      "suggested_weight_hint": 20
    },
    {
      "helper_name": "returnError",
      "defined_in": "app/Helpers/ApiHelper.php:28",
      "wraps_signal": "response()->json(",
      "wrap_depth": 1,
      "seen_called_in_files": 8,
      "pct_of_candidates": 9.0,
      "suggested_kind": "strong",
      "suggested_weight_hint": 20
    }
  ],
  "envelope_key_frequency": [
    { "key": "success", "seen_in_files": 38, "pct_of_candidates": 42.7 },
    { "key": "data",    "seen_in_files": 35, "pct_of_candidates": 39.3 },
    { "key": "message", "seen_in_files": 30, "pct_of_candidates": 33.7 },
    { "key": "code",    "seen_in_files": 22, "pct_of_candidates": 24.7 },
    { "key": "error",   "seen_in_files": 18, "pct_of_candidates": 20.2 }
  ],
  "method_distribution": {
    "POST": 31,
    "GET": 24,
    "PUT": 5,
    "DELETE": 3,
    "unknown": 26
  },
  "co_occurrence_patterns": [
    {
      "signals": ["response()->json(", "json_encode("],
      "files_count": 38,
      "note": "These two signals always appear together in this codebase; treat json_encode as redundant when response()->json( is present"
    },
    {
      "signals": ["return view(", "response()->json("],
      "files_count": 7,
      "note": "Mixed files: controller has both API and web methods; score must reflect per-method analysis, not per-file"
    }
  ],
  "pattern_json_generation_hints": {
    "recommended_strong_signals": ["response()->json(", "apiResponse", "returnError"],
    "recommended_weak_signals": ["json_encode("],
    "recommended_negative_signals": ["return view(", "Blade::"],
    "recommended_endpoint_threshold": 30,
    "endpoint_threshold_basis": "Files with at least one strong signal cluster at score >= 30; threshold set at the lower edge of this cluster",
    "recommended_uncertain_threshold": 15,
    "uncertain_threshold_basis": "Files with only weak signals and no strong signals cluster at score 8-18; threshold set above this cluster at the point where false-positive rate drops below 20%",
    "minimum_threshold_gap": 10,
    "minimum_threshold_gap_note": "ToolB and ToolC both enforce: (endpoint_threshold - uncertain_threshold) >= minimum_threshold_gap. Do not adjust recommended values in a way that violates this gap.",
    "score_distribution_summary": {
      "p25": 5,
      "p50": 18,
      "p75": 42,
      "p90": 68,
      "note": "Percentiles of ToolA heuristic scores across all candidate files (score > 0). Use to sanity-check threshold placement."
    },
    "recommended_envelope_template": {
      "keys_all_of": ["success", "data"],
      "keys_any_of": ["message", "code", "error"]
    },
    "warning": "These are suggestions derived from signal frequency and score distribution only. Human review is required before using as final pattern.json values."
  }
}
```

---

#### 第 1–N 行：逐檔記錄（`record_type: "file"`）

每個 PHP 檔案一行，欄位設計強調**每個信號都附帶可靠度上下文**：

```json
{
  "record_type": "file",
  "schema_version": "2.0",
  "path": "app/Http/Controllers/UserController.php",
  "framework": "laravel",
  "score": 75,
  "score_breakdown": [
    { "signal": "response()->json(", "kind": "strong", "delta": 30, "line_no": 58 },
    { "signal": "json_encode(",      "kind": "weak",   "delta": 10, "line_no": 72 },
    { "signal": "return view(",      "kind": "negative","delta": -10,"line_no": 91 }
  ],
  "signals": {
    "strong": [
      {
        "name": "response()->json(",
        "occurrences": 2,
        "line_nos": [58, 63],
        "global_seen_in_files": 42,
        "false_positive_risk": "low"
      }
    ],
    "weak": [
      {
        "name": "json_encode(",
        "occurrences": 1,
        "line_nos": [72],
        "global_seen_in_files": 87,
        "false_positive_risk": "medium"
      }
    ],
    "negative": [
      {
        "name": "return view(",
        "occurrences": 1,
        "line_nos": [91],
        "global_seen_in_files": 120
      }
    ]
  },
  "dynamic_notes": [
    {
      "type": "concatenated_header",
      "line_no": 42,
      "note": "Concatenated header — manual review required",
      "raw_line": "header('Content-Type: ' . $ct);"
    }
  ],
  "route_hints": [
    {
      "method": "POST",
      "uri": "/api/users",
      "source_file": "routes/api.php",
      "source_line": 14,
      "confidence": "high"
    },
    {
      "method": "GET",
      "uri": "/api/users/{id}",
      "source_file": "routes/api.php",
      "source_line": 15,
      "confidence": "high"
    }
  ],
  "input_params": {
    "get":       [{ "key": "id",      "line_no": 22 }, { "key": "page", "line_no": 23 }],
    "post":      [{ "key": "name",    "line_no": 45 }, { "key": "email","line_no": 46 }],
    "request":   [],
    "json_body": [{ "key": "user_id", "line_no": 60 }, { "key": "role", "line_no": 61 }]
  },
  "method_hints": [
    { "method": "POST", "evidence": "$_SERVER['REQUEST_METHOD'] === 'POST'", "line_no": 30 },
    { "method": "GET",  "evidence": "route_hints", "line_no": null }
  ],
  "envelope_keys": [
    { "key": "success", "line_no": 59 },
    { "key": "data",    "line_no": 59 },
    { "key": "message", "line_no": 63 }
  ],
  "output_points": [
    {
      "kind": "response()->json(",
      "line_no": 58,
      "context_excerpt": "return response()->json(['success' => true, 'data' => $user]);"
    }
  ],
  "custom_helpers_called": [
    { "name": "apiResponse", "line_no": 80, "resolved_to": "json_encode(", "wrap_depth": 1 }
  ],
  "redaction_count": 2,
  "skipped": false,
  "skip_reason": null,
  "encoding_note": null,
  "notes": []
}
```

---

#### 末行：跳過檔案摘要（`record_type: "skipped_files_summary"`）

```json
{
  "record_type": "skipped_files_summary",
  "skipped_files": [
    { "path": "app/Legacy/OldBigFile.php", "reason": "too_large", "size_mb": 8.2 },
    { "path": "app/Legacy/Broken.php",     "reason": "encoding_error", "encoding_detected": "windows-1252" }
  ]
}
```

---

## Scoring Model

Scoring is **framework-aware** and **explainable**. Every delta must be logged.

### Base Weights (adjust per framework profile)

| Signal | Points |
|---|---|
| `application/json` Content-Type header (literal) | +35 |
| Framework JSON helper (e.g., `response()->json(`, `wp_send_json(`) | +30 |
| `die(json_encode(` / `exit(json_encode(` | +25 |
| Custom helper from registry (wraps strong signal) | +20 |
| Lone `json_encode(` | +10 |
| Concatenated header (dynamic, unresolvable) | +5 |
| `<html` literal | −20 |
| `return view(` / `$this->load->view(` / `Blade::` | −15 |
| `include.*header\.php` / `include.*footer\.php` | −10 |
| `echo.*<[a-zA-Z]` (HTML tags in echo) | −5 |

Score is clamped to [0, 100].

---

## CLI Requirements

```bash
# Basic scan
python tool_a.py scan --root /path/to/project --out features_report.md

# With raw JSONL output
python tool_a.py scan --root . --out features_report.md --raw features_raw.jsonl

# Force framework profile
python tool_a.py scan --root . --framework laravel --out features_report.md

# Limit scope
python tool_a.py scan --root . --exclude vendor node_modules storage --max-files 20000 --max-file-size 3

# Show only high-confidence files
python tool_a.py scan --root . --min-score 30 --out features_report.md
```

All arguments:

| Flag | Default | Description |
|---|---|---|
| `--root` | required | PHP project root |
| `--out` | `features_report.md` | Markdown output path |
| `--raw` | (disabled) | JSONL output path |
| `--exclude` | vendor node_modules storage cache logs tmp .git | Directories to skip |
| `--ext` | .php | File extensions to scan |
| `--max-files` | unlimited | Max files to scan |
| `--max-file-size` | 3 | Max file size in MB |
| `--max-snippet-lines` | 80 | Max snippet lines per file |
| `--min-score` | 0 | Only report files at or above this score |
| `--framework` | (auto-detect) | Force framework: laravel, wordpress, codeigniter, symfony, slim, plain |

---

## Module Architecture

```
tool_a/
├── tool_a.py              # CLI entry point (argparse/typer)
├── framework_detector.py  # Auto-detects PHP framework
├── scanner.py             # Filesystem walker (streaming, memory-safe)
├── detector.py            # Signal detection (regex + dynamic pattern handler)
├── route_mapper.py        # Parses route files per framework
├── helper_registry.py     # First-pass custom helper discovery
├── redactor.py            # Secret masking with explicit rules
├── scorer.py              # Framework-aware scoring with breakdown log
├── reporter.py            # Markdown writer
└── serializer.py          # JSONL writer（global_stats header → file records → skipped_files_summary 三段式輸出）
```

---

## Implementation Notes

- **Two-pass scanning**: Pass 1 walks all PHP files to build the `helper_registry` 並統計全域信號頻率表。Pass 2 performs full detection using the registry.
- **JSONL 三段式輸出順序**：第 0 行 `global_stats`（含 `pattern_json_generation_hints`）→ 第 1–N 行逐檔 `file` 記錄 → 末行 `skipped_files_summary`。Claude Code 讀取時應先讀第 0 行建立全域上下文，再逐行處理 file 記錄。
- `schema_version` 欄位固定為 `"2.0"`，供下游工具版本驗證。
- Stream files one at a time; never load the entire repo into memory.
- Skip files exceeding `--max-file-size` and log them as `"SKIPPED: file too large"` in the summary.
- Use `chardet` or fallback encoding (`latin-1`) for files that fail UTF-8 decoding; log encoding issues per file.
- All regex patterns must be compiled at startup (not per-file) for performance.
- Route mapper must be run once before the main scan loop and its output cached in memory.

---

## Test Plan

Provide a `test_plan.md` and a `fixtures/` directory with:

1. **fixture_laravel_api_controller.php** — Laravel controller returning `response()->json()`, one `return view()` method, and one `return response()->download()` method. Expected score: 50–70.
2. **fixture_wordpress_ajax.php** — WordPress AJAX handler using `wp_send_json_success()`. Expected score: 70–90.
3. **fixture_plain_ui_page.php** — Plain PHP page with `<html>`, `include 'header.php'`, `echo "<div>"`. Expected score: 0–5.
4. **fixture_dynamic_dispatch.php** — Variable function call `$func = 'json_encode'; echo $func($data);`. Expected: weak signal flagged, note present in report.
5. **fixture_secrets.php** — File containing `$api_key = 'abc123xyz456def789ghi012jkl345mn';`. Expected: value redacted, key preserved, redaction count = 1.

Run `python test_sanity.py` and assert:
- No crash on any fixture
- Score ranges match expectations
- Redaction count matches for secrets fixture
- JSONL 第 0 行的 `record_type` 為 `"global_stats"`，且 `schema_version` 為 `"2.0"`
- JSONL 每個 `file` 記錄的 `signals.strong` 每個元素均含 `global_seen_in_files` 欄位
- `global_stats.pattern_json_generation_hints` 欄位存在且非空
- JSONL 末行的 `record_type` 為 `"skipped_files_summary"`
- 每行 JSONL 均為合法 JSON（`json.loads()` 不拋出例外）

---

## Non-Goals

- Do NOT generate Postman collections.
- Do NOT resolve dynamic includes or `require` chains beyond one level.
- Do NOT require internet access.
- Do NOT auto-classify endpoints into categories (that is the human's job after reviewing this report).

---

## Quality Bar

- Deterministic output (same input → same output, no randomness).
- Clear, human-auditable scoring breakdown.
- Conservative redaction (prefer over-redacting to under-redacting).
- Dynamic pattern flags must be clearly labeled as requiring manual review.
- Framework detection must print its confidence basis in the report header (e.g., `"Detected: Laravel — found artisan file and app/Http/Controllers/ directory"`).
- **Anti-hallucination rule**: the tool must only report signals that are literally present in the source text. No inferred or assumed patterns.

---

Now produce the full Python implementation and minimal documentation.
