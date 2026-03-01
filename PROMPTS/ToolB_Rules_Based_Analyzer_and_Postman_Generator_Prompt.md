# ToolB_Rules_Based_Analyzer_and_Postman_Generator_Prompt.md

You are a senior Python engineer building a rules-based API endpoint analyzer and Postman collection generator.

Goal
Build a Python CLI tool ("tool_b") that reads:
1) a PHP project directory
2) a user-authored rules file (pattern.json)
and then:
- classifies which PHP files are likely API endpoints (JSON output)
- extracts request parameter hints (query/form/json-body)
- infers an HTTP method when possible (GET/POST/etc.)
- generates a Postman Collection v2.1 JSON file that can be imported directly into Postman

Key Idea
This is NOT a generic PHP analyzer. The rules file encodes my codebase’s common patterns discovered via Tool A. Tool B must strictly follow pattern.json and remain conservative when uncertain.

Inputs
- Project root path
- pattern.json (rules)
- Optional baseUrl value (or default to Postman variable {{baseUrl}})
- Optional auth configuration (or default to Postman variable {{authToken}})

Outputs
1) postman_collection.json (Postman Collection v2.1)
- One item per endpoint (or per endpoint above threshold)
- Each item includes:
  - name (e.g., "GET /relative/path.php" or "POST /api/orders.php")
  - request:
    - method
    - headers (Accept: application/json; Content-Type for JSON bodies)
    - url using variables: {{baseUrl}} + relative path
    - query params (if extracted)
    - body (if inferred for POST/PUT): raw JSON skeleton or form-encoded depending on rules
  - (Optional but useful) example responses:
    - If the tool can infer an envelope template from pattern.json, include a sample response body (do not invent fields; only include template keys defined by rules)

2) endpoint_catalog.json (optional)
- A structured report of:
  - file path
  - endpoint_score
  - matched rules/signals
  - inferred method
  - extracted params
  - confidence tier (e.g., L1 candidate, L2 likely endpoint)

pattern.json Schema (Design and Validation)
Tool B must define and validate a schema for pattern.json. If invalid, fail with a clear error.
Suggested schema structure (you may refine but must keep it stable and documented):

- version: string
- exclude_paths: [string]
- include_extensions: [string]
- scoring:
  - strong_signals: [{ name, pattern, weight, kind }]
  - weak_signals:   [{ name, pattern, weight, kind }]
  - negative_signals:[{ name, pattern, weight, kind }]
  - thresholds:
      endpoint: number
      uncertain: number
- endpoint_envelopes:
  - templates: [
      { name, keys_all_of: [string], keys_any_of:[string], example: object }
    ]
- input_extractors:
  - get_keys_regex: string
  - post_keys_regex: string
  - request_keys_regex: string
  - json_body_keys_regex: string
- method_inference:
  - rules: [
      { if_any_signal: [string], method: "GET|POST|PUT|DELETE|PATCH" }
    ]
  - default_method: "GET"
- postman_defaults:
  - collection_name: string
  - base_url_variable: string (default "baseUrl")
  - auth_token_variable: string (default "authToken")
  - default_headers: [{key, value}]
  - auth_header: { key: "Authorization", value_template: "Bearer {{authToken}}" }
  - content_type_json: "application/json"
  - accept_json: "application/json"

Important Behavior Rules
- Conservative classification:
  - If score >= thresholds.endpoint -> endpoint
  - If thresholds.uncertain <= score < thresholds.endpoint -> uncertain (include only if --include-uncertain is set)
  - If score < thresholds.uncertain -> ignore
- No hallucination:
  - Only infer parameters from code matches (regex/AST-lite), or from explicit templates in pattern.json.
  - If no params found, leave params empty rather than inventing.
- Output determinism:
  - Sorting of items must be stable (e.g., by path).
- Safety redaction:
  - Never output detected secrets in Postman examples. If any secret-like literals are detected, replace with "REDACTED".

CLI Requirements
- Use argparse or typer.
- Example usage:
  - python tool_b.py generate --root /path/to/project --rules pattern.json --out postman_collection.json
  - python tool_b.py generate --root . --rules pattern.json --out postman_collection.json --catalog endpoint_catalog.json
  - python tool_b.py generate --root . --rules pattern.json --out postman_collection.json --include-uncertain
  - python tool_b.py dry-run --root . --rules pattern.json
- dry-run mode prints:
  - counts by tier
  - top matched signals
  - list of endpoints with score, method, and extracted params

Extraction Strategy (Practical, Not Perfect)
- Regex-based extraction is acceptable.
- Extract keys from patterns like:
  - $_GET['x'], $_POST["y"], $_REQUEST['z']
  - $body['k'] where $body is derived from json_decode(file_get_contents('php://input'), true)
- Detect output patterns:
  - json_encode, application/json, custom helpers listed in rules
- Infer method using:
  - explicit checks in code or method_inference rules
  - fallback to default_method

Postman Collection v2.1 Requirements
- Generate valid v2.1 JSON structure:
  - info { name, schema }
  - item []
  - variable [{key,value}]
- Use {{baseUrl}} variable for host.
- Do not hardcode environment-specific URLs.

Implementation Notes
- Efficient scanning, handle large repos.
- Skip huge files beyond a size limit but record in catalog if needed.
- Modular code:
  - load_rules + validate
  - scan_files
  - analyze_file (signals, score, params, method)
  - build_postman_collection
  - write_outputs

Deliverables
- tool_b.py implementation
- Embedded or separate README usage section
- Minimal test plan (how to validate the generated Postman JSON imports successfully)

Non-Goals
- Do not execute PHP.
- Do not require network calls.
- Do not implement a full PHP parser unless necessary; keep it simple and extendable.

Now produce the full Python implementation plus the rules schema documentation and CLI usage examples.

