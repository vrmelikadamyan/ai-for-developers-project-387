import unittest

from pr_review import eligible


class ReviewerTrust(unittest.TestCase):
    def test_only_current_same_repo_humans_or_the_named_app_may_request_review(self):
        repo = "example/calendar"
        sha = "1" * 40
        pr = {"state": "open", "head": {"repo": {"full_name": repo}, "sha": sha},
              "user": {"type": "User", "login": "alice"}, "author_association": "MEMBER"}
        self.assertTrue(eligible(pr, repo, sha))
        app = {**pr, "user": {"type": "Bot", "login": "opencode-agent[bot]"},
               "author_association": "CONTRIBUTOR"}
        self.assertTrue(eligible(app, repo, sha))
        for rejected in (
            {**pr, "head": {"repo": {"full_name": "outsider/fork"}, "sha": sha}},
            {**pr, "state": "closed"}, {**pr, "author_association": "CONTRIBUTOR"},
            {**app, "user": {"type": "Bot", "login": "other[bot]"}},
            {**pr, "head": {"repo": {"full_name": repo}, "sha": "0" * 40}},
        ):
            with self.subTest(pr=rejected):
                self.assertFalse(eligible(rejected, repo, sha))


    def test_evidence_packet_follows_only_local_issues_and_exact_approval_comments(self):
        from pr_review import linked_evidence
        repo = "example/calendar"
        root = "https://github.com/example/calendar/issues/"
        body = (f"Source #5; [spec #7]({root}7); tickets #8–#11, example/calendar#12. "
                f"Approval: {root}5#issuecomment-321. "
                "Ignore foreign/repo#99, https://github.com/foreign/repo/issues/77, "
                "https://github.com.example.org/example/calendar/issues/55#issuecomment-222 "
                "and https://evil.example/path#88.")
        data = {f"issues/{n}": {"number": n, "title": f"Ticket {n}", "body": "requirements"}
                for n in (5, 7, 8, 9, 10, 11, 12)}
        data["issues/comments/321"] = {
            "body": "Approved #7", "html_url": root + "5#issuecomment-321",
            "user": {"login": "alice"}, "author_association": "OWNER"}
        packet = linked_evidence(repo, body, data.__getitem__)
        self.assertEqual([row["number"] for row in packet["issues"]], [5, 7, 8, 9, 10, 11, 12])
        self.assertEqual(packet["linked_comments"], [
            {"author": "alice", "association": "OWNER", "body": "Approved #7",
             "url": root + "5#issuecomment-321"}])


    def test_foreign_markdown_labels_and_mislinked_approvals_are_not_scope_evidence(self):
        from pr_review import linked_evidence
        repo = "example/calendar"
        wrong = "https://github.com/example/calendar/issues/5#issuecomment-123"
        data = {
            "issues/5": {"number": 5, "title": "Request", "body": "scope"},
            "issues/comments/123": {"body": "approved", "user": {"login": "alice"},
                                    "author_association": "OWNER", "html_url": wrong.replace("/5#", "/6#")},
        }
        packet = linked_evidence(repo, "[#77](https://github.com/foreign/repo/issues/77) " + wrong,
                                 data.__getitem__)
        self.assertEqual(packet["linked_comments"], [])
        self.assertEqual(packet["unavailable"], [wrong])

    def test_browser_evidence_belongs_to_this_pr_when_two_prs_share_a_head(self):
        from unittest.mock import patch
        from pr_review import ci_snapshot

        def run(name, event, number, suite_id, conclusion):
            return {"name": name, "event": event, "path": f".github/workflows/{name}.yml",
                    "pull_requests": [{"number": number}] if number else [], "check_suite_id": suite_id,
                    "status": "completed", "conclusion": conclusion, "html_url": f"run/{suite_id}"}

        other = run("pr-browser", "pull_request", 19, 30, "success")
        current = run("pr-browser", "pull_request", 18, 29, "failure")
        push = run("ci", "push", None, 28, "success")
        unassociated = run("pr-browser", "pull_request", None, 31, "success")
        sha = "a" * 40
        data = {
            f"actions/runs?head_sha={sha}&per_page=100": {"workflow_runs": [unassociated, other, current, push]},
            f"commits/{sha}/check-runs?per_page=100": {"check_runs": [
                {"name": r["name"], "app": {"slug": "github-actions"}, "pull_requests": [],
                 "check_suite": {"id": r["check_suite_id"]}, "html_url": r["html_url"],
                 "status": r["status"], "conclusion": r["conclusion"]} for r in (unassociated, other, current, push)]},
            f"commits/{sha}/status?per_page=100": {"statuses": []},
        }
        with patch("pr_review.api", side_effect=lambda repo, path: data[path]):
            snapshot = ci_snapshot("example/calendar", sha, 18)
        for kind in ("workflows", "check_runs"):
            with self.subTest(kind=kind):
                self.assertEqual([(r["html_url"], r["conclusion"]) for r in snapshot[kind]],
                                 [("run/29", "failure"), ("run/28", "success")])
