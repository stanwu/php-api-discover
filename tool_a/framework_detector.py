"""Auto-detects the PHP framework in use based on file/directory fingerprints."""

import json
import os
from typing import List, Tuple


def detect_framework(
    root_path: str,
    force_framework: str = None,
) -> Tuple[str, str, List[str]]:
    """
    Returns (framework_name, confidence, evidence_list).

    Framework names: "laravel" | "wordpress" | "codeigniter" | "symfony" | "slim" | "plain"
    Confidence:      "high" | "medium" | "low" | "forced"
    """
    if force_framework:
        valid = {"laravel", "wordpress", "codeigniter", "symfony", "slim", "plain"}
        name = force_framework.lower()
        if name not in valid:
            name = "plain"
        return name, "forced", [f"Framework forced via --framework flag: {name}"]

    evidence: List[str] = []

    # ── Laravel ──────────────────────────────────────────────────────────────
    if os.path.isfile(os.path.join(root_path, "artisan")) and os.path.isdir(
        os.path.join(root_path, "app", "Http", "Controllers")
    ):
        evidence.append("artisan file found")
        evidence.append("app/Http/Controllers/ directory found")
        return "laravel", "high", evidence

    # ── WordPress ────────────────────────────────────────────────────────────
    if os.path.isfile(os.path.join(root_path, "wp-config.php")):
        evidence.append("wp-config.php found")
        return "wordpress", "high", evidence
    if os.path.isdir(os.path.join(root_path, "wp-includes")):
        evidence.append("wp-includes/ directory found")
        return "wordpress", "high", evidence

    # ── Symfony ──────────────────────────────────────────────────────────────
    if os.path.isfile(os.path.join(root_path, "symfony.lock")):
        evidence.append("symfony.lock found")
        return "symfony", "high", evidence
    if os.path.isfile(os.path.join(root_path, "src", "Kernel.php")):
        evidence.append("src/Kernel.php found")
        return "symfony", "high", evidence

    # ── CodeIgniter ───────────────────────────────────────────────────────────
    if os.path.isfile(
        os.path.join(root_path, "system", "core", "CodeIgniter.php")
    ):
        evidence.append("system/core/CodeIgniter.php found")
        return "codeigniter", "high", evidence
    if os.path.isdir(os.path.join(root_path, "application")):
        evidence.append("application/ directory found")
        return "codeigniter", "medium", evidence

    # ── Slim / Lumen (composer.json check) ───────────────────────────────────
    composer_json_path = os.path.join(root_path, "composer.json")
    if os.path.isfile(composer_json_path):
        try:
            with open(composer_json_path, "r", encoding="utf-8") as fh:
                composer_data = json.load(fh)
            require = composer_data.get("require", {})
            if "slim/slim" in require:
                evidence.append("slim/slim found in composer.json")
                return "slim", "high", evidence
            if "laravel/lumen-framework" in require:
                evidence.append("laravel/lumen-framework found in composer.json")
                return "slim", "high", evidence
        except Exception:
            pass

    # ── Plain PHP fallback ───────────────────────────────────────────────────
    evidence.append("No framework-specific files found; defaulting to plain PHP")
    return "plain", "low", evidence
