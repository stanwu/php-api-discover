# ToolB_AI_Agent_Pattern_Generator_Prompt_v1.md

You are a senior Python engineer building an AI agent orchestration tool.

---

## 工具鏈定位

```
PHP 專案
  → [ToolA v2]  → features_raw.jsonl + features_report.md
  → [人工審閱]   → 標記誤報、確認信號可信度
  → [ToolB]     → 組裝 AI agent prompt → 呼叫 AI agent CLI → 產生 pattern.json 草稿
  → [人工確認]   → 審閱並微調 pattern.json
  → [ToolC]     → postman_collection.json + endpoint_catalog.json
```

ToolB 是工具鏈的**中介轉換層**，負責：
1. 讀取 ToolA 產出的 `features_raw.jsonl`
2. 組裝精細的 AI agent prompt（內嵌 JSONL 摘要 + ToolC schema 約束）
3. 呼叫使用者選擇的 AI agent CLI（Claude / Codex / Gemini）
4. 驗證 AI 輸出是否符合 ToolC 的 `pattern.json` schema
5. 輸出最終的 `pattern.json` 草稿供人工確認後交給 ToolC

---

## Goal

Build a Python CLI tool ("tool_b") that:
- Reads `features_raw.jsonl` (ToolA v2, `schema_version: "2.0"`)
- Constructs a structured, self-contained AI agent prompt embedding JSONL evidence
- Dispatches the prompt to a user-selected AI agent CLI subprocess
- Captures, parses, and validates the AI agent's JSON output
- Writes a validated `pattern.json` ready for ToolC consumption

ToolB does **not** classify endpoints itself. It delegates all reasoning to the AI agent and acts as a **reliable orchestration shell** around that agent.

---

## Inputs

| Flag | Required | Default | Description |
|---|---|---|---|
| `--jsonl` | ✅ required | — | Path to `features_raw.jsonl` from ToolA v2 |
| `--out` | ✅ required | — | Output path for generated `pattern.json` |
| `--agent` | optional | `claude` | AI agent to use: `claude`, `codex`, `gemini` |
| `--agent-model` | optional | (agent default) | Override model name (e.g. `claude-opus-4-5`, `gpt-4o`, `gemini-2.0-flash`) |
| `--agent-timeout` | optional | `120` | Max seconds to wait for agent response |
| `--max-context-signals` | optional | `50` | Max signals to include in prompt context (top by frequency) |
| `--max-context-files` | optional | `20` | Max file records to include as examples in prompt |
| `--human-notes` | optional | — | Path to a plain-text file containing human reviewer notes to embed in prompt |
| `--dry-run` | optional flag | false | Print the assembled prompt only; do not call the agent |
| `--raw-response` | optional | — | Save raw agent response to this path before parsing |
| `--skip-validation` | optional flag | false | Skip ToolC schema validation (not recommended) |
| `--collection-name` | optional | `"API Collection"` | Sets `postman_defaults.collection_name` in pattern.json |
| `--base-url` | optional | `baseUrl` | Sets `postman_defaults.base_url_variable` |

---

## AI Agent CLI Adapters

ToolB must implement an **adapter layer** for each supported agent CLI. Each adapter translates a unified `AgentRequest` into the agent-specific subprocess call and parses the response back into a unified `AgentResponse`.

### Adapter Interface

```python
class AgentAdapter:
    def build_command(self, prompt: str, model: str | None) -> list[str]:
        """Return subprocess argv list."""

    def parse_response(self, stdout: str, stderr: str, returncode: int) -> str:
        """Extract the raw text content from agent output. Raise AgentError on failure."""
```

### Claude Adapter (`--agent claude`)

```python
# CLI call:
["claude", "--print", "--model", model or "claude-opus-4-5", "-p", prompt_text]

# Response: stdout contains the assistant's reply as plain text.
# Parse: extract first JSON code block (```json ... ```) or treat entire stdout as JSON.
# Error: non-zero returncode or empty stdout → raise AgentError.
```

Supported models (default: `claude-opus-4-5`):
- `claude-opus-4-5`
- `claude-sonnet-4-5`
- `claude-haiku-4-5`

### Codex Adapter (`--agent codex`)

```python
# CLI call:
["codex", "--model", model or "gpt-4o", "--quiet", "--full-auto",
 "--approval-policy", "auto-edit", "-p", prompt_text]

# Response: stdout contains agent response. Parse JSON block from response.
# Error: returncode != 0 or response contains no valid JSON block → raise AgentError.
```

Supported models (default: `gpt-4o`):
- `gpt-4o`
- `gpt-4o-mini`
- `o3`
- `o4-mini`

### Gemini Adapter (`--agent gemini`)

```python
# CLI call:
["gemini", "--model", model or "gemini-2.0-flash", "-p", prompt_text]

# Response: stdout is the agent's reply. Parse JSON block.
# Error: returncode != 0 or no JSON block found → raise AgentError.
```

Supported models (default: `gemini-2.0-flash`):
- `gemini-2.0-flash`
- `gemini-2.5-pro`

### Common Error Handling

All adapters must:
- Capture both `stdout` and `stderr`
- Enforce `--agent-timeout` via `subprocess.run(timeout=...)`
- On `TimeoutExpired`: print timeout error with elapsed time, exit code 3
- On `AgentError`: print stderr excerpt (max 500 chars), exit code 4
- On zero returncode but unparseable JSON: attempt retry once with a **repair prompt** (see Retry Strategy section)

---

## Prompt Assembly

This is the most critical component of ToolB. The assembled prompt must be **entirely self-contained** — the AI agent has no other context. It must contain:

1. Role and task definition
2. ToolC `pattern.json` schema (full, with field constraints)
3. JSONL global_stats summary (condensed)
4. Top signal evidence (filtered by frequency)
5. Representative file record examples
6. Human reviewer notes (if provided)
7. Output format instructions (strict JSON only)
8. Anti-hallucination rules

### Prompt Template Structure

```
[SYSTEM_BLOCK]
[TASK_BLOCK]
[TOOLC_SCHEMA_BLOCK]
[JSONL_EVIDENCE_BLOCK]
[HUMAN_NOTES_BLOCK]   ← omitted if --human-notes not provided
[RULES_BLOCK]
[OUTPUT_FORMAT_BLOCK]
```

---

### SYSTEM_BLOCK

```
You are a senior API analyst. Your task is to generate a pattern.json configuration file
for a tool called ToolC, which classifies PHP API endpoints and generates Postman collections.

You will be given structured evidence extracted from a PHP codebase by ToolA.
Your output must be a single valid JSON object conforming exactly to the schema provided.
Do not output anything other than the JSON object. No prose, no explanation, no markdown fences.
```

### TASK_BLOCK

```
## Task

Analyze the PHP codebase evidence below and produce a `pattern.json` file that:

1. Defines scoring signals (strong/weak/negative) calibrated to THIS specific codebase
2. Sets classification thresholds based on observed signal distributions
3. Defines response envelope templates based on observed envelope key patterns
4. Configures HTTP method inference rules appropriate for the detected framework
5. Provides conservative, evidence-based values — do not invent signals not present in the evidence

Framework detected: {framework}
Total files scanned: {total_files}
Candidate endpoint files: {candidate_files_above_score_30}
```

### TOOLC_SCHEMA_BLOCK

Embed the complete ToolC `pattern.json` schema with all field constraints, value ranges, and validation rules. This must be the **same schema** defined in the ToolC prompt — do not summarize or abbreviate.

```
## Target Schema: pattern.json

The output must be a JSON object with exactly these fields. Constraints are mandatory.

{
  "version": "1.0",
  "source_jsonl_schema_version": "2.0",   // MUST be exactly "2.0"
  "framework": "<detected_framework>",     // MUST match: laravel|wordpress|codeigniter|symfony|slim|plain

  "scoring": {
    "strong_signals": [
      // Each entry:
      // - name: MUST appear in signal_frequency_table or custom_helper_registry below
      // - pattern: valid Python regex matching the signal
      // - weight: integer 1–50
      // - kind: MUST be "strong"
      // Include ONLY signals with false_positive_risk "low" or "medium" AND seen_in_files >= 5
    ],
    "weak_signals": [
      // weight: integer 1–20, kind: MUST be "weak"
      // Include signals with medium/high false_positive_risk that still provide evidence
    ],
    "negative_signals": [
      // weight: integer -50 to -1 (MUST be negative), kind: MUST be "negative"
      // Include signals that strongly indicate non-API files (HTML, view rendering, etc.)
    ],
    "thresholds": {
      "endpoint": <integer>,    // Suggested: see pattern_json_generation_hints.recommended_endpoint_threshold
      "uncertain": <integer>    // MUST be strictly less than endpoint
    }
  },

  "endpoint_envelopes": {
    "templates": [
      // Base on envelope_key_frequency evidence only
      // keys_all_of: keys that ALWAYS appear together (use only keys with high co-occurrence)
      // keys_any_of: at least one of these must be present
      // example: object with ONLY keys from keys_all_of + keys_any_of as keys
      //          values: "" (string), 0 (number), true (boolean), null, {}, []
      //          DO NOT invent domain-specific field values
    ]
  },

  "method_inference": {
    "priority_order": ["route_hints", "request_method_check", "input_param_type", "signal_based", "default"],
    "rules": [
      // signal_based rules only — other sources handled automatically
      // Include rules ONLY for signals with clear method implications (e.g. wp_ajax → POST)
    ],
    "default_method": "GET"    // or "POST" — choose based on codebase evidence
  },

  "postman_defaults": {
    "collection_name": "{collection_name}",
    "base_url_variable": "{base_url_variable}",
    "auth_token_variable": "authToken",
    "default_headers": [
      { "key": "Accept", "value": "application/json", "disabled": false }
    ],
    "auth_header": {
      "key": "Authorization",
      "value_template": "Bearer {{authToken}}"
    },
    "generate_folder_per_directory": false,
    "include_pre_request_script": false,
    "include_test_script": false
  }
}
```

### JSONL_EVIDENCE_BLOCK

Assembled programmatically from `features_raw.jsonl` Line 0 (`global_stats`) plus top-N file records.

```
## Codebase Evidence (from ToolA v2 scan)

### Global Statistics

Framework: {framework.detected} (confidence: {framework.confidence})
Evidence: {framework.evidence joined as comma list}

Files scanned: {scan_summary.total_files_scanned}
Files skipped: {scan_summary.total_files_skipped}
Candidates above score 0:  {scan_summary.candidate_files_above_score_0}
Candidates above score 30: {scan_summary.candidate_files_above_score_30}
Candidates above score 60: {scan_summary.candidate_files_above_score_60}

### Signal Frequency Table (top {max_context_signals} by seen_in_files)

| Signal | Kind | Seen In Files | % of Candidates | False Positive Risk | Risk Reason |
|--------|------|---------------|-----------------|---------------------|-------------|
{rows: one per signal, sorted by seen_in_files DESC, limited to max_context_signals}

### Custom Helper Registry

{if custom_helper_registry is non-empty:}
| Helper Name | Wraps Signal | Called In Files | % of Candidates | Suggested Kind | Suggested Weight |
|-------------|--------------|-----------------|-----------------|----------------|-----------------|
{rows: read seen_called_in_files (NOT seen_in_files) from each custom_helper_registry entry}

{else: "No custom helpers detected."}

### Envelope Key Frequency (top 10)

| Key | Seen In Files | % of Candidates |
|-----|---------------|-----------------|
{rows sorted by seen_in_files DESC, max 10}

### Signal Co-occurrence Patterns

{for each co_occurrence_pattern:}
- Signals: {signals joined} | Files: {files_count} | Note: {note}

### HTTP Method Distribution

{method_distribution formatted as table}

### Score Distribution (across all candidate files with score > 0)

p25={score_distribution_summary.p25}  p50={score_distribution_summary.p50}
p75={score_distribution_summary.p75}  p90={score_distribution_summary.p90}
Note: {score_distribution_summary.note}

Use these percentiles to sanity-check threshold placement:
- A good endpoint threshold sits between p50 and p75
- A good uncertain threshold sits between p25 and p50

### Pattern.json Generation Hints (from ToolA — based on actual score distribution)

Recommended strong signals:   {recommended_strong_signals}
Recommended weak signals:     {recommended_weak_signals}
Recommended negative signals: {recommended_negative_signals}

Recommended endpoint threshold : {recommended_endpoint_threshold}
Basis: {endpoint_threshold_basis}

Recommended uncertain threshold: {recommended_uncertain_threshold}
Basis: {uncertain_threshold_basis}

Minimum required threshold gap : {minimum_threshold_gap}
Note: {minimum_threshold_gap_note}

Recommended envelope template keys_all_of: {recommended_envelope_template.keys_all_of}
Recommended envelope template keys_any_of: {recommended_envelope_template.keys_any_of}

⚠ WARNING: {pattern_json_generation_hints.warning}

### Representative File Records ({max_context_files} examples)

Selection strategy: include top-scoring files by ToolA score (diverse across score ranges).
Include at minimum: 3 L1-range files, 2 L2-range files, 1 L3-range file.

{for each selected file record, format as:}
---
File: {path}
ToolA Score: {score}
Strong signals: {signals.strong[].name + occurrences}
Weak signals:   {signals.weak[].name + occurrences}
Negative signals: {signals.negative[].name}
Route hints: {route_hints formatted as METHOD URI (source_file:source_line) [confidence]}
Input params (GET): {input_params.get[].key}
Input params (POST): {input_params.post[].key}
Input params (json_body): {input_params.json_body[].key}
Envelope keys: {envelope_keys[].key}
Method hints: {method_hints[].method via method_hints[].evidence}
Custom helpers called: {custom_helpers_called[].name}
Dynamic notes: {dynamic_notes[].note}
---
```

### HUMAN_NOTES_BLOCK (conditional)

Included only when `--human-notes` is provided:

```
## Human Reviewer Notes

The following notes were added by the human reviewer after examining features_report.md.
These notes OVERRIDE automated evidence when there is a conflict.
Treat these as authoritative corrections.

{contents of --human-notes file, verbatim, max 3000 chars}

If the notes reference signals to EXCLUDE, set their weight to 0 and omit them from the output.
If the notes reference custom threshold adjustments, apply them directly.
```

### RULES_BLOCK

```
## Generation Rules (MANDATORY)

R1. EVIDENCE-ONLY: Only include signals that appear in the Signal Frequency Table or
    Custom Helper Registry above. Do not invent signal names.

R2. WEIGHT CALIBRATION:
    - seen_in_files > 30 AND false_positive_risk=low   → weight range 25–40
    - seen_in_files 10–30 AND false_positive_risk=low  → weight range 15–25
    - seen_in_files < 10 OR false_positive_risk=medium → weight range 5–15
    - false_positive_risk=high                         → use as weak signal only (weight ≤ 10)

R3. THRESHOLD CALIBRATION:
    - Start from recommended_endpoint_threshold in generation hints
    - Adjust only if human notes specify otherwise
    - uncertain threshold MUST be < endpoint threshold
    - Minimum gap between uncertain and endpoint: 10 points

R4. ENVELOPE TEMPLATES:
    - Only create a template if at least 2 keys appear together in ≥ 10% of candidate files
    - keys_all_of must have ≥ 2 entries
    - keys_any_of must have ≥ 1 entry
    - example object values: use typed placeholders only (see schema)

R5. METHOD INFERENCE RULES:
    - Only add signal_based rules for signals with unambiguous method implications
    - WordPress wp_ajax signals → POST (always)
    - Laravel route_hints will handle most Laravel cases automatically (no signal_based rule needed)

R6. NO HALLUCINATION:
    - Do not add signals not present in the evidence
    - Do not add envelope keys not present in envelope_key_frequency
    - Do not invent HTTP method mappings not supported by evidence

R7. CONSERVATIVE DEFAULTS:
    - If uncertain about a weight, use the lower end of the range
    - If uncertain about threshold, use the JSONL hint value
    - If no clear envelope pattern, output an empty templates array []

R8. CO-OCCURRENCE DEDUPLICATION:
    - If two signals always appear together (see co-occurrence patterns), include only
      the stronger one as strong_signal; demote the other to weak or omit
```

### OUTPUT_FORMAT_BLOCK

```
## Output Format

Output ONLY a single valid JSON object. No markdown code fences. No prose before or after.
The JSON must be parseable by Python's json.loads() without any preprocessing.

The output will be machine-validated against the ToolC pattern.json schema immediately
after you respond. Validation errors will cause the process to fail.

Begin your response with { and end with }.
```

---

## Prompt Size Management

Before dispatching the prompt, ToolB must estimate token count and apply truncation if needed.

### Token Estimation

Use a simple heuristic: `estimated_tokens = len(prompt_text) / 4`

### Size Limits by Agent

| Agent | Safe Context Limit | Action if Exceeded |
|---|---|---|
| claude | 150,000 tokens | Reduce `--max-context-files` by 5, retry |
| codex | 100,000 tokens | Reduce `--max-context-files` by 5, retry |
| gemini | 800,000 tokens | No truncation needed in practice |

### Truncation Priority (reduce in this order)

1. Reduce `--max-context-files` (remove lowest-scoring file records first)
2. Reduce `--max-context-signals` (remove signals with lowest seen_in_files first)
3. Truncate `--human-notes` to 1500 chars with a truncation notice
4. If still over limit: exit with code 5 and suggest using `--max-context-files` and `--max-context-signals` flags

---

## Retry Strategy

### Scenario 1: Agent returns malformed JSON

On first parse failure, send a **repair prompt** to the same agent:

```
The following text was your previous response. It contains JSON that failed to parse.
Error: {json.JSONDecodeError message}

Your response:
---
{raw_response[:2000]}
---

Please output ONLY the corrected JSON object. No prose, no fences. Begin with { end with }.
```

Maximum 1 retry. If repair response also fails to parse → exit code 4.

### Scenario 2: Agent returns valid JSON but ToolC validation fails

On ToolC schema validation failure, send a **correction prompt**:

```
Your previous response was valid JSON but failed ToolC schema validation.
Validation errors:
{validation_errors formatted as numbered list, max 10 errors}

The original schema constraints are repeated below.
{TOOLC_SCHEMA_BLOCK repeated}

Please output a corrected JSON object addressing all validation errors.
```

Maximum 1 retry. If correction fails → save partial output with `_validation_errors` field appended, exit code 6.

### Scenario 3: Timeout

No retry on timeout. Print elapsed time and suggest increasing `--agent-timeout`. Exit code 3.

---

## Output Validation Pipeline

After receiving a parseable JSON response from the agent, ToolB runs the **same validation rules as ToolC** (V1–V10) before writing `pattern.json`.

Validation order:
1. JSON schema structure validation (jsonschema)
2. All regex patterns compile (`re.compile()`)
3. `thresholds.uncertain < thresholds.endpoint`
4. Negative signal weights are negative integers
5. Positive signal weights are positive integers
6. Each signal name exists in JSONL `signal_frequency_table` or `custom_helper_registry`
7. `envelope.example` keys are subset of `keys_all_of + keys_any_of`
8. `framework` matches JSONL `global_stats.framework.detected` (warning only)
9. Template names are unique
10. `priority_order` ends with `"default"`

On failures:
- Hard errors (V1–V7, V9–V10): trigger correction retry (Scenario 2)
- Warnings (V8): log and continue

After successful validation, append a `_tool_b_meta` field to pattern.json:

```json
"_tool_b_meta": {
  "generated_by": "tool_b",
  "tool_b_version": "1.0",
  "agent": "claude",
  "agent_model": "claude-opus-4-5",
  "generated_at": "2025-03-01T10:00:00Z",
  "source_jsonl": "features_raw.jsonl",
  "jsonl_schema_version": "2.0",
  "context_signals_used": 42,
  "context_files_used": 20,
  "human_notes_provided": true,
  "validation_passed": true,
  "retry_count": 0,
  "prompt_estimated_tokens": 12400
}
```

Note: ToolC must ignore `_tool_b_meta` during validation (treat as optional extension field).

---

## Outputs

### Primary: `pattern.json`

A validated `pattern.json` ready for ToolC. Written only after full validation passes.

File includes `_tool_b_meta` block for auditability.

### Optional: `--raw-response` file

The unprocessed raw text response from the agent, saved before any parsing or validation. Useful for debugging agent failures.

### `--dry-run` Console Output

```
=== ToolB Dry Run ===
Agent              : claude (claude-opus-4-5)
JSONL              : features_raw.jsonl
JSONL schema       : 2.0 ✓
Framework (JSONL)  : laravel (confidence: high)
Output             : pattern.json (not written — dry run)

Context assembled:
  Signals in prompt  : 42 (max: 50)
  File records       : 20 (max: 20)
  Human notes        : yes (847 chars)
  Estimated tokens   : ~12,400 (within claude limit of 150,000) ✓

Prompt preview (first 500 chars):
---
You are a senior API analyst. Your task is to generate a pattern.json...
---

Full prompt would be written to stdout with --dry-run --verbose
Agent would NOT be called. Remove --dry-run to execute.
```

---

## CLI Usage

```bash
# Basic usage (Claude, default model)
python tool_b.py generate \
  --jsonl features_raw.jsonl \
  --out pattern.json

# With human reviewer notes
python tool_b.py generate \
  --jsonl features_raw.jsonl \
  --out pattern.json \
  --human-notes reviewer_notes.txt

# Use Gemini with specific model
python tool_b.py generate \
  --jsonl features_raw.jsonl \
  --out pattern.json \
  --agent gemini \
  --agent-model gemini-2.5-pro

# Use Codex, save raw response, increase timeout
python tool_b.py generate \
  --jsonl features_raw.jsonl \
  --out pattern.json \
  --agent codex \
  --agent-model gpt-4o \
  --agent-timeout 180 \
  --raw-response raw_codex_response.txt

# Dry run — print assembled prompt only
python tool_b.py generate \
  --jsonl features_raw.jsonl \
  --out pattern.json \
  --dry-run

# Control context size for large codebases
python tool_b.py generate \
  --jsonl features_raw.jsonl \
  --out pattern.json \
  --max-context-signals 30 \
  --max-context-files 10

# Skip validation (debugging only)
python tool_b.py generate \
  --jsonl features_raw.jsonl \
  --out pattern.json \
  --skip-validation

# Check which agents are available (CLI availability check)
python tool_b.py check-agents
```

### `check-agents` Output

```
=== ToolB Agent Availability Check ===
claude  : ✓ available (claude --version → claude/1.0.3)
codex   : ✓ available (codex --version → codex/0.2.1)
gemini  : ✗ not found (gemini not in PATH)
```

---

## Module Architecture

```
toolchain/
├── toolchain_validator.py  # SHARED module (used by both ToolB and ToolC)
│                           # Implements V1–V12 pattern.json validation rules
│                           # Entry point: validate_pattern_json(pattern, global_stats) -> ValidationResult
│                           # Strips _-prefixed extension fields before validation (V11)
│
tool_b/
├── tool_b.py               # CLI entry point (argparse/typer)
├── jsonl_reader.py         # Reads and validates features_raw.jsonl; extracts global_stats + top file records
├── prompt_assembler.py     # Builds the full prompt from template blocks + JSONL evidence
├── context_selector.py     # Selects top-N signals and file records for prompt context; handles truncation
├── agents/
│   ├── base.py             # AgentAdapter abstract base class
│   ├── claude.py           # Claude CLI adapter
│   ├── codex.py            # Codex CLI adapter
│   └── gemini.py           # Gemini CLI adapter
├── agent_runner.py         # Dispatches to selected adapter; handles timeout + retry
├── response_parser.py      # Extracts JSON from agent stdout; handles fenced + unfenced responses
└── output_writer.py        # Writes pattern.json with _tool_b_meta appended; calls toolchain_validator
```

---

## Implementation Notes

- **Agent CLI availability check**: at startup (before reading JSONL), verify that the selected agent CLI is in `$PATH` using `shutil.which()`. If not found → exit code 7 with instructions.
- **Subprocess security**: never pass user-provided content directly into shell string interpolation. Always use `subprocess.run(argv_list, ...)` with a list, not `shell=True`.
- **Prompt file**: save the assembled prompt to a temp file before dispatching (for debuggability). Delete on success unless `--dry-run` or `--raw-response` is set.
- **JSON extraction**: agent responses may wrap JSON in markdown fences (` ```json ... ``` `). Strip fences before `json.loads()`. If multiple JSON blocks are found, use the largest one.
- **Deterministic context selection**: file record selection for prompt context must be deterministic (sort by `score DESC`, then `path ASC`). Same JSONL always produces the same prompt.
- **`_tool_b_meta` preservation**: if the user later re-runs ToolB and overwrites `pattern.json`, the new `_tool_b_meta` replaces the old one entirely. Do not merge or accumulate.

---

## Exit Codes

| Code | Meaning |
|---|---|
| 0 | Success — `pattern.json` written and validated |
| 1 | `pattern.json` schema validation failed after all retries |
| 2 | JSONL schema version mismatch (not `"2.0"`) |
| 3 | Agent subprocess timeout |
| 4 | Agent returned unparseable response after retry |
| 5 | Prompt exceeds agent context limit even after truncation |
| 6 | Partial output written — validation errors remain (use `--skip-validation` to force) |
| 7 | Selected agent CLI not found in PATH |
| 8 | JSONL file not found or unreadable |

---

## Test Plan

Provide `test_plan.md` and `fixtures/` directory:

### Fixture Files

| Fixture | Purpose |
|---|---|
| `fixture_global_stats_laravel.jsonl` | Valid Line 0 global_stats for Laravel project |
| `fixture_global_stats_wordpress.jsonl` | Valid Line 0 global_stats for WordPress project |
| `fixture_file_records_laravel.jsonl` | 5 file records: 3 L1-range, 1 L2-range, 1 L3-range |
| `fixture_mock_agent_valid.json` | A valid pattern.json the mock agent would return |
| `fixture_mock_agent_malformed.txt` | Malformed JSON (triggers repair retry) |
| `fixture_mock_agent_invalid_schema.json` | Valid JSON but fails ToolC validation (triggers correction retry) |
| `fixture_human_notes.txt` | Sample human reviewer notes |

### Mock Agent for Testing

Implement a `--agent mock` option (test-only) that reads response from `--mock-response-file` instead of calling a real CLI. This allows deterministic testing without AI API calls:

```bash
python tool_b.py generate \
  --jsonl fixtures/fixture_global_stats_laravel.jsonl \
  --out test_pattern.json \
  --agent mock \
  --mock-response-file fixtures/fixture_mock_agent_valid.json
```

### Sanity Test Assertions (`test_sanity.py`)

- JSONL schema `"1.0"` → exit code 2
- Agent not in PATH → exit code 7
- Mock agent returns malformed JSON → repair retry triggered → exit code 4
- Mock agent returns valid response → `pattern.json` written → validation passes
- `pattern.json` contains `_tool_b_meta` with correct agent name
- `thresholds.uncertain < thresholds.endpoint` in output
- All signal names in output exist in JSONL global_stats signal_frequency_table
- `--dry-run` → no `pattern.json` written, exit code 0
- `check-agents` subcommand → prints availability table, exit code 0

---

## Non-Goals

- Do NOT classify endpoints directly — delegate all reasoning to the AI agent
- Do NOT re-scan PHP source files
- Do NOT require network access beyond what the agent CLI itself uses
- Do NOT implement agent API calls directly (use agent CLI subprocess only)
- Do NOT store agent API keys — leave credential management to the agent CLI

---

## Quality Bar

- **Prompt determinism**: same JSONL + same flags always produces the same assembled prompt (deterministic context selection).
- **Validation parity**: ToolB uses the shared `toolchain_validator.py` module (V1–V12) — identical to what ToolC uses. Any future rule change in V1–V12 automatically applies to both tools. Do not maintain a separate copy of validation logic in ToolB.
- **V11 awareness**: ToolB must be aware that `_tool_b_meta` is an extension field. Before calling `toolchain_validator`, ToolB must confirm its own output will pass V11 (extension fields silently ignored) and not accidentally trigger V6 (envelope key constraints). The `_tool_b_meta` block must be appended **after** validation, never before.
- **V12 awareness**: ToolB must enforce the `minimum_threshold_gap` constraint (from JSONL) in its correction prompt (Scenario 2 retry) when the AI agent produces a threshold gap violation.
- **Auditability**: every generated `pattern.json` must contain `_tool_b_meta` so any downstream issue can be traced back to which agent, which model, which JSONL, and how many retries were needed.
- **Fail loudly**: prefer explicit exit codes over silent failures. Never write a `pattern.json` that has not passed full validation (unless `--skip-validation` is explicitly set).
- **Agent agnosticism**: adding a new agent should require only adding a new file under `agents/` and registering it in the CLI — no changes to any other module.

---

Now produce the full Python implementation, embedded README, and test plan.
