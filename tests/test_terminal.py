"""Exercise the real curses process in a pseudo-terminal."""
import fcntl
import json
import os
import pty
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from pathlib import Path


class TerminalTests(unittest.TestCase):
    def test_navigation_resize_and_quit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            review = {"id": "terminal-test", "packet": {
                "id": "fixture", "pr": {"number": 1, "title": "Terminal test", "headRefOid": "abc"},
                "merge_base": "def", "diff": "diff --git a/a.rb b/a.rb\n+ added_line",
                "coverage_notes": ["Test fixture only."], "files": []},
                "report": {"status": "no_feedback", "summary": "No worthwhile point.", "points": []}}
            source = root / "review.json"
            source.write_text(json.dumps(review))
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
            proc = subprocess.Popen([sys.executable, "-m", "cc", "--open", str(source),
                                     "--state-dir", str(root)], stdin=slave, stdout=slave, stderr=slave,
                                    env={**os.environ, "TERM": "xterm-256color"})
            os.close(slave)
            def expect(text):
                data = b""
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if select.select([master], [], [], 0.1)[0]:
                        data += os.read(master, 65536)
                        if text.encode() in data:
                            return
                self.fail(f"Missing terminal text: {text}. Output: {data!r}")
            try:
                expect("No feedback worth raising")
                os.write(master, b"d")
                expect("added_line")
                os.write(master, b"uiaxc")
                expect("Scope of this assessment")
                self.assertEqual(list(root.glob("*.ratings.json")), [])
                fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 12, 40, 0, 0))
                proc.send_signal(signal.SIGWINCH)
                expect("Resize to at least")
                fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
                proc.send_signal(signal.SIGWINCH)
                expect("Scope of this assessment")
                os.write(master, b"q")
                deadline = time.monotonic() + 5
                while proc.poll() is None and time.monotonic() < deadline:
                    if select.select([master], [], [], 0.1)[0]:
                        try:
                            os.read(master, 65536)
                        except OSError:
                            break
                self.assertEqual(proc.wait(timeout=1), 0)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                os.close(master)
