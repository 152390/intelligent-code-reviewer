"""Helpers that turn dataset samples into ChangeSets and prompts.

Used by training (to build fine-tuning examples) and by evaluation (to run the
pipeline on test data), so both use exactly the same prompt format as the live system.
"""
from __future__ import annotations
import json
import tempfile
from .ingestion import from_diff_text, parse_unified_diff
from .models import ChangeSet

_EMPTY_REPO = tempfile.mkdtemp(prefix="icr_empty_")


def read_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: str, rows) -> int:
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
            n += 1
    return n


def bug_sample_to_changeset(s: dict, repo_root: str | None = None) -> ChangeSet:
    """A bug sample has one file. If you cloned the project at that commit, pass
    repo_root so the context builder can index the rest of the repository."""
    # The sample's 'description' (e.g. the CVE text) is NOT passed to the model:
    # it would reveal the answer (label leakage).
    return from_diff_text(s["diff"], {s["file"]: s["after_code"]}, "", repo_root or _EMPTY_REPO)


def review_sample_to_changeset(s: dict) -> ChangeSet | None:
    """CodeReviewer 'msg' samples: a single diff hunk ('patch'), the old file ('oldf')
    and the reviewer comment ('msg'). We prepend a file header so the diff parser
    knows the file name and language."""
    lang = (s.get("lang") or "py").lower()
    ext = {"py": ".py", "python": ".py", "java": ".java"}.get(lang)
    if not ext:
        return None
    path = f"src/file{ext}"
    diff = f"--- a/{path}\n+++ b/{path}\n" + s["patch"]
    hunks = parse_unified_diff(diff)
    if not hunks:
        return None
    files = {path: s.get("oldf", "") or ""}
    return ChangeSet(hunks=hunks, files=files, repo_root=_EMPTY_REPO)
