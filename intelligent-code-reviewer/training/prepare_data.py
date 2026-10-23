"""Data preparation (Section 3.6).

Steps, in order:
  1. Load review-comment data (CodeReviewer 'msg' JSONL, Li et al., 2022) and bug
     samples (output of make_bug_samples.py).
  2. Filter empty or meaningless review comments ("LGTM", "ok", "+1", very short).
  3. Remove duplicates and near-duplicates (normalised-token hash + MinHash Jaccard).
  4. Split by PROJECT (default) or by TIME, never at random, so the model is not tested
     on code it has effectively seen. Evaluation PRs listed in --exclude are removed.
  5. Build chat-format training examples with the SAME prompt functions the live
     system uses (icr.prompts), with retrieved context from the sample's file.

Outputs (data/processed/):
  train.jsonl, val.jsonl            fine-tuning examples {"messages": [...], "task": ...}
  val_bugs.jsonl, test_bugs.jsonl   raw bug samples for threshold tuning / evaluation
  test_comments.jsonl               raw review samples for BLEU evaluation

Usage
  python training/prepare_data.py --codereviewer data/raw/msg-train.jsonl \
      --bugs data/raw/cvefixes.jsonl data/raw/defects4j.jsonl --out data/processed
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from icr.samples import read_jsonl, write_jsonl, bug_sample_to_changeset, review_sample_to_changeset  # noqa
from icr.context_builder import ContextBuilder  # noqa: E402
from icr.prompts import SYSTEM, format_context_block, review_prompt, detect_prompt  # noqa: E402
from icr.ingestion import language_of  # noqa: E402

MEANINGLESS = re.compile(r"^\s*(lgtm|ok(ay)?|\+1|nit\.?|done|thanks?( you)?|ship it|looks good( to me)?|"
                         r"same( here)?|ditto|nice|good|great|:\+1:|ack)\s*[.!]*\s*$", re.I)


# ------------------------------------------------------------------ 2. comment filtering
def meaningful(comment: str, min_words: int = 3) -> bool:
    c = (comment or "").strip()
    return bool(c) and not MEANINGLESS.match(c) and len(c.split()) >= min_words


# ------------------------------------------------------------------ 3. de-duplication
def norm_tokens(code: str) -> list[str]:
    return re.findall(r"[A-Za-z_]\w*|\d+|[^\s\w]", code.lower())


def exact_key(text: str) -> str:
    return hashlib.md5(" ".join(norm_tokens(text)).encode()).hexdigest()


def minhash(tokens: list[str], k: int = 64, shingle: int = 5) -> tuple:
    sh = {" ".join(tokens[i:i + shingle]) for i in range(max(1, len(tokens) - shingle + 1))}
    return tuple(min(int(hashlib.md5(f"{seed}:{s}".encode()).hexdigest()[:8], 16) for s in sh)
                 for seed in range(k))


def dedupe(rows: list[dict], text_of, jaccard: float = 0.9, bands: int = 16) -> list[dict]:
    """Exact duplicates via hash; near-duplicates via MinHash with LSH banding."""
    seen_exact, buckets, kept = set(), {}, []
    for r in rows:
        text = text_of(r)
        key = exact_key(text)
        if key in seen_exact:
            continue
        mh = minhash(norm_tokens(text))
        rows_per_band = len(mh) // bands
        cands = set()
        for b in range(bands):
            cands |= set(buckets.get((b, mh[b * rows_per_band:(b + 1) * rows_per_band]), []))
        if any(sum(x == y for x, y in zip(mh, kept[c]["_mh"])) / len(mh) >= jaccard for c in cands):
            continue
        seen_exact.add(key)
        r["_mh"] = mh
        idx = len(kept)
        kept.append(r)
        for b in range(bands):
            buckets.setdefault((b, mh[b * rows_per_band:(b + 1) * rows_per_band]), []).append(idx)
    for r in kept:
        r.pop("_mh", None)
    return kept


# ------------------------------------------------------------------ 4. splitting
def split_of(row: dict, by: str, cut: tuple[str, str] | None, val_frac: float, test_frac: float) -> str:
    if by == "time" and cut and row.get("date"):
        return "train" if row["date"] < cut[0] else ("val" if row["date"] < cut[1] else "test")
    project = row.get("project") or row.get("proj") or row.get("repo") or row.get("id", "")
    h = int(hashlib.md5(str(project).encode()).hexdigest(), 16) % 1000 / 1000
    return "test" if h < test_frac else ("val" if h < test_frac + val_frac else "train")


def time_cuts(rows, val_frac, test_frac):
    dates = sorted(r["date"] for r in rows if r.get("date"))
    if not dates:
        return None
    return (dates[int(len(dates) * (1 - val_frac - test_frac))], dates[int(len(dates) * (1 - test_frac))])


# ------------------------------------------------------------------ 5. example building
def context_for(cs, hunk, use_context: bool):
    if not use_context:
        return None
    return ContextBuilder(cs.repo_root, cs, top_k=3, max_chars=4000).retrieve(hunk)


def review_example(s: dict, use_context: bool):
    cs = review_sample_to_changeset(s)
    if cs is None:
        return None
    h = cs.hunks[0]
    block = format_context_block(h, context_for(cs, h, use_context), None, "", language_of(h.file))
    target = {"comments": [{"line": h.start, "comment": s["msg"].strip()}]}
    return {"task": "review", "meta": {"id": s.get("id"), "project": s.get("proj")},
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": review_prompt(block)},
                         {"role": "assistant", "content": json.dumps(target)}]}


def detection_example(s: dict, use_context: bool):
    cs = bug_sample_to_changeset(s)
    if not cs.hunks:
        return None
    h = cs.hunks[0]
    block = format_context_block(h, context_for(cs, h, use_context), None, "", s["language"])
    lines = [n for n in s["faulty_lines"] if n in h.added_line_numbers][:5]
    if s["label"] == "faulty" and not lines:
        return None
    msg = s.get("description") or f"{s['category']} fault"
    target = {"label": s["label"],
              "findings": [{"line": n, "category": s["category"], "message": msg} for n in lines]}
    return {"task": "detect", "meta": {"id": s["id"], "project": s["project"]},
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": detect_prompt(block)},
                         {"role": "assistant", "content": json.dumps(target)}]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codereviewer", nargs="*", default=[])
    ap.add_argument("--bugs", nargs="*", default=[])
    ap.add_argument("--out", default="data/processed")
    ap.add_argument("--split-by", choices=["project", "time"], default="project")
    ap.add_argument("--val-frac", type=float, default=0.1)
    ap.add_argument("--test-frac", type=float, default=0.1)
    ap.add_argument("--exclude", help="file with project names or ids reserved for the final evaluation")
    ap.add_argument("--max-review", type=int, default=20000)
    ap.add_argument("--no-context", action="store_true", help="faster; no retrieved context in prompts")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    random.seed(a.seed)
    os.makedirs(a.out, exist_ok=True)
    excluded = set(open(a.exclude).read().split()) if a.exclude else set()
    stats = {}

    reviews = [r for f in a.codereviewer for r in read_jsonl(f)]
    stats["review_loaded"] = len(reviews)
    reviews = [r for r in reviews if meaningful(r.get("msg", ""))]
    stats["review_after_comment_filter"] = len(reviews)
    reviews = dedupe(reviews, lambda r: r["patch"] + "\n" + r["msg"])
    stats["review_after_dedupe"] = len(reviews)
    random.shuffle(reviews)
    reviews = reviews[:a.max_review]

    bugs = [r for f in a.bugs for r in read_jsonl(f)]
    stats["bugs_loaded"] = len(bugs)
    bugs = dedupe(bugs, lambda r: r["diff"])
    stats["bugs_after_dedupe"] = len(bugs)

    rows = [r for r in reviews + bugs if str(r.get("project") or r.get("proj")) not in excluded
            and str(r.get("id")) not in excluded]
    cut = time_cuts(rows, a.val_frac, a.test_frac) if a.split_by == "time" else None
    splits = {"train": [], "val": [], "test": []}
    for r in rows:
        splits[split_of(r, a.split_by, cut, a.val_frac, a.test_frac)].append(r)

    for name in ("train", "val"):
        examples = []
        for r in splits[name]:
            ex = review_example(r, not a.no_context) if "msg" in r else detection_example(r, not a.no_context)
            if ex:
                examples.append(ex)
        random.shuffle(examples)
        stats[f"{name}_examples"] = write_jsonl(os.path.join(a.out, f"{name}.jsonl"), examples)
    stats["val_bugs"] = write_jsonl(os.path.join(a.out, "val_bugs.jsonl"), [r for r in splits["val"] if "msg" not in r])
    stats["test_bugs"] = write_jsonl(os.path.join(a.out, "test_bugs.jsonl"), [r for r in splits["test"] if "msg" not in r])
    stats["test_comments"] = write_jsonl(os.path.join(a.out, "test_comments.jsonl"),
                                         [r for r in splits["test"] if "msg" in r])
    with open(os.path.join(a.out, "data_stats.json"), "w") as f:
        json.dump(stats, f, indent=2)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
