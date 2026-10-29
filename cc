#!/usr/bin/env python3
"""Run CC from any directory without installing it."""
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "src"))
from cc.__main__ import main

if __name__ == "__main__":
    example = root / "results" / "pr11-checked.json"
    if len(sys.argv) == 1 and example.is_file():
        sys.argv.extend(["--open", str(example), "--state-dir", str(root / ".cc")])
    raise SystemExit(main())
