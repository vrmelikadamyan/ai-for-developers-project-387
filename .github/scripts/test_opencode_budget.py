import json
import os
import subprocess
import sys
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

from opencode_budget import budget_decision

REPO = "vrmelikadamyan/ai-for-developers-project-387"
TITLE = "OpenCode PR #22"
RUNS_PATH = f"/repos/{REPO}/actions/workflows/opencode.yml/runs?per_page=100&page="
SCRIPT = Path(__file__).with_name("opencode_budget.py")


def run(run_id, status="completed", attempt=1, **fields):
    return {"id": run_id, "run_attempt": attempt, "status": status,
            "conclusion": None, "display_title": TITLE, "event": "issue_comment",
            "head_repository": {"full_name": REPO}, **fields}


class BudgetCommand(unittest.TestCase):
    def check_history(self, snapshots, run_id, attempt=1):
        snapshots = iter(snapshots)
        pages = {}

        class Actions(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                nonlocal pages
                if self.headers.get("Authorization") != "Bearer test-token":
                    self.send_error(401)
                    return
                if self.path == RUNS_PATH + "1":
                    pages = next(snapshots, {})
                page = pages.get(self.path)
                if page is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(page).encode())

        with HTTPServer(("127.0.0.1", 0), Actions) as api:
            thread = Thread(target=api.serve_forever, kwargs={"poll_interval": 0.01})
            thread.start()
            try:
                return subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True,
                                      env={**os.environ, "GH_TOKEN": "test-token", "REQUEST_TITLE": TITLE,
                                           "GITHUB_REPOSITORY": REPO, "GITHUB_RUN_ID": str(run_id),
                                           "GITHUB_RUN_ATTEMPT": str(attempt),
                                           "GITHUB_API_URL": f"http://127.0.0.1:{api.server_port}"})
            finally:
                api.shutdown()
                thread.join()

    def test_failed_and_cancelled_attempts_on_different_pages_exhaust_the_budget(self):
        # Fields as returned for Actions run 44132824083, which failed before invoking the model.
        failed = run(44132824083, conclusion="failure")
        current = run(44132825000, "in_progress", event="pull_request_review_comment", pull_requests=[])
        ignored = [run(i, display_title="Ignored OpenCode comment") for i in range(98)]
        result = self.check_history([{
            RUNS_PATH + "1": {"total_count": 101, "workflow_runs": [current, *ignored, failed]},
            RUNS_PATH + "2": {"total_count": 101, "workflow_runs": [run(44132700000, conclusion="cancelled")]},
        }], current["id"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "limit_exhausted")

    def test_one_new_read_can_recover_a_changing_history_without_charging_any_attempt_twice(self):
        current = run(1, "in_progress")
        previous = run(2, conclusion="failure")
        unrelated = [run(i, display_title="Ignored OpenCode comment") for i in range(3, 101)]
        first_page = {RUNS_PATH + "1": {"total_count": 101, "workflow_runs": [current, previous, *unrelated]}}
        overlap = {**first_page, RUNS_PATH + "2": {"total_count": 101, "workflow_runs": [unrelated[-1]]}}
        short = {RUNS_PATH + "1": {"total_count": 3, "workflow_runs": [current, previous]}}
        stable = {**first_page, RUNS_PATH + "2": {"total_count": 101, "workflow_runs": [run(102, "queued")]}}
        changed_total = {
            RUNS_PATH + "1": {"total_count": 101, "workflow_runs": [current, previous, run(3), *unrelated[1:]]},
            RUNS_PATH + "2": {"total_count": 100, "workflow_runs": []},
        }
        for interrupted in (overlap, short, changed_total):
            result = self.check_history([interrupted, stable], current["id"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "allowed")

    def test_a_complete_history_with_the_wrong_attempt_stops_immediately(self):
        wrong_attempt = {RUNS_PATH + "1": {"total_count": 1, "workflow_runs": [run(1)]}}
        fresh = {RUNS_PATH + "1": {"total_count": 1, "workflow_runs": [run(1, attempt=2)]}}
        result = self.check_history([wrong_attempt, fresh], 1, attempt=2)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_a_persistently_short_or_overlapping_history_cannot_authorize_an_attempt(self):
        current = run(1, "in_progress")
        unrelated = [run(i, display_title="Ignored OpenCode comment") for i in range(2, 101)]
        histories = [
            {RUNS_PATH + "1": {"total_count": 2, "workflow_runs": [current]}},
            {RUNS_PATH + "1": {"total_count": 101, "workflow_runs": [current, *unrelated]},
             RUNS_PATH + "2": {"total_count": 101, "workflow_runs": [unrelated[-1]]}},
        ]
        for history in histories:
            # A third read would allow this attempt, but only one repeat is permitted.
            stable = {RUNS_PATH + "1": {"total_count": 1, "workflow_runs": [current]}}
            result = self.check_history([history, history, stable], current["id"])
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")


class BudgetPolicy(unittest.TestCase):
    def test_pending_requests_wait_their_turn_but_their_previous_attempts_still_count(self):
        current = run(1, "in_progress")
        for waiting in ("queued", "pending", "requested", "waiting"):
            with self.subTest(waiting=waiting):
                retry = run(2, waiting, attempt=2, event="pull_request_review_comment")
                history = [current, retry, run(3, "queued")]
                self.assertEqual(budget_decision(history, 1, 1, TITLE, REPO), "allowed")
                retry["run_attempt"] = 3
                self.assertEqual(budget_decision(history, 1, 1, TITLE, REPO), "limit_exhausted")

    def test_only_comments_on_this_repository_and_pr_share_the_two_attempts(self):
        current = run(1, "in_progress", attempt=2)
        unrelated = [run(2, event="pull_request_review_comment", head_repository={"full_name": "fork/calendar"}),
                     run(3, event="push"), run(4, display_title="OpenCode PR #23")]
        self.assertEqual(budget_decision([current, *unrelated], 1, 2, TITLE, REPO), "allowed")
        current["run_attempt"] = 3
        self.assertEqual(budget_decision([current, *unrelated], 1, 3, TITLE, REPO), "limit_exhausted")

    def test_incomplete_history_cannot_authorize_the_current_attempt(self):
        current = run(1, "in_progress", attempt=2)
        for incomplete in ([], [run(1)], [current, run(2, attempt=None)], [current, run(2, attempt=0)],
                           [current, run(2, attempt=True)]):
            with self.subTest(incomplete=incomplete), self.assertRaises(ValueError):
                budget_decision(incomplete, 1, 2, TITLE, REPO)
