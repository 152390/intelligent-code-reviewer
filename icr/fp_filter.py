"""Stage 4 - False-positive filter (Section 3.4.4).

Every candidate finding gets a score from three inputs:

    score = w_conf * model_confidence
          + w_static * static_agreement      (1 if a static analyser flags the same line +/- 1)
          + w_ctx * context_support          (do the identifiers the finding talks about
                                              actually exist in the change or retrieved context?)

Findings with score < threshold are dropped (kept=False, but still saved in the
report so the ablation in Section 3.8.3 can count them). The threshold and weights
are tuned on the validation set with training/tune_threshold.py and reported.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from .models import Finding, Hunk, Signal
from .static_analysis import signals_near

IDENT_RE = re.compile(r"`([^`]+)`|\b([A-Za-z_]\w*\(\))|\b([a-z]+_[a-z_0-9]+|[a-z]+[A-Z]\w*)\b")


@dataclass
class FilterConfig:
    w_conf: float = 0.60
    w_static: float = 0.25
    w_ctx: float = 0.15
    threshold: float = 0.45
    line_tolerance: int = 1


def mentioned_identifiers(message: str) -> set[str]:
    out = set()
    for groups in IDENT_RE.findall(message):
        tok = next(g for g in groups if g)
        tok = re.sub(r"\(.*\)$", "", tok).strip()
        out.update(re.findall(r"[A-Za-z_]\w*", tok)[:1])
    return {t for t in out if len(t) > 1}


def context_support(f: Finding, hunk: Hunk, context: dict | None) -> float:
    if f.line not in hunk.added_line_numbers:
        return 0.0
    idents = mentioned_identifiers(f.message)
    if not idents:
        return 0.5                                     # nothing checkable: neutral
    corpus = "\n".join(t for _, t in hunk.added)
    if context:
        corpus += "\n" + "\n".join(u["code"] for u in context.get("units", []))
    found = sum(1 for i in idents if re.search(rf"\b{re.escape(i)}\b", corpus))
    return found / len(idents)


def deduplicate(findings: list[Finding]) -> list[Finding]:
    """If the detector and the commenter both flag a line, keep the detector's finding
    (it carries a fault category) and fold the comment's confidence into it."""
    by_line: dict[tuple, Finding] = {}
    out = []
    for f in sorted(findings, key=lambda x: (x.source != "detector", -x.confidence)):
        key = (f.file, f.line)
        if key in by_line and f.source == "commenter":
            continue
        by_line.setdefault(key, f)
        out.append(f)
    return out


def apply_filter(findings: list[Finding], hunks: list[Hunk], contexts: list[dict | None],
                 signals: list[Signal], cfg: FilterConfig, enabled: bool = True) -> list[Finding]:
    for f in findings:
        hunk, ctx = hunks[f.hunk_index], contexts[f.hunk_index]
        near = sorted(signals_near(signals, f.file, f.line, cfg.line_tolerance),
                      key=lambda s: abs(s.line - f.line))
        # exact line = full agreement; only a neighbouring line = half agreement
        f.static_agreement = 1.0 if any(s.line == f.line for s in near) else (0.5 if near else 0.0)
        f.supporting_signals = [f"{s.tool}:{s.rule} (line {s.line}): {s.message}" for s in near]
        f.context_support = context_support(f, hunk, ctx)
        f.score = round(cfg.w_conf * f.confidence + cfg.w_static * f.static_agreement
                        + cfg.w_ctx * f.context_support, 4)
        f.kept = (f.score >= cfg.threshold) if enabled else True
    return findings
