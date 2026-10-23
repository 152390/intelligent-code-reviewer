"""Automated evaluation: accuracy, false positives, efficiency, baselines and ablations
(Sections 3.8.1, 3.8.3, 3.8.4, 3.8.5).

Usage
  python evaluation/run_eval.py --test data/processed/test_bugs.jsonl \
      --comments data/processed/test_comments.jsonl \
      --backend hf --model Qwen/Qwen2.5-Coder-1.5B-Instruct --adapter outputs/lora-reviewer \
      --filter-config outputs/filter_config.json --out results/

Baseline 2 ("general-purpose LLM, diff only") must use the BASE model without the
adapter. Run it separately and the results are merged into the same table:
  python evaluation/run_eval.py ... --variants llm_diff_only --backend hf --model <same base> --out results/
"""
from __future__ import annotations
import argparse
import csv
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "evaluation"))
from icr.samples import read_jsonl, bug_sample_to_changeset, review_sample_to_changeset  # noqa: E402
from icr.pipeline import PipelineConfig, run  # noqa: E402
from icr.fp_filter import FilterConfig  # noqa: E402
from icr.llm import make_backend, extract_json  # noqa: E402
from icr.prompts import format_context_block, review_prompt  # noqa: E402
from icr.context_builder import ContextBuilder  # noqa: E402
from metrics import block_and_line_metrics, bleu  # noqa: E402

ALL = ["full", "no_context", "no_static", "no_filter", "no_explanation", "static_only"]


def size_bucket(n: int) -> str:
    return "1-10" if n <= 10 else "11-30" if n <= 30 else "31-80" if n <= 80 else "80+"


def evaluate_bugs(samples, backend, variant, fcfg, out_dir):
    cfg = PipelineConfig.for_variant(variant, filter=fcfg)
    pairs, eff = [], []
    with open(os.path.join(out_dir, f"reports_{variant}.jsonl"), "w", encoding="utf-8") as fh:
        for i, s in enumerate(samples):
            cs = bug_sample_to_changeset(s)
            if not cs.hunks:
                continue
            rep = run(cs, backend, cfg)
            rep.pop("contexts", None)
            pairs.append((s, rep))
            eff.append({"variant": variant, "id": s["id"], "added_lines": rep["pr_size_added_lines"],
                        "bucket": size_bucket(rep["pr_size_added_lines"]), "seconds": rep["timings_sec"]["total"]})
            fh.write(json.dumps({"id": s["id"], "label": s["label"], "report": rep}) + "\n")
            if (i + 1) % 25 == 0:
                print(f"  {variant}: {i + 1}/{len(samples)}")
    m = block_and_line_metrics(pairs)
    m["variant"] = variant
    m["mean_seconds_per_block"] = round(sum(e["seconds"] for e in eff) / max(1, len(eff)), 3)
    return m, eff


def evaluate_comments(samples, backend, use_context=True):
    hyps, refs = [], []
    for s in samples:
        cs = review_sample_to_changeset(s)
        if cs is None:
            continue
        h = cs.hunks[0]
        ctx = ContextBuilder(cs.repo_root, cs, max_chars=4000).retrieve(h) if use_context else None
        data = extract_json(backend.generate(review_prompt(format_context_block(h, ctx, None, "", "")))) or {}
        comments = data.get("comments", []) if isinstance(data, dict) else []
        hyps.append(" ".join(str(c.get("comment", "")) for c in comments) or "")
        refs.append(s["msg"])
    return {"bleu": bleu(hyps, refs), "n": len(refs)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", required=True)
    ap.add_argument("--comments")
    ap.add_argument("--variants", nargs="+", default=ALL)
    ap.add_argument("--backend", default="heuristic", choices=["hf", "openai", "heuristic"])
    ap.add_argument("--model")
    ap.add_argument("--adapter")
    ap.add_argument("--base-url")
    ap.add_argument("--load-4bit", action="store_true")
    ap.add_argument("--filter-config")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out", default="results")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    fcfg = FilterConfig(**json.load(open(a.filter_config))) if a.filter_config else FilterConfig()
    samples = read_jsonl(a.test)[:a.limit]
    needs_model = any(v != "static_only" for v in a.variants)
    backend = make_backend(a.backend, a.model, a.adapter, a.base_url, a.load_4bit) if needs_model else None

    rows, eff_rows = [], []
    for v in a.variants:
        print(f"Evaluating variant {v} on {len(samples)} blocks")
        t = time.perf_counter()
        m, eff = evaluate_bugs(samples, backend, v, fcfg, a.out)
        m["model"] = "none" if v == "static_only" else getattr(backend, "name", "?")
        m["wall_seconds"] = round(time.perf_counter() - t, 1)
        rows.append(m)
        eff_rows += eff
        print(json.dumps(m))

    # Merge with earlier runs (e.g. baseline 2 run with the base model) by variant name.
    mpath = os.path.join(a.out, "metrics.json")
    old = {r["variant"]: r for r in json.load(open(mpath))} if os.path.exists(mpath) else {}
    old.update({r["variant"]: r for r in rows})
    rows = list(old.values())
    json.dump(rows, open(mpath, "w"), indent=2)

    cols = ["variant", "model", "blocks", "block_precision", "block_recall", "block_f1", "line_precision",
            "line_recall", "line_f1", "block_fpr", "false_alarm_share", "findings_shown", "mean_seconds_per_block"]
    with open(os.path.join(a.out, "metrics.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(a.out, "metrics.md"), "w") as f:
        f.write("| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n")
        for r in rows:
            f.write("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |\n")
    with open(os.path.join(a.out, "efficiency.csv"), "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["variant", "id", "added_lines", "bucket", "seconds"])
        if f.tell() == 0:
            w.writeheader()
        w.writerows(eff_rows)

    if a.comments and backend is not None:
        res = evaluate_comments(read_jsonl(a.comments)[:a.limit], backend)
        json.dump(res, open(os.path.join(a.out, "comment_bleu.json"), "w"), indent=2)
        print("Comment generation BLEU:", res)
    print(f"Results written to {a.out}/metrics.md")


if __name__ == "__main__":
    main()
