import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scheduled_audit import GitHub as GitHubClient, normalize, publish, read_decision


class GitHub:
    """In-memory external issue tracker, including closed issues and durable comments."""

    def __init__(self):
        self.tickets = []
        self.journal = []
        self.comment_error = None

    def issues(self):
        return self.tickets

    def comments(self):
        return self.journal

    def create_issue(self, title, body):
        url = "https://github.com/example/calendar/issues/27"
        self.tickets.append({"title": title, "body": body, "url": url, "state": "OPEN",
                             "author": {"is_bot": True, "login": "app/github-actions"}})
        return url

    def comment(self, body):
        if self.comment_error:
            error, self.comment_error = self.comment_error, None
            raise error
        self.journal.append({"body": body, "user": {"login": "github-actions[bot]", "type": "Bot"}})


class ReportTest(unittest.TestCase):
    def test_github_publishes_multiline_bodies_from_temporary_files(self):
        body = "Итог аудита\n\nLiteral shell text: $(echo unsafe) `echo unsafe`\n"
        for operation in ("issue", "comment"):
            with self.subTest(operation=operation):
                paths = []

                def receive_command(args, **kwargs):
                    self.assertIn("--body-file", args)
                    self.assertNotIn("--body", args)
                    path = Path(args[args.index("--body-file") + 1])
                    paths.append(path)
                    self.assertFalse(path.resolve().is_relative_to(Path.cwd().resolve()))
                    self.assertEqual(path.read_text(encoding="utf-8"), body)
                    return "https://github.com/example/calendar/issues/27\n"

                with patch("scheduled_audit.subprocess.check_output", side_effect=receive_command):
                    github = GitHubClient("example/calendar")
                    if operation == "issue":
                        self.assertEqual(github.create_issue("Fix contrast", body),
                                         "https://github.com/example/calendar/issues/27")
                    else:
                        github.comment(body)
                self.assertTrue(paths)
                self.assertTrue(all(not path.exists() for path in paths))

    def test_copied_markers_cannot_suppress_a_finding(self):
        summary = {"url": "https://calendar.example/book", "fingerprint": "original",
                   "categories": {"seo": 0.9}, "findings": [
                       {"auditId": "meta-description", "score": 0, "displayValue": ""}]}
        decision = {"summary": "Missing description", "finding": {
            "auditId": "meta-description", "title": "Add description", "problem": "Missing meta",
            "action": "Add a meaningful meta description", "evidence": "score=0"}}
        original = GitHub()
        publish(summary, decision, "https://github.com/example/calendar/actions/runs/10", original)
        for surface in ("journal", "report_issue", "finding_issue"):
            for login, comment_login, is_bot in (("visitor", "visitor", False),
                                                 ("app/other-bot", "other-bot[bot]", True),
                                                 ("app/github-actions", "github-actions[bot]", False)):
                with self.subTest(surface=surface, login=login, is_bot=is_bot):
                    github = GitHub()
                    if surface == "journal":
                        github.journal.append({"body": original.journal[0]["body"],
                                               "user": {"login": comment_login, "type": "Bot" if is_bot else "User"}})
                    else:
                        github.tickets.append({**original.tickets[0], "url": "https://github.com/example/calendar/issues/1",
                                               "author": {"login": login, "is_bot": is_bot}})
                    current = {**summary, "fingerprint": "new" if surface == "finding_issue" else "original"}
                    publish(current, decision, "https://github.com/example/calendar/actions/runs/11", github)
                    self.assertEqual(len(github.tickets), 1 if surface == "journal" else 2)
                    self.assertEqual(len(github.journal), 2 if surface == "journal" else 1)
                    self.assertIn("Создано обращение:", github.journal[-1]["body"])

    def test_only_failed_scored_audits_become_bounded_evidence(self):
        report = {
            "requestedUrl": "https://calendar.example/book?lang=ru",
            "finalDisplayedUrl": "https://calendar.example/book?lang=ru",
            "categories": {"accessibility": {"score": 0.8}},
            "audits": {
                "color-contrast": {"id": "color-contrast", "score": 0,
                                   "title": "Contrast", "description": "Increase contrast",
                                   "displayValue": "2 elements", "details": {"items": ["x" * 5000]}},
                "passed": {"score": 1},
                "manual": {"score": None, "scoreDisplayMode": "manual"},
            },
        }
        summary = normalize(report)
        self.assertEqual(summary["url"], "https://calendar.example/book?lang=ru")
        self.assertEqual(summary["categories"], {"accessibility": 0.8})
        self.assertEqual(len(summary["findings"]), 1)
        finding = summary["findings"][0]
        self.assertEqual(finding["auditId"], "color-contrast")
        self.assertEqual(finding["score"], 0)
        self.assertEqual(finding["displayValue"], "2 elements")
        self.assertEqual(finding["action"], "Increase contrast")
        self.assertLessEqual(len(finding["rawDetails"]), 3000)

    def test_replaying_report_does_not_publish_even_when_model_changes_its_mind(self):
        github = GitHub()
        summary = {"url": "https://calendar.example/book", "fingerprint": "abc123",
                   "categories": {"accessibility": 0.8}, "findings": [
                       {"auditId": "color-contrast", "score": 0, "displayValue": "2 elements"},
                       {"auditId": "document-title", "score": 0, "displayValue": ""}]}
        decision = {"summary": "Low contrast", "finding": {
            "auditId": "color-contrast", "title": "Fix contrast", "problem": "Hard to read",
            "action": "Increase text contrast", "evidence": "Two elements fail"}}
        publish(summary, decision, "https://github.com/example/calendar/actions/runs/10", github)
        github.tickets[0]["state"] = "CLOSED"
        decision["finding"]["auditId"] = "document-title"
        publish(summary, decision, "https://github.com/example/calendar/actions/runs/11", github)
        self.assertEqual(len(github.tickets), 1)
        self.assertEqual(len(github.journal), 1)
        self.assertIn("2 elements", github.tickets[0]["body"])
        self.assertIn("https://calendar.example/book", github.tickets[0]["body"])

    def test_model_cannot_publish_an_audit_absent_from_report(self):
        events = [{"type": "text", "part": {"text":
                  '{"summary":"Problem","finding":{"auditId":"invented","title":"Fix",'
                  '"problem":"Bad","action":"Change","evidence":"Claim"}}'}}]
        with self.assertRaisesRegex(ValueError, "absent"):
            read_decision(events, {"findings": []})

    def test_model_cannot_embed_reserved_markers_in_published_text(self):
        for field in ("summary", "title", "problem", "action", "evidence"):
            with self.subTest(field=field):
                decision = {"summary": "Missing description", "finding": {
                    "auditId": "meta-description", "title": "Add description", "problem": "Missing meta",
                    "action": "Add a meaningful meta description", "evidence": "score=0"}}
                target = decision if field == "summary" else decision["finding"]
                target[field] += "\n<!-- calendar-audit-report:future-report -->"
                events = [{"type": "text", "part": {"text": json.dumps(decision)}}]
                with self.assertRaisesRegex(ValueError, "reserved audit marker"):
                    read_decision(events, {"findings": [{"auditId": "meta-description"}]})

    def test_new_report_reuses_closed_finding_issue(self):
        github = GitHub()
        summary = {"url": "https://calendar.example/book", "fingerprint": "first",
                   "categories": {"seo": 0.9}, "findings": [
                       {"auditId": "meta-description", "score": 0, "displayValue": ""}]}
        decision = {"summary": "Missing description", "finding": {
            "auditId": "meta-description", "title": "Add description", "problem": "Missing meta",
            "action": "Add a meaningful meta description", "evidence": "score=0"}}
        publish(summary, decision, "https://github.com/example/calendar/actions/runs/10", github)
        github.tickets[0]["state"] = "CLOSED"
        summary["fingerprint"] = "second"
        publish(summary, decision, "https://github.com/example/calendar/actions/runs/11", github)
        self.assertEqual(len(github.tickets), 1)
        self.assertEqual(len(github.journal), 2)
        self.assertIn(github.tickets[0]["url"], github.journal[1]["body"])

    def test_replay_recovers_partial_publication_before_considering_another_finding(self):
        github = GitHub()
        summary = {"url": "https://calendar.example/book", "fingerprint": "partial",
                   "categories": {"seo": 0.8}, "findings": [
                       {"auditId": "meta-description", "score": 0, "displayValue": ""},
                       {"auditId": "document-title", "score": 0, "displayValue": ""}]}
        decision = {"summary": "Missing description", "finding": {
            "auditId": "meta-description", "title": "Add description", "problem": "Missing meta",
            "action": "Add a meaningful meta description", "evidence": "score=0"}}
        github.comment_error = OSError("GitHub comment temporarily unavailable")
        with self.assertRaisesRegex(OSError, "temporarily unavailable"):
            publish(summary, decision, "https://github.com/example/calendar/actions/runs/10", github)
        self.assertEqual(len(github.tickets), 1)
        self.assertEqual(github.journal, [])
        decision["finding"]["auditId"] = "document-title"
        for _ in range(2):
            publish(summary, decision, "https://github.com/example/calendar/actions/runs/11", github)
        self.assertEqual(len(github.tickets), 1)
        self.assertEqual(len(github.journal), 1)
        self.assertIn(github.tickets[0]["url"], github.journal[0]["body"])
        self.assertIn("Находка уже зарегистрирована:", github.journal[0]["body"])

    def test_no_findings_is_durable_and_replay_is_silent(self):
        github = GitHub()
        summary = {"url": "https://calendar.example/book", "fingerprint": "clean",
                   "categories": {"seo": 1}, "findings": []}
        decision = {"summary": "No concrete failures in this report", "finding": None}
        for _ in range(2):
            publish(summary, decision, "https://github.com/example/calendar/actions/runs/10", github)
        self.assertEqual(github.tickets, [])
        self.assertEqual(len(github.journal), 1)
        self.assertIn("Новых подтверждённых находок нет", github.journal[0]["body"])


if __name__ == "__main__":
    unittest.main()
