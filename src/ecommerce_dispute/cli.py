"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import create_submission_zip, run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve all 50 Olist dispute cases")
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(), help="Repository root (default: cwd)"
    )
    parser.add_argument(
        "--zip",
        action="store_true",
        help="Create output.zip containing exactly the 50 output JSON files",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.root.resolve()
    metadata = run_pipeline(
        root, progress_callback=lambda message: print(message, flush=True)
    )
    if args.zip:
        create_submission_zip(root / "output", root / "output.zip")
    print(json.dumps(metadata["run"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
