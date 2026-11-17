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
