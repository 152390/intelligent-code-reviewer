"""Metrics for Section 3.8.

Accuracy (3.8.1)
  block level : a changed block is predicted 'faulty' if at least one kept detector
                finding remains on it. Precision, recall, F1 against the label.
  line level  : kept detector findings vs. the labelled faulty lines (+/- tolerance).
  BLEU        : generated comments vs. reference reviewer comments (comparison only).
False positives (3.8.3)
  FPR (block) = FP / (FP + TN)      - how often CLEAN code gets flagged
  false-alarm share = wrong findings / all shown findings  - what the developer experiences
                (automatic proxy: a comment away from the labelled lines may still be valid,
                 so the human judgement in the rating study is the definitive measure)
Usability (3.8.2)
  SUS score (Brooke, 1996): odd items (score-1), even items (5-score), sum x 2.5 -> 0..100
"""
from __future__ import annotations


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4)}


def kept_detector_lines(report: dict) -> list[int]:
    return [f["line"] for f in report["findings"]
            if f["kept"] and f["source"] in ("detector", "static")]


def block_and_line_metrics(pairs: list[tuple[dict, dict]], tolerance: int = 1) -> dict:
    """pairs = [(sample, report), ...] for bug samples."""
    tp = fp = fn = tn = 0
    ltp = lfp = lfn = 0
    shown = wrong = 0
    for s, rep in pairs:
        lines = kept_detector_lines(rep)
        predicted_faulty = bool(lines)
        truth = s["label"] == "faulty"
        tp += predicted_faulty and truth
        fp += predicted_faulty and not truth
        fn += (not predicted_faulty) and truth
        tn += (not predicted_faulty) and not truth
        gold = set(s.get("faulty_lines", []))
        hit = set()
        for ln in lines:
            match = [g for g in gold if abs(g - ln) <= tolerance]
            if match:
                ltp += 1
                hit.update(match)
            else:
                lfp += 1
        lfn += len(gold - hit)
        all_shown = [f for f in rep["findings"] if f["kept"]]
        shown += len(all_shown)
        wrong += sum(1 for f in all_shown if not any(abs(g - f["line"]) <= tolerance for g in gold))
    out = {"blocks": len(pairs), "tp": tp, "fp": fp, "fn": fn, "tn": tn}
    out.update({f"block_{k}": v for k, v in prf(tp, fp, fn).items()})
    out.update({f"line_{k}": v for k, v in prf(ltp, lfp, lfn).items()})
    out["block_fpr"] = round(fp / (fp + tn), 4) if fp + tn else 0.0
    out["false_alarm_share"] = round(wrong / shown, 4) if shown else 0.0
    out["findings_shown"] = shown
    return out


def bleu(hypotheses: list[str], references: list[str]) -> float:
    import sacrebleu
    return round(sacrebleu.corpus_bleu(hypotheses, [references]).score, 2)


def sus_score(answers: list[int]) -> float:
    """answers: the 10 SUS items, each 1..5, in questionnaire order."""
    assert len(answers) == 10
    total = sum((a - 1) if i % 2 == 0 else (5 - a) for i, a in enumerate(answers))
    return total * 2.5
