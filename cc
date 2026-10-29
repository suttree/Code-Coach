#!/usr/bin/env python3
"""Run CC from any directory without installing it."""
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "src"))
from cc.__main__ import main

if __name__ == "__main__":
    if not any(arg == "--state-dir" or arg.startswith("--state-dir=") for arg in sys.argv[1:]):
        sys.argv.extend(["--state-dir", str(root / ".cc")])
    raise SystemExit(main())
