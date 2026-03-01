import json
import os
from typing import List, Dict
from .models import FileFeatures

def generate_markdown_report(
    features_list: List[FileFeatures],
    summary_stats: Dict,
    output_path: str
):
    with open(output_path, 'w', encoding='utf-8') as f:
        # Summary
        f.write("# PHP API Feature Extraction Report\n\n")
        f.write("## Summary Statistics\n\n")
        f.write(f"- Total files scanned: {summary_stats['total_files']}\n")
        f.write(f"- Total PHP files analyzed: {summary_stats['php_files']}\n")
        
        if summary_stats['top_dirs']:
            f.write("\n### Top Directories by PHP File Count\n")
            for d, c in summary_stats['top_dirs']:
                f.write(f"- `{d}`: {c} files\n")

        if summary_stats['top_signals']:
            f.write("\n### Top Detected Signals\n")
            for s, c in summary_stats['top_signals']:
                f.write(f"- `{s}`: {c} occurrences\n")

        f.write("\n## Candidate Endpoint Files\n\n")
        f.write("Files are scored based on heuristics. A high score suggests a higher likelihood of being an API endpoint. Files with a score below 30 and no detected output points are omitted for brevity.\n\n")

        # Per-file details, sorted by score
        sorted_features = sorted(features_list, key=lambda x: x.score, reverse=True)
        
        for features in sorted_features:
            if features.error:
                f.write(f"### `{features.path}`\n\n")
                f.write(f"**Error:** {features.error}\n\n---\n\n")
                continue

            # Skip low-score files unless they have some output, to reduce noise
            if features.score < 30 and not features.output_points:
                continue

            f.write(f"### `{os.path.relpath(features.path)}`\n\n")
            f.write(f"**Heuristic Score:** {features.score}/100\n\n")

            if features.signals['strong'] or features.signals['weak'] or features.signals['negative']:
                f.write("**Matched Evidence:**\n")
                if features.signals["strong"]:
                    f.write(f"- **Strong Signals:** {', '.join(sorted(list(set(features.signals['strong']))))}\n")
                if features.signals["weak"]:
                    f.write(f"- **Weak Signals:** {', '.join(sorted(list(set(features.signals['weak']))))}\n")
                if features.signals["negative"]:
                    f.write(f"- **Negative Signals:** {', '.join(sorted(list(set(features.signals['negative']))))}\n")
                f.write("\n")

            has_params = any(v for v in features.input_params.values())
            if has_params:
                f.write("**Parameter Hints:**\n")
                if features.input_params["get"]:
                    f.write(f"- `$_GET` keys: `{', '.join(features.input_params['get'])}`\n")
                if features.input_params["post"]:
                    f.write(f"- `$_POST` keys: `{', '.join(features.input_params['post'])}`\n")
                if features.input_params["request"]:
                    f.write(f"- `$_REQUEST` keys: `{', '.join(features.input_params['request'])}`\n")
                if features.input_params["json_body"]:
                    f.write(f"- Suspected JSON body keys: `{', '.join(features.input_params['json_body'])}`\n")
                f.write("\n")

            if features.method_hints:
                f.write(f"**Request Method Checks:** `{', '.join(features.method_hints)}`\n\n")

            if features.envelope_keys:
                f.write(f"**Output Envelope Hints:** `{', '.join(features.envelope_keys)}`\n\n")

            if features.output_points:
                f.write("**Output Snippets:**\n")
                for point in features.output_points:
                    f.write(f"\n*   **Kind:** `{point.kind}`, **Line:** {point.line_no}\n")
                    f.write("    ```php\n")
                    f.write(point.context_excerpt)
                    f.write("\n    ```\n")
            
            f.write("\n---\n\n")

def generate_jsonl_report(
    features_list: List[FileFeatures],
    output_path: str
):
    with open(output_path, 'w', encoding='utf-8') as f:
        for features in features_list:
            if features.error:
                continue
            
            # Convert dataclasses to dicts for JSON serialization
            feature_dict = {
                "path": features.path,
                "score": features.score,
                "signals": features.signals,
                "input_params": features.input_params,
                "method_hints": features.method_hints,
                "envelope_keys": features.envelope_keys,
                "output_points": [
                    {"kind": p.kind, "line_no": p.line_no, "context_excerpt": p.context_excerpt}
                    for p in features.output_points
                ],
                "notes": features.notes,
            }
            f.write(json.dumps(feature_dict) + '\n')