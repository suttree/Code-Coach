import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from coach.core import CoachError, analyse, collect, parse_pr, safe_path, validate
from coach.tui import paragraphs, wrapped


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.packet = {"files": [{"path": "app/a.rb", "side": "head", "start_line": 1,
                                  "text": "class A\n  send_email\nend"}]}
        self.report = {"status": "feedback", "summary": "Discuss delivery.", "points": [{
            "title": "Delivery", "kind": "discussion", "timing": "later",
            "observation": "Email runs inline.", "why": "The request waits for delivery.",
            "question": "What latency is acceptable?", "principle": "Bound request work.",
            "assumptions": ["Delivery time has not been measured."],
            "evidence": [{"path": "app/a.rb", "side": "head", "line": 2, "quote": "  send_email"}]}]}

    def test_valid_evidence(self):
        self.assertEqual(validate(self.report, self.packet), self.report)

    def test_resolves_unique_quote_to_real_source_line(self):
        citation = self.report["points"][0]["evidence"][0]
        citation.update(line=1, quote="send_email")
        validate(self.report, self.packet, resolve_citations=True)
        self.assertEqual(citation["line"], 2)
        self.assertEqual(citation["quote"], "  send_email")

    def test_does_not_resolve_ambiguous_or_invented_quotes(self):
        self.packet["files"][0]["text"] += "\n  send_email"
        citation = self.report["points"][0]["evidence"][0]
        for quote in ["send_email", "imaginary_method"]:
            citation.update(line=1, quote=quote)
            with self.assertRaises(CoachError):
                validate(self.report, self.packet, resolve_citations=True)

    def test_no_feedback_is_valid(self):
        validate({"status": "no_feedback", "summary": "No worthwhile discussion in this change.", "points": []}, self.packet)

    def test_missing_context_is_distinct(self):
        validate({"status": "needs_context", "summary": "Need caller's loading behaviour.", "points": []}, self.packet)

    def test_rejects_more_than_two(self):
        self.report["points"] *= 3
        with self.assertRaises(CoachError):
            validate(self.report, self.packet)

    def test_rejects_fabricated_evidence(self):
        for key, value in [("path", "other.rb"), ("line", 3), ("quote", "  invented"), ("side", "base")]:
            report = copy.deepcopy(self.report)
            report["points"][0]["evidence"][0][key] = value
            with self.subTest(key=key), self.assertRaises(CoachError):
                validate(report, self.packet)

    def test_rejects_inconsistent_status(self):
        self.report["status"] = "no_feedback"
        with self.assertRaises(CoachError):
            validate(self.report, self.packet)

    def test_rejects_missing_explanation(self):
        self.report["points"][0]["why"] = " "
        with self.assertRaises(CoachError):
            validate(self.report, self.packet)

    def test_model_failure_is_not_no_feedback(self):
        with patch("coach.core.urlopen", side_effect=OSError("model unavailable")):
            with self.assertRaisesRegex(CoachError, "did not return a usable result"):
                analyse(self.packet, "local-model", "http://127.0.0.1:11434")

    def test_rejects_remote_model_endpoint(self):
        with self.assertRaises(CoachError):
            analyse(self.packet, "any", "https://remote.example")

    def test_pr_url_validation(self):
        self.assertEqual(parse_pr("https://github.com/suttree/commonground/pull/11"), ("suttree/commonground", 11))
        for url in ["https://evil.test/a/b/pull/1", "https://github.com/a/b/pull/1;rm", "--help"]:
            with self.assertRaises(CoachError):
                parse_pr(url)

    def test_excludes_sensitive_paths(self):
        for path in [".env.production", "config/master.key", "config/credentials.yml.enc", "../outside.rb", "/tmp/out.rb"]:
            self.assertFalse(safe_path(path))

    def test_terminal_control_characters_removed(self):
        self.assertNotIn("\x1b", "".join(wrapped(["hello\x1b[2J"], 80)))

    def test_empty_state_and_missing_context_copy(self):
        review = {"packet": {}, "report": {"status": "no_feedback", "summary": "Small change.", "points": []}}
        self.assertEqual(paragraphs(review, 0, 0)[0], "No feedback worth raising")
        review["report"]["status"] = "needs_context"
        self.assertEqual(paragraphs(review, 0, 0)[0], "More context needed")


class HistoricalContextTests(unittest.TestCase):
    def test_uses_historical_head_and_merge_base_without_touching_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            def git(*args):
                return subprocess.check_output(["git", "-C", directory, *args], text=True).strip()
            git("init", "-q")
            git("config", "user.email", "test@example.com")
            git("config", "user.name", "Test")
            git("remote", "add", "origin", "https://github.com/example/project.git")
            padding = "# Earlier code in this historical file.\n" * 150
            (repo / "model.rb").write_text(padding + "class Model\nend\n")
            git("add", ".")
            git("commit", "-qm", "base")
            base = git("rev-parse", "HEAD")
            (repo / "model.rb").write_text(padding + "class Model\n  def historical; end\nend\n")
            git("commit", "-qam", "feature")
            head = git("rev-parse", "HEAD")
            (repo / "model.rb").write_text("UNCOMMITTED CURRENT WORK\n")
            (repo / ".env").write_text("DO_NOT_INCLUDE=secret\n")
            meta = {"headRefOid": head, "baseRefOid": base, "number": 1,
                    "title": "Test", "body": "", "url": "https://github.com/example/project/pull/1"}
            from coach.core import run as real_run
            def fake_run(*args, **kwargs):
                return json.dumps(meta) if args[0] == "gh" else real_run(*args, **kwargs)
            with patch("coach.core.run", fake_run):
                packet = collect(meta["url"], repo)
            self.assertIn("def historical", packet["files"][0]["text"])
            self.assertGreater(packet["files"][0]["start_line"], 1)
            self.assertNotIn("UNCOMMITTED", json.dumps(packet))
            self.assertNotIn("DO_NOT_INCLUDE", json.dumps(packet))
            self.assertEqual((repo / "model.rb").read_text(), "UNCOMMITTED CURRENT WORK\n")
            self.assertEqual(packet["merge_base"], base)


if __name__ == "__main__":
    unittest.main()
