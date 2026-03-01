"""
Filesystem walker — streaming, memory-safe.

collect_files() yields all PHP files under root_path that pass filters,
and returns a separate list of skipped files (too large, etc.).
"""

import os
from typing import Dict, List, Optional, Tuple

DEFAULT_EXCLUDE_DIRS = [
    "vendor", "node_modules", "storage", "cache", "logs", "tmp", ".git"
]
DEFAULT_INCLUDE_EXTENSIONS = [".php"]
DEFAULT_MAX_FILE_SIZE_MB = 3


def collect_files(
    root_path: str,
    exclude_dirs: Optional[List[str]],
    include_extensions: Optional[List[str]],
    max_file_size_mb: float,
    max_files: int = 0,
) -> Tuple[List[str], List[Dict]]:
    """
    Walk root_path and collect PHP (or other) source files.

    Returns (file_paths, skipped_files).
      file_paths    : absolute paths of files to scan
      skipped_files : list of dicts {path, reason, size_mb?}
    """
    exclude_set = set(
        exclude_dirs if exclude_dirs is not None else DEFAULT_EXCLUDE_DIRS
    )
    extensions = tuple(
        include_extensions if include_extensions is not None else DEFAULT_INCLUDE_EXTENSIONS
    )
    max_bytes = int(max_file_size_mb * 1024 * 1024)

    file_paths: List[str] = []
    skipped: List[Dict] = []

    for dirpath, dirnames, filenames in os.walk(root_path, topdown=True):
        # Prune excluded directories in-place (deterministic order)
        dirnames[:] = sorted(d for d in dirnames if d not in exclude_set)

        for filename in sorted(filenames):
            if not filename.endswith(extensions):
                continue

            full_path = os.path.join(dirpath, filename)
            try:
                size = os.path.getsize(full_path)
            except OSError:
                continue

            if size > max_bytes:
                skipped.append(
                    {
                        "path": full_path,
                        "reason": "too_large",
                        "size_mb": round(size / 1024 / 1024, 2),
                    }
                )
                continue

            file_paths.append(full_path)

            if max_files > 0 and len(file_paths) >= max_files:
                return file_paths, skipped

    return file_paths, skipped
