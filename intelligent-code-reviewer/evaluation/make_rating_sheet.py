"""Build a BLIND rating sheet for the human evaluation (Section 3.8.2).

Folder layout (one folder per pull request, one sub-folder per system):
  study/
    pr01/
      full/review_report.json            <- python -m icr review ... --variant full --out study/pr01/full
      llm_diff_only/review_report.json   <- baseline 2
      static_only/review_report.json     <- baseline 1
      manual.csv                         <- baseline 3: comments written by a human reviewer
                                            columns: file,line,comment
    pr02/ ...

Output
  rating_sheet.csv   given to raters. Items from all systems are shuffled and get random ids,
                     so raters cannot tell which system wrote which comment.
  rating_key.csv     kept by the researcher ONLY: item id -> system.

Usage:  python evaluation/make_rating_sheet.py --study study --out study_out
"""
from __future__ import annotations
import argparse
import csv
import json
import os
import random


def comment_text(f: dict) -> tuple[str, str]:
    e = f.get("explanation") or {}
    expl = " ".join(x for x in [e.get("problem"), e.get("why_it_matters"),
                                 f"Suggestion: {e['suggestion']}" if e.get("suggestion") else ""] if x)
    return f["message"], expl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--study", required=True)
    ap.add_argument("--out", default="study_out")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--hide-explanations", action="store_true",
                    help="blank the explanation column. Only the full system has explanations, so showing "
                         "them reveals the system. Do a first pass hidden (correctness/relevance/clarity), "
                         "then a second pass on the full system's explanations.")
    a = ap.parse_args()
    random.seed(a.seed)
    items = []
    for pr in sorted(os.listdir(a.study)):
        pr_dir = os.path.join(a.study, pr)
        if not os.path.isdir(pr_dir):
            continue
        for system in sorted(os.listdir(pr_dir)):
            path = os.path.join(pr_dir, system, "review_report.json")
            if os.path.exists(path):
                for f in json.load(open(path, encoding="utf-8"))["findings"]:
                    if f["kept"]:
                        c, e = comment_text(f)
                        items.append({"pr": pr, "system": system, "file": f["file"], "line": f["line"],
                                      "comment": c, "explanation": e})
        manual = os.path.join(pr_dir, "manual.csv")
        if os.path.exists(manual):
            for r in csv.DictReader(open(manual, encoding="utf-8")):
                items.append({"pr": pr, "system": "manual", "file": r["file"], "line": r["line"],
                              "comment": r["comment"], "explanation": ""})
    random.shuffle(items)
    os.makedirs(a.out, exist_ok=True)
    sheet_cols = ["item_id", "pr", "file", "line", "comment", "explanation",
                  "correctness_1to5", "relevance_1to5", "clarity_1to5", "explanation_1to5_or_NA",
                  "real_problem_yes_no"]
    with open(os.path.join(a.out, "rating_sheet.csv"), "w", newline="", encoding="utf-8") as s, \
            open(os.path.join(a.out, "rating_key.csv"), "w", newline="", encoding="utf-8") as k:
        ws, wk = csv.writer(s), csv.writer(k)
        ws.writerow(sheet_cols)
        wk.writerow(["item_id", "system"])
        for i, it in enumerate(items, 1):
            iid = f"C{i:04d}"
            expl = "" if a.hide_explanations else it["explanation"]
            ws.writerow([iid, it["pr"], it["file"], it["line"], it["comment"], expl, "", "", "", "", ""])
            wk.writerow([iid, it["system"]])
    print(f"{len(items)} items -> {a.out}/rating_sheet.csv (give to raters), {a.out}/rating_key.csv (keep private)")


if __name__ == "__main__":
    main()
