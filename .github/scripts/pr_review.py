"""Build the read-only evidence packet for an independent PR review."""

import json
import os
import re
import subprocess
import sys
import time
from urllib.parse import urlsplit


def eligible(pr, repo, sha):
    author = pr["user"]
    human = author["type"] == "User" and pr["author_association"] in {"OWNER", "MEMBER", "COLLABORATOR"}
    app = author["type"] == "Bot" and author["login"] == "opencode-agent[bot]"
    return (pr["state"] == "open" and (pr["head"]["repo"] or {}).get("full_name") == repo
            and pr["head"]["sha"] == sha and (human or app))


# Consume entire URLs and qualified references so their fragments cannot become local #numbers.
REFERENCES = re.compile(r"https?://[^\s<>()[\],]+|(?<![\w./#])"
                        r"(?:(?P<repo>[\w.-]+/[\w.-]+))?#(?P<start>[1-9]\d{0,9})"
                        r"(?:\s*[–—-]\s*#?(?P<end>[1-9]\d{0,9}))?", re.I)


def clipped(value, size):
    value = value or ""
    return value if len(value) <= size else value[:size] + f"\n[… {len(value)-size} characters omitted]"


def comment(item, size=2500):
    return {"author": item["user"]["login"], "association": item["author_association"],
            "body": clipped(item["body"], size), "url": item["html_url"]}


def linked_evidence(repo, body, get):
    issues, comments = {}, {}
    # In a Markdown link, the destination (not the display label) identifies the issue.
    body = re.sub(r"\[[^]\n]*\]\((https?://[^)\s]+)\)", r" \1 ", body, flags=re.I)
    for match in REFERENCES.finditer(body):
        if match["start"]:
            if match["repo"] and match["repo"].lower() != repo.lower():
                continue
            first, last = int(match["start"]), int(match["end"] or match["start"])
            issues[first] = None
            if first < last:
                issues.update(dict.fromkeys(range(first + 1, min(last, first + 15) + 1)))
                issues[last] = None
            continue
        token = match[0].rstrip(".,;:")
        url = urlsplit(token)
        local = re.fullmatch("/" + re.escape(repo) + r"/(?:issues|pull)/([1-9]\d{0,9})/?", url.path, re.I)
        if url.netloc.lower() != "github.com" or not local:
            continue
        issues[int(local[1])] = None
        anchor = re.fullmatch(r"issuecomment-([1-9]\d{0,19})", url.fragment)
        if anchor:
            comments[anchor[1]] = token

    packet = {"issues": [], "linked_comments": [], "unavailable": []}
    for number in list(issues)[:16]:
        issue = get(f"issues/{number}")
        if issue is None:
            packet["unavailable"].append(f"#{number}")
        else:
            packet["issues"].append({"number": number, "title": issue["title"],
                                     "body": clipped(issue["body"], 20000)})
    for cid, url in list(comments.items())[:8]:
        item = get(f"issues/comments/{cid}")
        # A real comment from another issue is not approval of the linked issue.
        if item is None or item["html_url"].lower() != url.lower():
            packet["unavailable"].append(url)
        else:
            packet["linked_comments"].append(comment(item, 5000))
    if len(issues) > 16 or len(comments) > 8:
        packet["unavailable"].append("Link limit reached (16 issues / 8 comments).")
    return packet


def api(repo, path, *, pages=False, diff=False, optional=False):
    cmd = ["gh", "api", f"repos/{repo}/{path}"]
    if pages:
        cmd += ["--paginate", "--slurp"]
    if diff:
        cmd += ["-H", "Accept: application/vnd.github.diff"]
    response = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if response.returncode:
        if optional and "(HTTP 404)" in response.stderr:
            return None
        raise RuntimeError(f"GitHub could not read {path}: {response.stderr.strip()}")
    if diff:
        return response.stdout
    data = json.loads(response.stdout)
    return [item for page in data for item in page] if pages else data


def ci_snapshot(repo, sha):
    # The CI push run can predate the PR; its browser run starts when the PR opens.
    # Include both once complete, or label missing/pending evidence after six minutes.
    expected = {".github/workflows/ci.yml", ".github/workflows/pr-browser.yml"}
    deadline = time.monotonic() + 360
    while True:
        runs = api(repo, f"actions/runs?head_sha={sha}&per_page=100")["workflow_runs"]
        latest = {}
        for run in runs:
            latest.setdefault(run["path"], run)  # newest first
        if all(latest.get(path, {}).get("status") == "completed" for path in expected):
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(15)
    return {
        "missing_workflows": sorted(expected - latest.keys()),
        "workflows": [{key: run[key] for key in ("name", "status", "conclusion", "html_url")}
                      for run in latest.values()],
        "check_runs": [{key: check[key] for key in ("name", "status", "conclusion", "html_url")}
                       for check in api(repo, f"commits/{sha}/check-runs?per_page=100")["check_runs"]],
        "statuses": [{key: item[key] for key in ("context", "state", "target_url")}
                     for item in api(repo, f"commits/{sha}/status?per_page=100")["statuses"]],
    }


def collect(repo, number, sha, base, pr):
    def history(path, extra=()):
        items = api(repo, path + "?per_page=100", pages=True)
        return {"count": len(items), "recent": [
            {**comment(item), **{key: item.get(key) for key in extra}} for item in items[-15:]]}

    return {
        "pr": {"number": number, "base_sha": base, "head_sha": sha, "title": pr["title"],
               "body": clipped(pr["body"], 12000), "author": pr["user"]["login"]},
        "links": linked_evidence(repo, pr["body"] or "", lambda path: api(repo, path, optional=True)),
        "discussion": history(f"issues/{number}/comments"),
        "reviews": history(f"pulls/{number}/reviews", ["state", "commit_id"]),
        "inline_comments": history(f"pulls/{number}/comments", ["path", "line", "commit_id"]),
        "diff": clipped(api(repo, f"compare/{base}...{sha}", diff=True), 120000),
        "ci_for_head": ci_snapshot(repo, sha),
    }


def main():
    repo, sha, base, number = (os.environ[key] for key in
                               ("GITHUB_REPOSITORY", "HEAD_SHA", "BASE_SHA", "PR_NUMBER"))
    if not (re.fullmatch(r"[1-9]\d*", number) and
            all(re.fullmatch(r"[0-9a-f]{40}", rev) for rev in (sha, base))):
        raise ValueError("Invalid PR number or SHA in GitHub event")
    pr = api(repo, f"pulls/{number}")
    if sys.argv[1] == "eligible":
        print("eligible=" + str(eligible(pr, repo, sha)).lower())
    elif sys.argv[1] == "context" and eligible(pr, repo, sha):
        json.dump(collect(repo, number, sha, base, pr), sys.stdout, ensure_ascii=False)
    else:
        raise SystemExit("PR no longer eligible")


if __name__ == "__main__":
    main()
