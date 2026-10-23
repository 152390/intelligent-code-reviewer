"""Analyse the human evaluation (Sections 3.8.2, 3.8.3, 3.8.4).

Inputs
  --ratings  one or more filled rating_sheet.csv files (one per rater)
  --key      rating_key.csv (item -> system)
  --sus      CSV: participant,q1,...,q10   (System Usability Scale answers, 1-5)
  --timing   CSV: participant,pr,condition,minutes   condition = unaided | assisted

Outputs (printed and saved as human_results.json)
  * mean / median Likert scores per system and criterion
  * Mann-Whitney U test: full system vs each other system (ordinal data, so non-parametric)
  * human-judged false-positive rate per system = share of items rated real_problem = no
  * percent agreement between raters on real_problem
  * SUS mean and standard deviation (68 is the commonly cited average)
  * mean review time unaided vs assisted, and time saved
"""
from __future__ import annotations
import argparse
import csv
import json
import os
import statistics as st
import sys
from collections import defaultdict
from itertools import combinations

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from metrics import sus_score  # noqa: E402

CRITERIA = ["correctness_1to5", "relevance_1to5", "clarity_1to5", "explanation_1to5_or_NA"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratings", nargs="+", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--sus")
    ap.add_argument("--timing")
    ap.add_argument("--out", default="study_out")
    a = ap.parse_args()
    key = {r["item_id"]: r["system"] for r in csv.DictReader(open(a.key, encoding="utf-8"))}
    scores = defaultdict(lambda: defaultdict(list))
    real = defaultdict(list)
    per_item = defaultdict(dict)
    for rater, path in enumerate(a.ratings):
        for r in csv.DictReader(open(path, encoding="utf-8")):
            sysname = key.get(r["item_id"])
            if not sysname:
                continue
            for c in CRITERIA:
                v = (r.get(c) or "").strip()
                if v.isdigit():
                    scores[sysname][c].append(int(v))
            rp = (r.get("real_problem_yes_no") or "").strip().lower()
            if rp in ("yes", "no"):
                real[sysname].append(rp == "yes")
                per_item[r["item_id"]][rater] = rp
    res = {"likert": {}, "human_false_positive_rate": {}, "tests_vs_full": {}}
    for sysname, crit in scores.items():
        res["likert"][sysname] = {c: {"mean": round(st.mean(v), 2), "median": st.median(v), "n": len(v)}
                                  for c, v in crit.items() if v}
    for sysname, v in real.items():
        res["human_false_positive_rate"][sysname] = round(1 - sum(v) / len(v), 3) if v else None
    try:
        from scipy.stats import mannwhitneyu
        for other in scores:
            if other == "full":
                continue
            res["tests_vs_full"][other] = {}
            for c in CRITERIA:
                x, y = scores["full"].get(c, []), scores[other].get(c, [])
                if len(x) > 1 and len(y) > 1:
                    u, p = mannwhitneyu(x, y, alternative="two-sided")
                    res["tests_vs_full"][other][c] = {"U": float(u), "p": round(float(p), 4)}
    except ImportError:
        res["tests_vs_full"] = "install scipy for significance tests"
    agree = [per_item[i][r1] == per_item[i][r2] for i in per_item
             for r1, r2 in combinations(sorted(per_item[i]), 2)]
    res["rater_percent_agreement_real_problem"] = round(sum(agree) / len(agree), 3) if agree else None

    if a.sus:
        sus = [sus_score([int(r[f"q{i}"]) for i in range(1, 11)]) for r in csv.DictReader(open(a.sus))]
        res["sus"] = {"mean": round(st.mean(sus), 1), "sd": round(st.stdev(sus), 1) if len(sus) > 1 else 0,
                      "n": len(sus)}
    if a.timing:
        t = defaultdict(list)
        for r in csv.DictReader(open(a.timing)):
            t[r["condition"].strip().lower()].append(float(r["minutes"]))
        if t.get("unaided") and t.get("assisted"):
            u, s = st.mean(t["unaided"]), st.mean(t["assisted"])
            res["review_time_minutes"] = {"unaided": round(u, 2), "assisted": round(s, 2),
                                          "time_saved_percent": round(100 * (u - s) / u, 1)}
    os.makedirs(a.out, exist_ok=True)
    json.dump(res, open(os.path.join(a.out, "human_results.json"), "w"), indent=2)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
