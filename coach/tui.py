"""A small, keyboard-driven reader. All curses calls stay on the UI thread."""
from __future__ import annotations

import curses
import json
import queue
import textwrap
import threading
import time
from pathlib import Path

from .core import save_json


RATINGS = {"u": "useful", "i": "irrelevant", "a": "already_understood", "x": "unsupported"}


def paragraphs(review: dict, selected: int, tab: int) -> list[str]:
    packet, report = review["packet"], review["report"]
    if tab == 2:
        return ["PR diff", "", *packet["diff"].splitlines()]
    if tab == 3:
        checks = review.get("assessment", {}).get("decisions", {}).get("decisions", [])
        decisions = [f"Draft point {d['index'] + 1}: {'kept' if d['keep'] else 'discarded'}. {d['reason']}" for d in checks]
        return ["Scope of this assessment", "", f"Head: {packet['pr']['headRefOid']}",
                f"Comparison base: {packet['merge_base']}", "", *packet["coverage_notes"],
                "", "Draft relevance check", *(decisions or ["No second-pass decisions in this saved result."]),
                "", "Files supplied to the model", *[f"{f['side']}: {f['path']}" for f in packet["files"]]]
    points = report["points"]
    if not points:
        title = "No feedback worth raising" if report["status"] == "no_feedback" else "More context needed"
        return [title, "", report["summary"], "", "This assessment covers the supplied evidence. Press c to see its scope."]
    point = points[selected]
    if tab == 1:
        lines = []
        for citation in point["evidence"]:
            lines.extend([f"{citation['side']}: {citation['path']}:{citation['line']}", ""])
            source = next(f for f in packet["files"] if f["path"] == citation["path"] and f["side"] == citation["side"])
            start = max(source["start_line"], citation["line"] - 5)
            end = citation["line"] + len(citation["quote"].splitlines()) + 5
            for number, line in enumerate(source["text"].splitlines(), source["start_line"]):
                if start <= number < end:
                    marker = ">" if citation["line"] <= number < citation["line"] + len(citation["quote"].splitlines()) else " "
                    lines.append(f"{marker} {number:4}  {line}")
            lines.append("")
        return lines
    timing = "Discuss in this PR" if point["timing"] == "this_pr" else "Save for a later conversation"
    lines = [point["title"], f"{point['kind'].capitalize()} | {timing}", "",
             point["observation"], "", "Why it matters", point["why"], "",
             "Ask the developer", point["question"], "", "What to explain", point["principle"]]
    if point["assumptions"]:
        lines.extend(["", "Assumptions to check", *point["assumptions"]])
    lines.extend(["", "Evidence", *[f"{e['side']}: {e['path']}:{e['line']}" for e in point["evidence"]]])
    return lines


def wrapped(lines: list[str], width: int) -> list[str]:
    output = []
    for line in lines:
        # Remove control characters so PR text cannot control a user's terminal.
        clean = "".join(char if char.isprintable() else " " for char in line)
        output.extend(textwrap.wrap(clean, max(10, width), replace_whitespace=False,
                                    drop_whitespace=False) or [""])
    return output


def show(loader, state_dir: Path):
    messages = queue.Queue()

    def work():
        try:
            review = loader(lambda message: messages.put(("progress", message)))
            messages.put(("result", review))
        except Exception as exc:
            messages.put(("error", str(exc)))

    def screen(stdscr):
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        stdscr.timeout(120)
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            curses.init_pair(2, curses.COLOR_GREEN, -1)
        accent = curses.color_pair(1) if curses.has_colors() else curses.A_BOLD
        review = None
        error = None
        status = "Preparing review"
        selected = tab = scroll = 0
        ratings = {}
        started = time.monotonic()
        threading.Thread(target=work, daemon=True).start()

        def put(y, x, text, attr=0):
            height, width = stdscr.getmaxyx()
            if 0 <= y < height and 0 <= x < width - 1:
                clean = "".join(c if c.isprintable() else " " for c in text)
                try:
                    stdscr.addnstr(y, x, clean, width - x - 1, attr)
                except curses.error:
                    pass

        while True:
            while not messages.empty():
                kind, value = messages.get_nowait()
                if kind == "result":
                    review = value
                    path = state_dir / (review.get("id", review["packet"]["id"]) + ".ratings.json")
                    if path.exists():
                        try:
                            ratings = json.loads(path.read_text())
                            if not isinstance(ratings, dict):
                                ratings = {}
                        except (OSError, ValueError):
                            ratings = {}
                    status = "Saved locally. Nothing is posted to GitHub."
                elif kind == "error":
                    error = value
                else:
                    status = value
            stdscr.erase()
            height, width = stdscr.getmaxyx()
            put(0, 2, "COACH  /  Prepare a useful conversation", accent | curses.A_BOLD)
            if width < 55 or height < 14:
                put(2, 1, "Resize to at least 55 columns and 14 rows. q quits.")
                stdscr.refresh()
                if stdscr.getch() == ord("q"):
                    return
                continue
            if error:
                lines = wrapped(["Analysis failed", "", error, "", "This is not a no-feedback result. Press q to close."], width - 5)
            elif review:
                packet, report = review["packet"], review["report"]
                put(2, 2, f"#{packet['pr']['number']}  {packet['pr']['title']}", curses.A_BOLD)
                count = len(report["points"])
                position = f"Point {selected + 1} of {count}" if count else "No coaching points"
                rating = ratings.get(str(selected), "not rated") if count else ratings.get("review", "not rated")
                put(3, 2, f"{position}  |  {rating.replace('_', ' ')}", accent)
                labels = ["[f] Conversation", "[e] Evidence", "[d] Diff", "[c] Context"]
                put(5, 2, "   ".join(label.upper() if i == tab else label for i, label in enumerate(labels)))
                lines = wrapped(paragraphs(review, selected, tab), width - 6)
            else:
                elapsed = int(time.monotonic() - started)
                lines = wrapped(["Reading and thinking" + "." * (elapsed % 4), "", status,
                                 "", f"{elapsed}s elapsed. Local models can take several minutes.",
                                 "q closes the viewer; the current model request may finish in Ollama."], width - 6)
            visible = max(1, height - 12)
            scroll = max(0, min(scroll, max(0, len(lines) - visible)))
            for index, line in enumerate(lines[scroll:scroll + visible]):
                put(7 + index, 3, line)
            put(height - 4, 2, status)
            put(height - 3, 2, "j/k scroll  n/p points  f/e/d/c views  q quit", accent)
            put(height - 2, 2, "Rate: u useful  i irrelevant  a already understood  x unsupported")
            stdscr.refresh()
            key = stdscr.getch()
            if key in (ord("q"), 27):
                return error is None
            if key in (ord("j"), curses.KEY_DOWN):
                scroll += 1
            elif key in (ord("k"), curses.KEY_UP):
                scroll -= 1
            elif key == curses.KEY_NPAGE:
                scroll += visible
            elif key == curses.KEY_PPAGE:
                scroll -= visible
            elif review and key in (ord("n"), ord("p")):
                count = len(review["report"]["points"])
                selected = (selected + (1 if key == ord("n") else -1)) % max(1, count)
                scroll = 0
            elif review and key in map(ord, "fedc"):
                tab = "fedc".index(chr(key))
                scroll = 0
            elif review and key in map(ord, RATINGS):
                rating_key = str(selected) if review["report"]["points"] else "review"
                ratings[rating_key] = RATINGS[chr(key)]
                try:
                    save_json(state_dir / (review.get("id", review["packet"]["id"]) + ".ratings.json"), ratings)
                    status = "Rating saved locally."
                except OSError as exc:
                    status = f"Could not save rating: {exc}"
    return curses.wrapper(screen)
