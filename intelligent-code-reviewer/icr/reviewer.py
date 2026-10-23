"""Stage 3 - Review comment generator and error detector (Section 3.4.3).

Both run on the same open-weight LLM (with the same LoRA adapter) and the SAME
context block; they differ only in the task instruction. That shared input is what
lets review and error detection live in one system rather than two tools.
"""
from __future__ import annotations
from .models import Hunk, Finding
from .llm import extract_json

VALID_CATEGORIES = {"logic", "security", "quality"}


def _clamp(x, lo=0.0, hi=1.0) -> float:
    try:
        return max(lo, min(hi, float(x)))
    except (TypeError, ValueError):
        return 0.5


def _snap_line(line, hunk: Hunk) -> int | None:
    """Keep findings on the changed block. Lines slightly off are snapped to the
    nearest added line; anything far away is discarded (the model is pointing at
    code that is not part of the change)."""
    try:
        line = int(line)
    except (TypeError, ValueError):
        return None
    added = sorted(hunk.added_line_numbers)
    if line in hunk.added_line_numbers:
        return line
    nearest = min(added, key=lambda n: abs(n - line))
    return nearest if abs(nearest - line) <= 2 else None


def _confidence(item: dict, backend) -> float:
    """Use the model's token-probability confidence when the backend provides it
    (hf backend); otherwise the confidence the model wrote in its JSON; else 0.5."""
    seq = getattr(backend, "last_confidence", None)
    if seq is not None:
        return _clamp(seq)
    return _clamp(item.get("confidence", 0.5))


def generate_comments(backend, prompt: str, hunk: Hunk, idx: int) -> tuple[list[Finding], str]:
    raw = backend.generate(prompt)
    data = extract_json(raw) or {}
    out = []
    for c in (data.get("comments", []) if isinstance(data, dict) else []):
        line = _snap_line(c.get("line"), hunk)
        text = str(c.get("comment", "")).strip()
        if line and text:
            out.append(Finding(file=hunk.file, line=line, category="review", message=text,
                               confidence=_confidence(c, backend), source="commenter", hunk_index=idx))
    return out, raw


def detect_errors(backend, prompt: str, hunk: Hunk, idx: int) -> tuple[list[Finding], str, str]:
    raw = backend.generate(prompt)
    data = extract_json(raw) or {}
    label = str(data.get("label", "clean")).lower() if isinstance(data, dict) else "clean"
    out = []
    for f in (data.get("findings", []) if isinstance(data, dict) else []):
        line = _snap_line(f.get("line"), hunk)
        cat = str(f.get("category", "quality")).lower()
        msg = str(f.get("message", "")).strip()
        if line and msg:
            out.append(Finding(file=hunk.file, line=line, category=cat if cat in VALID_CATEGORIES else "quality",
                               message=msg, confidence=_confidence(f, backend),
                               source="detector", hunk_index=idx))
    if out:
        label = "faulty"
    return out, label, raw
