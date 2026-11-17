import unittest

from scheduled_audit import normalize, publish, read_decision


class GitHub:
    """In-memory external issue tracker, including closed issues and durable comments."""

    def __init__(self):
        self.tickets = []
        self.journal = []

    def issues(self):
        return self.tickets

    def comments(self):
        return self.journal

    def create_issue(self, title, body):
        url = "https://github.com/example/calendar/issues/27"
        self.tickets.append({"title": title, "body": body, "url": url, "state": "OPEN"})
        return url

    def comment(self, body):
        self.journal.append({"body": body})


class ReportTest(unittest.TestCase):
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
