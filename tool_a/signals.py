"""
Framework-specific signal profiles.

Each signal entry is a dict:
  {
    "name":               str,            # display name
    "pattern":            re.Pattern,     # compiled regex
    "kind":               str,            # "strong" | "weak" | "negative"
    "delta":              int,            # score contribution (signed)
    "false_positive_risk": str,           # "low" | "medium" | "high" | "n/a"
  }

Base scoring table (from spec):
  Content-Type header literal     +35
  Framework JSON helper           +30
  die/exit(json_encode(           +25
  Custom helper from registry     +20  (applied in detector, not here)
  Lone json_encode(               +10
  Concatenated header (dynamic)   +5   (applied in detector)
  <html literal                   −20
  return view / load view / Blade −15
  include.*header/footer.php      −10
  echo.*<HTML-tag>                −5
"""

import re
from typing import Dict, List

# ── Helper: build a signal dict ───────────────────────────────────────────────

def _s(name, pattern_str, kind, delta, fpr="low", flags=0):
    return {
        "name": name,
        "pattern": re.compile(pattern_str, flags),
        "kind": kind,
        "delta": delta,
        "false_positive_risk": fpr,
    }


# ── Common negative signals (shared across frameworks) ────────────────────────

_NEG_HTML = _s("<html literal", r"<html", "negative", -20, "n/a", re.IGNORECASE)
_NEG_ECHO_HTML = _s(
    "echo HTML tag",
    r"echo\s+['\"].*?<[a-zA-Z]",
    "negative", -5, "n/a", re.IGNORECASE,
)
_NEG_INCLUDE_HEADER = _s(
    "include header.php",
    r"(?:include|require)(?:_once)?\s*['\"].*?header\.php['\"]",
    "negative", -10, "n/a", re.IGNORECASE,
)
_NEG_INCLUDE_FOOTER = _s(
    "include footer.php",
    r"(?:include|require)(?:_once)?\s*['\"].*?footer\.php['\"]",
    "negative", -10, "n/a", re.IGNORECASE,
)

_COMMON_NEGATIVES = [_NEG_HTML, _NEG_ECHO_HTML, _NEG_INCLUDE_HEADER, _NEG_INCLUDE_FOOTER]


# ── Framework profiles ────────────────────────────────────────────────────────

FRAMEWORK_SIGNALS: Dict[str, List[dict]] = {

    "laravel": [
        # Strong
        _s("response()->json(",
           r"response\s*\(\s*\)\s*->\s*json\s*\(",
           "strong", 30),
        _s("JsonResource",
           r"\bJsonResource\b",
           "strong", 30),
        _s("->toResponse(",
           r"->\s*toResponse\s*\(",
           "strong", 30),
        # Weak
        _s("json_encode(",
           r"\bjson_encode\s*\(",
           "weak", 10, "medium"),
        _s("Illuminate\\Http\\JsonResponse",
           r"Illuminate\\+Http\\+JsonResponse",
           "weak", 10, "low"),
        # Negative
        _s("return view(",
           r"\breturn\s+view\s*\(",
           "negative", -15, "n/a"),
        _s("->render(",
           r"->\s*render\s*\(",
           "negative", -15, "n/a"),
        _s("Blade::",
           r"\bBlade\s*::\s*\w+\s*\(",
           "negative", -15, "n/a"),
    ] + _COMMON_NEGATIVES,

    "wordpress": [
        # Strong
        _s("wp_send_json(",
           r"\bwp_send_json\s*\(",
           "strong", 30),
        _s("wp_send_json_success(",
           r"\bwp_send_json_success\s*\(",
           "strong", 30),
        _s("wp_send_json_error(",
           r"\bwp_send_json_error\s*\(",
           "strong", 30),
        _s("add_action('wp_ajax_",
           r"add_action\s*\(\s*['\"]wp_ajax_",
           "strong", 30),
        # Weak
        _s("json_encode(",
           r"\bjson_encode\s*\(",
           "weak", 10, "medium"),
        _s("wp_die(",
           r"\bwp_die\s*\(",
           "weak", 5, "medium"),
        # Negative
        _s("get_template_part(",
           r"\bget_template_part\s*\(",
           "negative", -15, "n/a"),
        _s("load_template(",
           r"\bload_template\s*\(",
           "negative", -15, "n/a"),
        _s("echo get_header(",
           r"\becho\s+get_header\s*\(",
           "negative", -15, "n/a"),
    ] + _COMMON_NEGATIVES,

    "codeigniter": [
        # Strong
        _s("$this->output->set_content_type('application/json')",
           r"\$this\s*->\s*output\s*->\s*set_content_type\s*\(\s*['\"]application/json['\"]",
           "strong", 30),
        _s("$this->response(",
           r"\$this\s*->\s*response\s*\(",
           "strong", 30),
        # Weak
        _s("json_encode(",
           r"\bjson_encode\s*\(",
           "weak", 10, "medium"),
        _s("$this->input->post(",
           r"\$this\s*->\s*input\s*->\s*post\s*\(",
           "weak", 5, "medium"),
        # Negative
        _s("$this->load->view(",
           r"\$this\s*->\s*load\s*->\s*view\s*\(",
           "negative", -15, "n/a"),
    ] + _COMMON_NEGATIVES,

    "symfony": [
        # Strong
        _s("new JsonResponse(",
           r"\bnew\s+JsonResponse\s*\(",
           "strong", 30),
        _s("$this->json(",
           r"\$this\s*->\s*json\s*\(",
           "strong", 30),
        _s("JsonResponse::HTTP_",
           r"\bJsonResponse\s*::\s*HTTP_",
           "strong", 20),
        # Weak
        _s("json_encode(",
           r"\bjson_encode\s*\(",
           "weak", 10, "medium"),
        _s("Request $request",
           r"\bRequest\s+\$request\b",
           "weak", 5, "low"),
        # Negative
        _s("$this->render(",
           r"\$this\s*->\s*render\s*\(",
           "negative", -15, "n/a"),
        _s("$this->renderView(",
           r"\$this\s*->\s*renderView\s*\(",
           "negative", -15, "n/a"),
    ] + _COMMON_NEGATIVES,

    "slim": [
        # Strong
        _s("response()->json(",
           r"response\s*\(\s*\)\s*->\s*json\s*\(",
           "strong", 30),
        _s("$response->withJson(",
           r"\$response\s*->\s*withJson\s*\(",
           "strong", 30),
        _s("$response->withHeader Content-Type application/json",
           r"\$response\s*->\s*withHeader\s*\(\s*['\"]Content-Type['\"],\s*['\"]application/json['\"]",
           "strong", 35),
        # Weak
        _s("json_encode(",
           r"\bjson_encode\s*\(",
           "weak", 10, "medium"),
        # Negative
        _s("return view(",
           r"\breturn\s+view\s*\(",
           "negative", -15, "n/a"),
    ] + _COMMON_NEGATIVES,

    "plain": [
        # Strong
        _s("header('Content-Type: application/json') literal",
           r"header\s*\(\s*'Content-Type:\s*application/json'\s*\)",
           "strong", 35),
        _s('header("Content-Type: application/json") literal',
           r'header\s*\(\s*"Content-Type:\s*application/json"\s*\)',
           "strong", 35),
        _s("die(json_encode(",
           r"\bdie\s*\(\s*json_encode\s*\(",
           "strong", 25),
        _s("exit(json_encode(",
           r"\bexit\s*\(\s*json_encode\s*\(",
           "strong", 25),
        # Weak
        _s("json_encode(",
           r"\bjson_encode\s*\(",
           "weak", 10, "medium"),
        _s("$_SERVER['HTTP_ACCEPT']",
           r"\$_SERVER\s*\[\s*['\"]HTTP_ACCEPT['\"]",
           "weak", 5, "low"),
        # Negative
        _s("$this->load->view(",
           r"\$this\s*->\s*load\s*->\s*view\s*\(",
           "negative", -15, "n/a"),
        _s("return view(",
           r"\breturn\s+view\s*\(",
           "negative", -15, "n/a"),
    ] + _COMMON_NEGATIVES,
}

# Ensure each framework falls back to "plain" if not found
for _fw in ("laravel", "wordpress", "codeigniter", "symfony", "slim", "plain"):
    if _fw not in FRAMEWORK_SIGNALS:
        FRAMEWORK_SIGNALS[_fw] = FRAMEWORK_SIGNALS["plain"]
