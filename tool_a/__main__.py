import argparse
import os
from collections import Counter
from .scanner import scan_directory, DEFAULT_EXCLUDE_DIRS, DEFAULT_INCLUDE_EXTENSIONS, DEFAULT_MAX_FILE_SIZE_MB
from .detector import Detector
from .reporting import generate_markdown_report, generate_jsonl_report

def main():
    parser = argparse.ArgumentParser(
        description="Scan a PHP project to extract API features.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    # Main command is "scan", but using subparsers for future extensibility
    subparsers = parser.add_subparsers(dest="command")
    
    scan_parser = subparsers.add_parser("scan", help="Scan a directory for API features")
    scan_parser.add_argument("--root", type=str, required=True, help="Root path of the PHP project.")
    scan_parser.add_argument("--out", type=str, required=True, help="Output path for the Markdown report.")
    scan_parser.add_argument("--raw", type=str, help="Optional output path for the raw JSONL features.")
    scan_parser.add_argument("--exclude", nargs='*', help=f"Directories to exclude. Default: {' '.join(DEFAULT_EXCLUDE_DIRS)}")
    scan_parser.add_argument("--extensions", nargs='*', help=f"File extensions to include. Default: {' '.join(DEFAULT_INCLUDE_EXTENSIONS)}")
    scan_parser.add_argument("--max-files", type=int, default=20000, help="Maximum number of files to scan.")
    scan_parser.add_argument("--max-snippet-lines", type=int, default=10, help="Number of lines for context snippets.")
    scan_parser.add_argument("--max-file-size-mb", type=int, default=DEFAULT_MAX_FILE_SIZE_MB, help="Maximum file size in MB to process.")

    # Set default command if none is provided
    import sys
    if len(sys.argv) == 1 or sys.argv[1] not in subparsers.choices:
        # Default to 'scan' if no command or an invalid one is given, but check for --help
        if any(h in sys.argv for h in ['-h', '--help']):
             parser.print_help()
             sys.exit(0)
        # This is a bit of a hack to make 'scan' the default command
        # It assumes if a command isn't specified, it should be 'scan'.
        # A more robust solution might be needed if more commands are added.
        args = parser.parse_args(['scan'] + sys.argv[1:])
    else:
        args = parser.parse_args()


    if args.command == "scan":
        run_scan(args)
    else:
        parser.print_help()

def run_scan(args):
    if not os.path.isdir(args.root):
        print(f"Error: Root path '{args.root}' is not a valid directory.")
        return

    print(f"Starting scan of '{args.root}'...")
    
    detector = Detector(max_snippet_lines=args.max_snippet_lines)
    features_list = []
    
    file_paths = scan_directory(
        root_path=args.root,
        exclude_dirs=args.exclude,
        include_extensions=args.extensions,
        max_file_size_mb=args.max_file_size_mb
    )

    scanned_files_count = 0
    php_files_count = 0
    dir_counter = Counter()
    signal_counter = Counter()

    for i, file_path in enumerate(file_paths):
        scanned_files_count += 1
        if i >= args.max_files:
            print(f"Reached max files limit ({args.max_files}). Stopping.")
            break
        
        php_files_count += 1
        relative_path = os.path.relpath(file_path, args.root)
        dir_counter[os.path.dirname(relative_path)] += 1
        
        print(f"Analyzing: {relative_path}")
        features = detector.analyze_file(file_path)
        features_list.append(features)
        
        for category in features.signals:
            for signal in features.signals[category]:
                signal_counter[signal] += 1

    print("Scan complete. Generating reports...")

    summary_stats = {
        "total_files": scanned_files_count,
        "php_files": php_files_count,
        "top_dirs": dir_counter.most_common(10),
        "top_signals": signal_counter.most_common(15),
    }

    generate_markdown_report(features_list, summary_stats, args.out)
    print(f"Markdown report saved to: {args.out}")

    if args.raw:
        generate_jsonl_report(features_list, args.raw)
        print(f"JSONL report saved to: {args.raw}")

if __name__ == "__main__":
    main()
