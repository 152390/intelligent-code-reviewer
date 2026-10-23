"""Stage 1 - Change ingestion (Section 3.3).

Receives the diff, the changed files and the pull request description.
Two entry points:
  * from_git(): compute the diff between two commits of a local repository
    (this is what the GitHub Action uses after checking out the PR).
  * from_diff_text(): parse a unified diff you already have (used in evaluation).
"""
from __future__ import annotations
import json
import os
import re
import subprocess
from .models import Hunk, ChangeSet

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
SUPPORTED_EXT = {".py": "python", ".java": "java"}   # scope: Python and Java (Section 3.5)


def language_of(path: str) -> str | None:
    return SUPPORTED_EXT.get(os.path.splitext(path)[1].lower())


def parse_unified_diff(text: str, max_hunk_lines: int = 80) -> list[Hunk]:
    """Turn unified-diff text into Hunk objects with correct new-file line numbers.

    Very large hunks are split into pieces of at most `max_hunk_lines` added lines
    (Section 3.6: 'very large changes are either excluded or split')."""
    hunks: list[Hunk] = []
    current_file = None
    hunk = None
    new_line = 0
    for line in text.splitlines():
        if line.startswith("diff --git"):
            current_file, hunk = None, None
        elif line.startswith("+++ "):
            path = line[4:].strip().split("\t")[0]
            current_file = None if path == "/dev/null" else (path[2:] if path.startswith("b/") else path)
            hunk = None
        elif line.startswith("--- ") and hunk is None:
            continue
        elif (m := HUNK_RE.match(line)) and current_file:
            new_line = int(m.group(3))
            hunk = Hunk(file=current_file, header=line, raw=line + "\n")
            hunks.append(hunk)
        elif hunk is not None:
            hunk.raw += line + "\n"
            if line.startswith("+"):
                hunk.added.append((new_line, line[1:]))
                new_line += 1
            elif line.startswith("-"):
                hunk.removed.append(line[1:])
            elif line.startswith("\\"):
                continue                      # "\ No newline at end of file"
            else:
                new_line += 1                 # unchanged context line

    # Keep only hunks that add code in a supported language, and split big ones.
    result: list[Hunk] = []
    for h in hunks:
        if not h.added or language_of(h.file) is None:
            continue
        if len(h.added) <= max_hunk_lines:
            result.append(h)
        else:
            for i in range(0, len(h.added), max_hunk_lines):
                part = h.added[i:i + max_hunk_lines]
                result.append(Hunk(file=h.file, header=f"{h.header} [part {i // max_hunk_lines + 1}]",
                                   added=part, raw="\n".join("+" + t for _, t in part)))
    return result


def _git(repo: str, *args: str, quiet: bool = False) -> str:
    import shutil
    if not shutil.which("git"):
        raise RuntimeError("Git is not installed or not on PATH. Install Git from https://git-scm.com/downloads")
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        if quiet:
            raise subprocess.CalledProcessError(r.returncode, args)
        lines = [ln for ln in r.stderr.strip().splitlines() if ln.strip()] or ["unknown error"]
        fatal = next((ln for ln in lines if ln.startswith(("fatal", "error"))), lines[0])
        raise RuntimeError(f"Git error: {fatal}  (check the Base/Head names; see README.txt section 13)")
    return r.stdout


def from_git(repo: str, base: str, head: str = "HEAD", description: str = "",
             max_hunk_lines: int = 80) -> ChangeSet:
    """Build a ChangeSet from `git diff base...head` in a local checkout."""
    diff = _git(repo, "diff", "--unified=3", f"{base}...{head}")
    hunks = parse_unified_diff(diff, max_hunk_lines)
    files = {}
    for path in sorted({h.file for h in hunks}):
        try:
            files[path] = _git(repo, "show", f"{head}:{path}", quiet=True)
        except subprocess.CalledProcessError:
            pass
    return ChangeSet(hunks=hunks, files=files, description=description, repo_root=repo)


def from_diff_text(diff: str, files: dict[str, str], description: str = "",
                   repo_root: str = ".", max_hunk_lines: int = 80) -> ChangeSet:
    """Build a ChangeSet from diff text plus the new file contents (used by evaluation)."""
    return ChangeSet(hunks=parse_unified_diff(diff, max_hunk_lines), files=files,
                     description=description, repo_root=repo_root)


def pr_description_from_github_event() -> str:
    """Inside a GitHub Action, read the PR title and body from the event payload."""
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        pr = json.load(f).get("pull_request", {})
    return f"{pr.get('title', '')}\n\n{pr.get('body') or ''}".strip()


def from_patch_file(patch_path: str, repo: str, description: str = "",
                    max_hunk_lines: int = 80) -> ChangeSet:
    """Review a .diff/.patch file. `repo` must be a folder that already contains the NEW
    version of the code (the patch applied), so full file contents and context can be read."""
    with open(patch_path, encoding="utf-8", errors="ignore") as f:
        diff = f.read()
    hunks = parse_unified_diff(diff, max_hunk_lines)
    files = {}
    for path in sorted({h.file for h in hunks}):
        full = os.path.join(repo, path)
        if os.path.isfile(full):
            with open(full, encoding="utf-8", errors="ignore") as f:
                files[path] = f.read()
    return ChangeSet(hunks=hunks, files=files, description=description, repo_root=repo)


PR_URL_RE = re.compile(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)")


def parse_pr_url(url: str) -> tuple[str, int]:
    m = PR_URL_RE.search(url or "")
    if not m:
        raise ValueError("Not a GitHub pull request URL. Expected https://github.com/<owner>/<repo>/pull/<number>")
    return f"{m.group(1)}/{m.group(2)}", int(m.group(3))


def from_github_pr(url: str, token: str | None = None, repo_root: str | None = None,
                   max_hunk_lines: int = 80) -> tuple[ChangeSet, dict]:
    """Download a pull request from GitHub: its description, the patch of every changed file
    and the full new contents of those files (at the PR's head commit).
    If `repo_root` is a local clone of the repository, the rest of the repository is also
    used as context; otherwise only the changed files are indexed."""
    import requests
    import tempfile
    repo, number = parse_pr_url(url)
    api = f"https://api.github.com/repos/{repo}"
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(f"{api}/pulls/{number}", headers=headers, timeout=60)
    if r.status_code == 404:
        raise RuntimeError("Pull request not found (private repositories need a token).")
    if r.status_code in (401, 403):
        if r.headers.get("x-ratelimit-remaining") == "0":
            raise RuntimeError("GitHub's limit of 60 requests per hour without a token was reached. "
                               "Enter a GitHub token (see README.txt, section 9) and try again.")
        raise RuntimeError("GitHub refused the request: check that your token is valid.")
    r.raise_for_status()
    pr = r.json()
    head_sha = pr["head"]["sha"]
    diff_parts, files = [], {}
    for page in range(1, 31):
        r = requests.get(f"{api}/pulls/{number}/files", headers=headers,
                         params={"per_page": 100, "page": page}, timeout=60)
        r.raise_for_status()
        batch = r.json()
        for f in batch:
            if f.get("status") == "removed" or not f.get("patch") or language_of(f["filename"]) is None:
                continue
            diff_parts.append(f"--- a/{f['filename']}\n+++ b/{f['filename']}\n{f['patch']}\n")
            raw = requests.get(f"{api}/contents/{f['filename']}", params={"ref": head_sha}, timeout=60,
                               headers={**headers, "Accept": "application/vnd.github.raw"})
            if raw.ok:
                files[f["filename"]] = raw.text
        if len(batch) < 100:
            break
    description = f"{pr.get('title', '')}\n\n{pr.get('body') or ''}".strip()
    hunks = parse_unified_diff("".join(diff_parts), max_hunk_lines)
    root = repo_root or tempfile.mkdtemp(prefix="icr_pr_")
    meta = {"repo": repo, "number": number, "head_sha": head_sha, "title": pr.get("title", "")}
    return ChangeSet(hunks=hunks, files=files, description=description, repo_root=root), meta
