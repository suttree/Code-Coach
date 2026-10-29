import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qq.core import QQError, analyse, collect, correct_citations, filter_points, parse_pr, safe_path, validate
from qq.tui import paragraphs, wrapped


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
            with self.assertRaises(QQError):
                validate(self.report, self.packet, resolve_citations=True)

    def test_no_feedback_is_valid(self):
        validate({"status": "no_feedback", "summary": "No worthwhile discussion in this change.", "points": []}, self.packet)

    def test_missing_context_is_distinct(self):
        validate({"status": "needs_context", "summary": "Need caller's loading behaviour.", "points": []}, self.packet)

    def test_rejects_more_than_two(self):
        self.report["points"] *= 3
        with self.assertRaises(QQError):
            validate(self.report, self.packet)

    def test_rejects_fabricated_evidence(self):
        for key, value in [("path", "other.rb"), ("line", 3), ("quote", "  invented"), ("side", "base")]:
            report = copy.deepcopy(self.report)
            report["points"][0]["evidence"][0][key] = value
            with self.subTest(key=key), self.assertRaises(QQError):
                validate(report, self.packet)

    def test_rejects_inconsistent_status(self):
        self.report["status"] = "no_feedback"
        with self.assertRaises(QQError):
            validate(self.report, self.packet)

    def test_rejects_missing_explanation(self):
        self.report["points"][0]["why"] = " "
        with self.assertRaises(QQError):
            validate(self.report, self.packet)

    def test_relevance_check_can_discard_every_point(self):
        checked = filter_points(self.report, {"decisions": [
            {"index": 0, "keep": False, "kind": "discussion", "reason": "The impact is overstated."}]})
        self.assertEqual(checked["status"], "no_feedback")
        self.assertEqual(checked["points"], [])
        self.assertEqual(len(self.report["points"]), 1)

    def test_relevance_check_can_correct_kind_without_rewriting_claims(self):
        checked = filter_points(self.report, {"decisions": [
            {"index": 0, "keep": True, "kind": "strength", "reason": "A deliberate decision."}]})
        self.assertEqual(checked["points"][0]["kind"], "strength")
        self.assertEqual(checked["points"][0]["observation"], self.report["points"][0]["observation"])

    def test_missing_relevance_decision_is_an_error(self):
        with self.assertRaises(QQError):
            filter_points(self.report, {"decisions": []})

    def test_analysis_runs_final_check_before_accepting_points(self):
        self.packet.update(pr={"title": "Example"}, coverage_notes=[])
        verdict = {"decisions": [{"index": 0, "keep": False, "kind": "discussion", "reason": "Unsupported impact."}]}
        audit = {}
        with patch("qq.core.model_json", side_effect=[self.report, verdict]) as model:
            result = analyse(self.packet, "local-model", "http://127.0.0.1:11434", audit=audit)
        self.assertEqual(model.call_count, 2)
        self.assertEqual(result["status"], "no_feedback")
        self.assertEqual(len(audit["draft"]["points"]), 1)

    def test_corrects_changed_quote_characters_before_relevance_check(self):
        source = '  document.querySelector(".profile-tabs [aria-current]")?.scrollIntoView({ block: "nearest", inline: "nearest" });'
        self.packet["files"][0]["text"] = "// Tabs\n// Keep selected tab visible\n" + source
        self.packet.update(pr={"title": "Example"}, coverage_notes=[])
        citation = self.report["points"][0]["evidence"][0]
        citation.update(line=2, quote=source.strip().replace('"', "'"))
        original = copy.deepcopy(self.report)
        # Quotation marks inside code are not safe to change by fuzzy matching.
        with self.assertRaises(QQError):
            validate(copy.deepcopy(self.report), self.packet, resolve_citations=True)
        correction = {"evidence": [[dict(citation, line=3, quote=source)]]}
        verdict = {"decisions": [{"index": 0, "keep": False, "kind": "discussion", "reason": "Routine UI change."}]}
        audit = {}
        with patch("qq.core.model_json", side_effect=[self.report, correction, verdict]) as model:
            result = analyse(self.packet, "local-model", "http://127.0.0.1:11434", audit=audit)
        self.assertEqual(model.call_count, 3)
        self.assertEqual(result["status"], "no_feedback")
        self.assertEqual(audit["raw_draft"], original)
        self.assertEqual(self.report, original)
        corrected = copy.deepcopy(audit["draft"])
        self.assertEqual(corrected["points"][0]["evidence"][0]["quote"], source)
        corrected["points"][0]["evidence"] = original["points"][0]["evidence"]
        self.assertEqual(corrected, original)

    def test_bad_correction_stops_after_one_attempt(self):
        self.report["points"][0]["evidence"][0]["quote"] = "invented"
        correction = {"evidence": [self.report["points"][0]["evidence"]]}
        audit = {}
        with patch("qq.core.model_json", side_effect=[self.report, correction]) as model:
            with self.assertRaisesRegex(QQError, "after one correction attempt"):
                analyse(self.packet, "local-model", "http://127.0.0.1:11434", audit=audit)
        self.assertEqual(model.call_count, 2)
        self.assertEqual(audit["citation_correction"], correction)
        self.assertNotIn("decisions", audit)

    def test_correction_cannot_drop_points_citations_or_change_files(self):
        citation = self.report["points"][0]["evidence"][0]
        for evidence in [[], [[]], [[dict(citation, path="other.rb")]],
                         [[dict(citation, side="base")]], [[citation, citation]],
                         [[dict(citation, quote="invented")]], [[dict(citation, line=True)]]]:
            with self.subTest(evidence=evidence), self.assertRaises(QQError):
                correct_citations(self.report, {"evidence": evidence}, self.packet)

    def test_malformed_draft_does_not_trigger_citation_retry(self):
        del self.report["points"][0]["why"]
        with patch("qq.core.model_json", return_value=self.report) as model:
            with self.assertRaises(QQError):
                analyse(self.packet, "local-model", "http://127.0.0.1:11434")
        self.assertEqual(model.call_count, 1)

    def test_cli_preserves_failed_draft_without_saving_a_review(self):
        import contextlib
        import io
        from qq.__main__ import main
        self.packet["id"] = "citation-failure"
        self.report["points"][0]["evidence"][0]["quote"] = "invented"
        correction = {"evidence": [self.report["points"][0]["evidence"]]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet_path = root / "input.json"
            packet_path.write_text(json.dumps(self.packet))
            stderr = io.StringIO()
            with patch("sys.argv", ["qq", "--packet", str(packet_path), "--state-dir", str(root), "--json"]), \
                    patch("qq.core.model_json", side_effect=[self.report, correction]), \
                    contextlib.redirect_stderr(stderr):
                self.assertEqual(main(), 1)
            failures = list(root.glob("*.failure.json"))
            self.assertEqual(len(failures), 1)
            failure = json.loads(failures[0].read_text())
            self.assertEqual(failure["assessment"]["raw_draft"], self.report)
            self.assertEqual(failure["assessment"]["citation_correction"], correction)
            self.assertIn(str(failures[0]), stderr.getvalue())
            self.assertEqual(list(root.glob("*.review.json")), [])
            self.assertTrue((root / "citation-failure.packet.json").exists())

    def test_model_failure_is_not_no_feedback(self):
        with patch("qq.core.urlopen", side_effect=OSError("model unavailable")):
            with self.assertRaisesRegex(QQError, "did not return a usable result"):
                analyse(self.packet, "local-model", "http://127.0.0.1:11434")

    def test_rejects_remote_model_endpoint(self):
        with self.assertRaises(QQError):
            analyse(self.packet, "any", "https://remote.example")

    def test_pr_url_validation(self):
        self.assertEqual(parse_pr("https://github.com/suttree/commonground/pull/11"), ("suttree/commonground", 11))
        for url in ["https://evil.test/a/b/pull/1", "https://github.com/a/b/pull/1;rm", "--help"]:
            with self.assertRaises(QQError):
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
            from qq.core import run as real_run
            def fake_run(*args, **kwargs):
                return json.dumps(meta) if args[0] == "gh" else real_run(*args, **kwargs)
            with patch("qq.core.run", fake_run):
                packet = collect(meta["url"], repo)
            self.assertIn("def historical", packet["files"][0]["text"])
            self.assertGreater(packet["files"][0]["start_line"], 1)
            self.assertNotIn("UNCOMMITTED", json.dumps(packet))
            self.assertNotIn("DO_NOT_INCLUDE", json.dumps(packet))
            self.assertEqual((repo / "model.rb").read_text(), "UNCOMMITTED CURRENT WORK\n")
            self.assertEqual(packet["merge_base"], base)


if __name__ == "__main__":
    unittest.main()
