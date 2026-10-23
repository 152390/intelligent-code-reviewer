"""Convert public bug/vulnerability datasets into labelled changed blocks (Section 3.5).

KEY IDEA - a bug-fix pair gives us BOTH a faulty and a clean example:
  * fixed  -> buggy  diff  = a change that INTRODUCES the fault   -> label "faulty";
                             its added lines are the faulty lines (line-level labels)
  * buggy  -> fixed  diff  = the fix itself                       -> label "clean"
This matches the review setting: the system sees a change, not a whole program.

Every sample is written as one JSON line in a common format:
  {"id", "project", "language", "file", "diff", "after_code", "label",
   "faulty_lines": [...], "category": "security|logic|quality", "description", "date"}

Sub-commands
  cvefixes  read the CVEfixes SQLite database (Bhandari et al., 2021)
  pair      read two directories with the buggy and fixed versions of a project, e.g. a
            Defects4J checkout (Java, Just et al., 2014) or BugsInPy (Python)

Usage
  python training/make_bug_samples.py cvefixes --db CVEfixes.db --out data/raw/cvefixes.jsonl
  defects4j checkout -p Lang -v 1b -w /tmp/lang_1_buggy
  defects4j checkout -p Lang -v 1f -w /tmp/lang_1_fixed
  python training/make_bug_samples.py pair --buggy /tmp/lang_1_buggy --fixed /tmp/lang_1_fixed \
         --project Lang --bug-id 1 --category logic --out data/raw/defects4j.jsonl
"""
from __future__ import annotations
import argparse
import difflib
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from icr.ingestion import parse_unified_diff, language_of  # noqa: E402

MAX_ADDED = 80   # Section 3.6: very large changes are excluded


def make_diff(path: str, old: str, new: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                        fromfile=f"a/{path}", tofile=f"b/{path}", n=3))


def samples_from_pair(path: str, buggy: str, fixed: str, project: str, sid: str,
                      category: str, description: str = "", date: str = "") -> list[dict]:
    lang = language_of(path)
    if lang is None or not buggy or not fixed or buggy == fixed:
        return []
    out = []
    # faulty: fixed -> buggy
    d = make_diff(path, fixed, buggy)
    hunks = parse_unified_diff(d)
    faulty_lines = sorted({n for h in hunks for n, _ in h.added})
    if hunks and len(faulty_lines) <= MAX_ADDED:
        out.append(dict(id=f"{sid}:faulty", project=project, language=lang, file=path, diff=d,
                        after_code=buggy, label="faulty", faulty_lines=faulty_lines,
                        category=category, description=description, date=date))
    # clean: buggy -> fixed
    d = make_diff(path, buggy, fixed)
    hunks = parse_unified_diff(d)
    if hunks and sum(len(h.added) for h in hunks) <= MAX_ADDED:
        out.append(dict(id=f"{sid}:clean", project=project, language=lang, file=path, diff=d,
                        after_code=fixed, label="clean", faulty_lines=[], category="",
                        description="", date=date))
    return out


def cvefixes(args):
    """NOTE: column names follow the published CVEfixes schema. If your copy differs,
    check with:  sqlite3 CVEfixes.db ".schema file_change"  and adjust the query."""
    con = sqlite3.connect(args.db)
    langs = ",".join("?" for _ in args.languages)
    q = f"""
      SELECT f.file_change_id, f.filename, f.code_before, f.code_after, c.repo_url,
             c.author_date, fx.cve_id, cw.cwe_id
      FROM file_change f
      JOIN commits c ON f.hash = c.hash
      LEFT JOIN fixes fx ON fx.hash = f.hash
      LEFT JOIN cwe_classification cw ON cw.cve_id = fx.cve_id
      WHERE f.programming_language IN ({langs})
    """
    n = 0
    seen = set()
    with open(args.out, "w", encoding="utf-8") as out:
        for fid, fname, before, after, repo, date, cve, cwe in con.execute(q, args.languages):
            if fid in seen:
                continue
            seen.add(fid)
            desc = f"Vulnerability {cve or ''} ({cwe or 'unknown CWE'})".strip()
            for s in samples_from_pair(fname, before, after, repo, f"cvefixes:{fid}", "security", desc, date or ""):
                out.write(json.dumps(s) + "\n")
                n += 1
    print(f"wrote {n} samples to {args.out}")


def pair(args):
    n = 0
    with open(args.out, "a", encoding="utf-8") as out:
        for root, _, files in os.walk(args.fixed):
            for fn in files:
                full_fixed = os.path.join(root, fn)
                rel = os.path.relpath(full_fixed, args.fixed).replace(os.sep, "/")
                full_buggy = os.path.join(args.buggy, rel)
                if not language_of(rel) or not os.path.exists(full_buggy):
                    continue
                with open(full_fixed, encoding="utf-8", errors="ignore") as a, \
                        open(full_buggy, encoding="utf-8", errors="ignore") as b:
                    fixed, buggy = a.read(), b.read()
                for s in samples_from_pair(rel, buggy, fixed, args.project,
                                           f"{args.project}-{args.bug_id}:{rel}", args.category, args.description):
                    out.write(json.dumps(s) + "\n")
                    n += 1
    print(f"appended {n} samples to {args.out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cvefixes")
    c.add_argument("--db", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--languages", nargs="+", default=["Python", "Java"])
    p = sub.add_parser("pair")
    p.add_argument("--buggy", required=True)
    p.add_argument("--fixed", required=True)
    p.add_argument("--project", required=True)
    p.add_argument("--bug-id", required=True)
    p.add_argument("--category", default="logic", choices=["logic", "security", "quality"])
    p.add_argument("--description", default="")
    p.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    {"cvefixes": cvefixes, "pair": pair}[a.cmd](a)
