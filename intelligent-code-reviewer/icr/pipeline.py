"""The full pipeline of Figure 3.1, plus the baselines and ablations of Section 3.8.5.

    variant           context  static  filter  explanation   what it is
    full                yes     yes     yes       yes        the proposed system
    no_context           -      yes     yes       yes        ablation
    no_static           yes      -      yes       yes        ablation
    no_filter           yes     yes      -        yes        ablation
    no_explanation      yes     yes     yes        -         ablation
    llm_diff_only        -       -       -         -         baseline 2 (general LLM, diff only)
    static_only       (no LLM: static warnings on changed lines)   baseline 1
Baseline 3 (manual human review) is collected with people, see evaluation/.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field, asdict
from .models import ChangeSet, Finding, Signal
from .ingestion import language_of
from .context_builder import ContextBuilder
from . import static_analysis
from .prompts import format_context_block, review_prompt, detect_prompt
from .reviewer import generate_comments, detect_errors
from .fp_filter import FilterConfig, apply_filter, deduplicate
from .explainer import explain

VARIANTS = {
    "full":           dict(use_context=True,  use_static=True,  use_filter=True,  use_explanations=True),
    "no_context":     dict(use_context=False, use_static=True,  use_filter=True,  use_explanations=True),
    "no_static":      dict(use_context=True,  use_static=False, use_filter=True,  use_explanations=True),
    "no_filter":      dict(use_context=True,  use_static=True,  use_filter=False, use_explanations=True),
    "no_explanation": dict(use_context=True,  use_static=True,  use_filter=True,  use_explanations=False),
    "llm_diff_only":  dict(use_context=False, use_static=False, use_filter=False, use_explanations=False),
}


@dataclass
class PipelineConfig:
    variant: str = "full"
    use_context: bool = True
    use_static: bool = True
    use_filter: bool = True
    use_explanations: bool = True
    top_k: int = 3
    max_context_chars: int = 6000
    embedding_model: str | None = None
    spotbugs_classes: str | None = None
    filter: FilterConfig = field(default_factory=FilterConfig)

    @classmethod
    def for_variant(cls, variant: str, **overrides):
        cfg = cls(variant=variant, **overrides)
        for k, v in VARIANTS.get(variant, {}).items():
            setattr(cfg, k, v)
        return cfg


def _static_category(sig: Signal) -> str:
    if sig.tool == "semgrep":
        return "security"
    if sig.tool == "spotbugs" or sig.severity in ("error", "fatal"):
        return "logic"
    return "quality"


def run_static_only(cs: ChangeSet, cfg: PipelineConfig) -> dict:
    t0 = time.perf_counter()
    signals = static_analysis.analyse(cs, cfg.spotbugs_classes)
    findings = []
    for i, h in enumerate(cs.hunks):
        for s in signals:
            if s.file == h.file and s.line in h.added_line_numbers:
                findings.append(Finding(file=s.file, line=s.line, category=_static_category(s),
                                        message=f"[{s.tool}:{s.rule}] {s.message}", confidence=1.0,
                                        source="static", hunk_index=i, score=1.0))
    blocks = [{"file": h.file, "start": h.start, "end": h.end,
               "label": "faulty" if any(f.hunk_index == i for f in findings) else "clean"}
              for i, h in enumerate(cs.hunks)]
    return _report(cs, "static_only", "none", findings, blocks, signals,
                   {"static_analysis": time.perf_counter() - t0}, asdict(cfg))


def run(cs: ChangeSet, backend, cfg: PipelineConfig | None = None, verbose: bool = False,
        log=None, progress=None) -> dict:
    """log(message) receives stage messages; progress(fraction 0..1) receives progress.
    Both are optional and are used by the desktop application."""
    cfg = cfg or PipelineConfig()
    log = log or (print if verbose else (lambda *a, **k: None))
    progress = progress or (lambda x: None)
    if cfg.variant == "static_only":
        log("[static only] running analysers")
        rep = run_static_only(cs, cfg)
        progress(1.0)
        return rep
    timings = {}

    # Stage 2a: context builder
    t = time.perf_counter()
    builder = ContextBuilder(cs.repo_root, cs, cfg.top_k, cfg.max_context_chars,
                             cfg.embedding_model) if cfg.use_context else None
    contexts = [builder.retrieve(h) if builder else None for h in cs.hunks]
    timings["context_builder"] = time.perf_counter() - t
    log(f"[1/5] context: {len(builder.units) if builder else 0} units indexed")
    progress(0.15)

    # Stage 2b: static analysis
    t = time.perf_counter()
    signals = static_analysis.analyse(cs, cfg.spotbugs_classes) if cfg.use_static else []
    timings["static_analysis"] = time.perf_counter() - t
    log(f"[2/5] static analysis: {len(signals)} warnings")
    progress(0.3)

    # Stage 3: review comment generator + error detector (shared context block)
    t = time.perf_counter()
    findings: list[Finding] = []
    blocks = []
    for i, h in enumerate(cs.hunks):
        hunk_sigs = static_analysis.signals_for_hunk(signals, h.file, h.start, h.end)
        block = format_context_block(h, contexts[i], hunk_sigs, cs.description, language_of(h.file) or "")
        comments, _ = generate_comments(backend, review_prompt(block), h, i)
        faults, label, _ = detect_errors(backend, detect_prompt(block), h, i)
        findings += faults + comments
        blocks.append({"file": h.file, "start": h.start, "end": h.end, "label": label})
        log(f"      block {i + 1}/{len(cs.hunks)}: {h.file} lines {h.start}-{h.end} -> {label}")
        progress(0.3 + 0.5 * (i + 1) / max(1, len(cs.hunks)))
    timings["llm_review_and_detection"] = time.perf_counter() - t
    log(f"[3/5] model: {len(findings)} candidate findings")

    # Stage 4: false-positive filter
    t = time.perf_counter()
    findings = deduplicate(findings)
    apply_filter(findings, cs.hunks, contexts, signals, cfg.filter, enabled=cfg.use_filter)
    for b_i, b in enumerate(blocks):     # a block is 'faulty' only if a kept detector finding remains
        b["label"] = "faulty" if any(f.kept and f.hunk_index == b_i and f.source == "detector"
                                     for f in findings) else "clean"
    timings["false_positive_filter"] = time.perf_counter() - t
    log(f"[4/5] filter: kept {sum(f.kept for f in findings)} of {len(findings)}")
    progress(0.85)

    # Stage 5: explanation generator
    t = time.perf_counter()
    if cfg.use_explanations:
        explain(backend, cs, findings, contexts)
    timings["explanation_generator"] = time.perf_counter() - t
    log("[5/5] explanations done")
    progress(1.0)
    return _report(cs, cfg.variant, getattr(backend, "name", "?"), findings, blocks, signals, timings,
                   asdict(cfg), contexts)


def _snippet(cs: ChangeSet, file: str, line: int, around: int = 2) -> list:
    lines = cs.files.get(file, "").splitlines()
    lo, hi = max(1, line - around), min(len(lines), line + around)
    return [[n, lines[n - 1]] for n in range(lo, hi + 1)]


def _report(cs, variant, model, findings, blocks, signals, timings, cfg, contexts=None) -> dict:
    timings["total"] = sum(timings.values())
    fdicts = []
    for f in findings:
        d = f.to_dict()
        d["snippet"] = _snippet(cs, f.file, f.line)
        fdicts.append(d)
    return {
        "variant": variant, "model": model, "config": cfg,
        "pr_size_added_lines": sum(len(h.added) for h in cs.hunks),
        "blocks": blocks,
        "findings": fdicts,
        "description": cs.description,
        "static_signals": [asdict(s) for s in signals],
        "contexts": contexts,
        "timings_sec": {k: round(v, 3) for k, v in timings.items()},
    }
