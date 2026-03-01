"""
Route Mapper — links controller files to URL patterns.

Supports:
  - Laravel  : parses routes/api.php and routes/web.php
  - WordPress: parses add_action('wp_ajax_...')  calls
  - Others   : falls back to file-path-based "low-confidence" hints
"""

import os
import re
from typing import Dict, List, Optional

from .models import RouteHint

# ── Laravel route regex patterns ─────────────────────────────────────────────

# New array-style: Route::get('/uri', [Controller::class, 'method'])
_LARAVEL_ARRAY = re.compile(
    r"Route\s*::\s*(get|post|put|patch|delete|any)\s*\("
    r"\s*['\"]([^'\"]+)['\"]\s*,\s*"
    r"\[\s*([A-Za-z\\]+)::class\s*,\s*['\"](\w+)['\"]\s*\]",
    re.IGNORECASE,
)

# Old string-style: Route::get('/uri', 'Controller@method')
_LARAVEL_STRING = re.compile(
    r"Route\s*::\s*(get|post|put|patch|delete|any)\s*\("
    r"\s*['\"]([^'\"]+)['\"]\s*,\s*"
    r"['\"]([A-Za-z\\]+)@(\w+)['\"]",
    re.IGNORECASE,
)

# ── WordPress AJAX action pattern ─────────────────────────────────────────────
_WP_AJAX = re.compile(
    r"add_action\s*\(\s*['\"]wp_ajax(?:_nopriv)?_([^'\"]+)['\"]\s*,\s*"
    r"(?:array\s*\([^)]+\)|['\"]?([A-Za-z_][A-Za-z0-9_:]*)['\"]?)\s*\)",
    re.IGNORECASE,
)

_SKIP_DIRS = {"vendor", "node_modules", ".git", "storage", "cache", "logs", "tmp"}


class RouteMapper:
    def __init__(self) -> None:
        # controller short-class-name → list of hints
        self._controller_map: Dict[str, List[RouteHint]] = {}
        # WordPress: handler function/method → hint
        self._wp_handler_map: Dict[str, RouteHint] = {}
        self._framework: str = "plain"
        self._root_path: str = ""

    # ── Public API ────────────────────────────────────────────────────────────

    def load(self, framework: str, root_path: str) -> None:
        self._framework = framework
        self._root_path = root_path

        if framework == "laravel":
            self._load_laravel(root_path)
        elif framework == "wordpress":
            self._load_wordpress(root_path)

    def get_hints_for_file(self, rel_path: str, content: str) -> List[RouteHint]:
        if self._framework == "laravel":
            return self._hints_laravel(rel_path)
        if self._framework == "wordpress":
            return self._hints_wordpress(rel_path, content)
        return self._hints_plain(rel_path)

    # ── Laravel ───────────────────────────────────────────────────────────────

    def _load_laravel(self, root_path: str) -> None:
        for fname in ("api.php", "web.php"):
            path = os.path.join(root_path, "routes", fname)
            if not os.path.isfile(path):
                continue
            rel = os.path.relpath(path, root_path)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    lines = fh.readlines()
            except OSError:
                continue

            for i, line in enumerate(lines):
                line_no = i + 1
                hint = self._parse_laravel_line(line, rel, line_no)
                if hint:
                    ctrl = hint.controller_method.split("@")[0] if hint.controller_method else ""
                    self._controller_map.setdefault(ctrl, []).append(hint)

    def _parse_laravel_line(
        self, line: str, source_file: str, line_no: int
    ) -> Optional[RouteHint]:
        m = _LARAVEL_ARRAY.search(line)
        if m:
            ctrl = m.group(3).split("\\")[-1]
            return RouteHint(
                method=m.group(1).upper(),
                uri=m.group(2),
                source_file=source_file,
                source_line=line_no,
                confidence="high",
                controller_method=f"{ctrl}@{m.group(4)}",
            )
        m = _LARAVEL_STRING.search(line)
        if m:
            ctrl = m.group(3).split("\\")[-1]
            return RouteHint(
                method=m.group(1).upper(),
                uri=m.group(2),
                source_file=source_file,
                source_line=line_no,
                confidence="high",
                controller_method=f"{ctrl}@{m.group(4)}",
            )
        return None

    def _hints_laravel(self, rel_path: str) -> List[RouteHint]:
        basename = os.path.basename(rel_path)
        class_name = basename[:-4] if basename.endswith(".php") else basename
        hints = self._controller_map.get(class_name)
        if hints:
            return hints
        return [
            RouteHint(
                method="unknown",
                uri=f"/{rel_path}",
                source_file=rel_path,
                source_line=0,
                confidence="low",
                controller_method=None,
            )
        ]

    # ── WordPress ─────────────────────────────────────────────────────────────

    def _load_wordpress(self, root_path: str) -> None:
        for dirpath, dirnames, filenames in os.walk(root_path, topdown=True):
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
            for filename in sorted(filenames):
                if not filename.endswith(".php"):
                    continue
                file_path = os.path.join(dirpath, filename)
                rel = os.path.relpath(file_path, root_path)
                try:
                    with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
                        lines = fh.readlines()
                except OSError:
                    continue
                for i, line in enumerate(lines):
                    m = _WP_AJAX.search(line)
                    if not m:
                        continue
                    action_name = m.group(1)
                    handler = m.group(2) or ""
                    hint = RouteHint(
                        method="POST",
                        uri=f"/wp-admin/admin-ajax.php?action={action_name}",
                        source_file=rel,
                        source_line=i + 1,
                        confidence="high",
                        controller_method=handler if handler else None,
                    )
                    if handler:
                        self._wp_handler_map[handler] = hint

    def _hints_wordpress(self, rel_path: str, content: str) -> List[RouteHint]:
        func_names = re.findall(r"function\s+(\w+)\s*\(", content)
        hints = [
            self._wp_handler_map[fn]
            for fn in func_names
            if fn in self._wp_handler_map
        ]
        return hints if hints else []

    # ── Plain PHP ─────────────────────────────────────────────────────────────

    def _hints_plain(self, rel_path: str) -> List[RouteHint]:
        return [
            RouteHint(
                method="unknown",
                uri=f"/{rel_path}",
                source_file=rel_path,
                source_line=0,
                confidence="low",
                controller_method=None,
            )
        ]
