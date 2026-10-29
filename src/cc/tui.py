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
        return ["Scope of this assessment", "", *([review["example_note"], ""] if review.get("example") else []), f"Head: {packet['pr']['headRefOid']}",
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
             point["observation"], "", "why", point["why"], "",
             "Questions to ask", point["question"], "", "Explanation", point["principle"]]
    if point["assumptions"]:
        lines.extend(["", "Assumptions", *point["assumptions"]])
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



def palette():
    colors = {name: curses.A_BOLD for name in ("pink", "orange", "yellow", "green", "muted", "cyan")}
    colors["muted"] = curses.A_DIM
    if not curses.has_colors():
        return colors
    curses.start_color()
    background = curses.COLOR_BLACK
    try:
        curses.use_default_colors()
        background = -1
    except curses.error:
        pass
    choices = [("pink", 205, curses.COLOR_MAGENTA), ("orange", 215, curses.COLOR_YELLOW),
               ("yellow", 221, curses.COLOR_YELLOW), ("green", 114, curses.COLOR_GREEN),
               ("muted", 245, curses.COLOR_WHITE), ("cyan", 117, curses.COLOR_CYAN)]
    for pair, (name, rich, basic) in enumerate(choices, 1):
        try:
            curses.init_pair(pair, rich if curses.COLORS >= 256 else basic, background)
            colors[name] = curses.color_pair(pair)
        except curses.error:
            pass
    return colors


def line_style(line, colors, tab, titles):
    if line in titles or line in {"Questions to ask", "No feedback worth raising", "More context needed", "Analysis failed"}:
        return colors["pink"] | curses.A_BOLD
    if line in {"why", "Assumptions", "Scope of this assessment", "Draft relevance check"}:
        return colors["orange"] | curses.A_BOLD
    if line in {"Explanation", "Evidence", "PR diff", "Files supplied to the model"}:
        return colors["yellow"] | curses.A_BOLD
    if line.startswith("Strength |"):
        return colors["green"]
    if line.startswith("Discussion |"):
        return colors["orange"]
    if tab == 2:
        if line.startswith(("+++", "---", "@@", "diff --git")):
            return colors["yellow"]
        if line.startswith("+"):
            return colors["green"]
        if line.startswith("-"):
            return colors["pink"]
    if tab == 1 and line.startswith(">"):
        return colors["yellow"] | curses.A_BOLD
    if line.startswith(("head:", "base:")):
        return colors["cyan"]
    return 0


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
        colors = palette()
        accent = colors["pink"]
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
                    status = "Curated example. Ratings stay local." if review.get("example") else "Saved locally. Nothing is posted to GitHub."
                elif kind == "error":
                    error = value
                else:
                    status = value
            stdscr.erase()
            height, width = stdscr.getmaxyx()
            put(0, 2, " CC ", accent | curses.A_REVERSE | curses.A_BOLD)
            put(0, 8, "Code coaching", colors["orange"] | curses.A_BOLD)
            put(1, 2, "─" * max(0, width - 5), colors["muted"])
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
                put(3, 2, position, colors["orange"] | curses.A_BOLD)
                put(3, 4 + len(position), "|  " + rating.replace("_", " "), colors["yellow"])
                if review.get("example"):
                    put(4, 2, "CURATED EXAMPLE | Real PR excerpts, not a model result", colors["pink"])
                labels = ["[f] Conversation", "[e] Evidence", "[d] Diff", "[c] Context"] if width >= 80 else ["[f] Talk", "[e] Code", "[d] Diff", "[c] Context"]
                column = 2
                for i, label in enumerate(labels):
                    style = colors["pink"] | curses.A_REVERSE | curses.A_BOLD if i == tab else colors["muted"]
                    put(5, column, " " + label + " ", style)
                    column += len(label) + 3
                put(6, 2, "─" * max(0, width - 5), colors["muted"])
                lines = wrapped(paragraphs(review, selected, tab), width - 6)
            else:
                elapsed = int(time.monotonic() - started)
                lines = wrapped(["Reading and thinking" + "." * (elapsed % 4), "", status,
                                 "", f"{elapsed}s elapsed. Local models can take several minutes.",
                                 "q closes the viewer; the current model request may finish in Ollama."], width - 6)
            visible = max(1, height - 13)
            scroll = max(0, min(scroll, max(0, len(lines) - visible)))
            titles = {point["title"] for point in review["report"]["points"]} if review else set()
            for index, line in enumerate(lines[scroll:scroll + visible]):
                put(7 + index, 3, line, line_style(line, colors, tab, titles))
            put(height - 5, 2, "─" * max(0, width - 5), colors["muted"])
            put(height - 4, 2, status, colors["muted"])
            put(height - 3, 2, "j/k scroll  n/p points  f/e/d/c views  q quit", colors["orange"])
            put(height - 2, 2, "Rate: u useful  i irrelevant  a already understood  x unsupported", colors["yellow"])
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
