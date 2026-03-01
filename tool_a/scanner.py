import os
from typing import Iterator, List, Optional

DEFAULT_EXCLUDE_DIRS = ['vendor', 'node_modules', 'storage', 'cache', 'logs', 'tmp', '.git']
DEFAULT_INCLUDE_EXTENSIONS = ['.php']
DEFAULT_MAX_FILE_SIZE_MB = 5

def scan_directory(
    root_path: str,
    exclude_dirs: Optional[List[str]],
    include_extensions: Optional[List[str]],
    max_file_size_mb: int
) -> Iterator[str]:
    
    exclude_dirs_set = set(exclude_dirs if exclude_dirs is not None else DEFAULT_EXCLUDE_DIRS)
    include_extensions_tuple = tuple(include_extensions if include_extensions is not None else DEFAULT_INCLUDE_EXTENSIONS)
    max_size_bytes = max_file_size_mb * 1024 * 1024

    for root, dirs, files in os.walk(root_path, topdown=True):
        # Modify dirs in-place to prune the search based on the exclude list
        dirs[:] = [d for d in dirs if d not in exclude_dirs_set]

        for file in files:
            if file.endswith(include_extensions_tuple):
                file_path = os.path.join(root, file)
                try:
                    if os.path.getsize(file_path) <= max_size_bytes:
                        yield file_path
                    else:
                        print(f"Skipping large file (>{max_file_size_mb}MB): {file_path}")
                except OSError:
                    # File might not exist anymore if it was temporary, or permissions error
                    continue
