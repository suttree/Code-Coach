from __future__ import annotations

import argparse
import hashlib
import time
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .core import QQError, analyse, collect, save_json, validate


def main():
    parser = argparse.ArgumentParser(prog="qq", description="Zero to two coaching opportunities for a PR.")
    parser.add_argument("--example", action="store_true", help="Open the curated two-point example without a model")
    parser.add_argument("pr", nargs="?", help="GitHub PR URL")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Local checkout, read without changes")
    parser.add_argument("--model", default=os.getenv("QQ_MODEL", "qwen3.5:9b-coding"))
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--context-file", action="append", default=[], help="Additional repository-relative file")
    parser.add_argument("--state-dir", type=Path, default=Path(".qq"))
    parser.add_argument("--open", type=Path, help="Open a saved review without GitHub or a model")
    parser.add_argument("--packet", type=Path, help="Analyse a previously collected evidence packet")
    parser.add_argument("--collect-only", action="store_true", help="Save evidence without running a model")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of opening the TUI")
    args = parser.parse_args()
    if not any((args.pr, args.open, args.packet, args.example)):
        args.example = True
    if sum(bool(value) for value in (args.pr, args.open, args.packet, args.example)) != 1:
        parser.error("Provide one PR URL, --open REVIEW, --packet EVIDENCE, or --example.")
    if args.example:
        args.open = Path(__file__).with_name("examples") / "suggestions.json"
    if args.collect_only and args.open:
        parser.error("--collect-only cannot be used with --open or --example.")

    def load(progress):
        if args.open:
            review = json.loads(args.open.read_text())
            validate(review["report"], review["packet"])
            return review
        packet = json.loads(args.packet.read_text()) if args.packet else collect(
            args.pr, args.repo, args.context_file, progress)
        save_json(args.state_dir / (packet["id"] + ".packet.json"), packet)
        if args.collect_only:
            return packet
        started = time.monotonic()
        audit = {}
        report = analyse(packet, args.model, args.endpoint, progress, audit=audit)
        review = {"packet": packet, "report": report, "model": args.model, "assessment": audit,
                  "created_at": datetime.now(timezone.utc).isoformat(),
                  "elapsed_seconds": round(time.monotonic() - started, 1)}
        review["id"] = hashlib.sha256(json.dumps([packet["id"], args.model, report], sort_keys=True).encode()).hexdigest()[:16]
        destination = args.state_dir / (review["id"] + ".review.json")
        save_json(destination, review)
        progress(f"Saved {destination}")
        return review
    try:
        if args.json or args.collect_only:
            result = load(lambda message: print(message, file=sys.stderr))
            print(json.dumps(result, indent=2))
        else:
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                raise QQError("The TUI needs an interactive terminal. Use --json for scripts.")
            from .tui import show
            if show(load) is False:
                return 1
    except (QQError, OSError, ValueError, KeyError) as exc:
        print(f"qq: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
