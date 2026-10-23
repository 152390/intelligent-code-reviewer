"""Tune the false-positive filter on the VALIDATION set (Section 3.4.4).

1. Run the full pipeline once on val_bugs.jsonl with the filter switched OFF, so
   every candidate finding is kept together with its three filter inputs
   (confidence, static agreement, context support).
2. Mark each finding correct if it lies on a labelled faulty line (+/- 1).
3. Offline, try a grid of weights and thresholds (the model is NOT re-run, so this is fast).
4. Choose the setting with the best F1, write it to filter_config.json, and write the full
   sweep to threshold_sweep.csv so the precision/recall trade-off can be plotted and reported.

Usage
  python training/tune_threshold.py --val data/processed/val_bugs.jsonl --backend hf \
      --model Qwen/Qwen2.5-Coder-1.5B-Instruct --adapter outputs/lora-reviewer --out outputs/
"""
from __future__ import annotations
import argparse
import csv
import itertools
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from icr.samples import read_jsonl, bug_sample_to_changeset  # noqa: E402
from icr.pipeline import PipelineConfig, run  # noqa: E402
from icr.llm import make_backend  # noqa: E402


def collect(samples, backend, tol=1):
    cfg = PipelineConfig.for_variant("no_filter")
    cfg.use_explanations = False
    items, total_gold = [], 0
    for s in samples:
        cs = bug_sample_to_changeset(s)
        if not cs.hunks:
            continue
        gold = set(s.get("faulty_lines", []))
        total_gold += len(gold)
        for f in run(cs, backend, cfg)["findings"]:
            if f["source"] != "detector":
                continue
            items.append({"conf": f["confidence"], "static": f["static_agreement"], "ctx": f["context_support"],
                          "line": f["line"], "sample": s["id"],
                          "correct": any(abs(g - f["line"]) <= tol for g in gold)})
    return items, total_gold


def evaluate(items, total_gold, w, thr):
    kept = [i for i in items if w[0] * i["conf"] + w[1] * i["static"] + w[2] * i["ctx"] >= thr]
    tp = sum(i["correct"] for i in kept)
    hit = len({(i["sample"], i["line"]) for i in kept if i["correct"]})
    p = tp / len(kept) if kept else 0.0
    r = min(1.0, hit / total_gold) if total_gold else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return {"w_conf": w[0], "w_static": w[1], "w_ctx": w[2], "threshold": thr, "precision": round(p, 4),
            "recall": round(r, 4), "f1": round(f1, 4), "shown": len(kept),
            "false_alarms": len(kept) - tp}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--val", required=True)
    ap.add_argument("--backend", default="heuristic", choices=["hf", "openai", "heuristic"])
    ap.add_argument("--model")
    ap.add_argument("--adapter")
    ap.add_argument("--base-url")
    ap.add_argument("--load-4bit", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out", default="outputs")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    backend = make_backend(a.backend, a.model, a.adapter, a.base_url, a.load_4bit)
    items, total_gold = collect(read_jsonl(a.val)[:a.limit], backend)
    print(f"{len(items)} candidate findings, {total_gold} labelled faulty lines")

    weights = [w for w in itertools.product([0.4, 0.5, 0.6, 0.7], [0.1, 0.2, 0.3], [0.1, 0.2, 0.3])
               if abs(sum(w) - 1.0) < 1e-9]
    thresholds = [round(t * 0.05, 2) for t in range(0, 21)]
    sweep = [evaluate(items, total_gold, w, t) for w in weights for t in thresholds]
    best = max(sweep, key=lambda r: (r["f1"], r["precision"]))

    with open(os.path.join(a.out, "threshold_sweep.csv"), "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(sweep[0]))
        wr.writeheader()
        wr.writerows(sweep)
    cfg = {"w_conf": best["w_conf"], "w_static": best["w_static"], "w_ctx": best["w_ctx"],
           "threshold": best["threshold"], "line_tolerance": 1}
    json.dump(cfg, open(os.path.join(a.out, "filter_config.json"), "w"), indent=2)
    print("Best setting:", json.dumps(best))
    print(f"Saved {a.out}/filter_config.json and {a.out}/threshold_sweep.csv")


if __name__ == "__main__":
    main()
