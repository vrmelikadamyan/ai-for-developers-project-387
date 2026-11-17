"""Check a PR's OpenCode attempt budget before allowing a model invocation."""

import json
import os
from urllib.request import Request, urlopen


def workflow_runs(api, repo, token):
    url = f"{api}/repos/{repo}/actions/workflows/opencode.yml/runs"
    seen = set()
    page = 1
    while True:
        request = Request(f"{url}?per_page=100&page={page}", headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        })
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
        runs = payload["workflow_runs"]
        for run in runs:
            if run["id"] in seen:
                raise ValueError("Actions history changed during pagination")
            seen.add(run["id"])
            yield run
        if len(runs) < 100:
            if len(seen) != payload["total_count"]:
                raise ValueError("Actions history is incomplete")
            return
        page += 1


def budget_decision(runs, run_id, attempt, title, repo):
    charged = 0
    current_attempt = None
    for run in runs:
        if (run["display_title"] != title or run["event"] not in {"issue_comment", "pull_request_review_comment"}
                or (run["head_repository"] or {}).get("full_name") != repo):
            continue
        attempts = run.get("run_attempt")
        if type(attempts) is not int or attempts < 1:
            raise ValueError("Actions history is missing an attempt count")
        if run["id"] == run_id:
            current_attempt = attempts
        charged += attempts
        # The latest attempt of another waiting run has not acquired the concurrency group.
        if run["id"] != run_id and run["status"] in {"queued", "pending", "requested", "waiting"}:
            charged -= 1
    if current_attempt != attempt:
        raise ValueError("Actions history does not include this run attempt")
    return "allowed" if charged <= 2 else "limit_exhausted"


if __name__ == "__main__":
    repo = os.environ["GITHUB_REPOSITORY"]
    history = workflow_runs(os.environ["GITHUB_API_URL"], repo, os.environ["GH_TOKEN"])
    print(budget_decision(history, int(os.environ["GITHUB_RUN_ID"]),
                          int(os.environ["GITHUB_RUN_ATTEMPT"]), os.environ["REQUEST_TITLE"], repo))
