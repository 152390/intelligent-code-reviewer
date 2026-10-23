"""Stage 5 - Explanation generator (Section 3.4.5).

Every finding that survives the filter is given a short plain-language explanation:
the problem, the evidence in the code, why it matters, and a suggested direction
for fixing it. The fix is NEVER applied: the output stays advisory.
"""
from __future__ import annotations
from .models import Finding, ChangeSet
from .prompts import explain_prompt
from .llm import extract_json


def _code_line(cs: ChangeSet, f: Finding) -> str:
    lines = cs.files.get(f.file, "").splitlines()
    return lines[f.line - 1] if 0 < f.line <= len(lines) else ""


def explain(backend, cs: ChangeSet, findings: list[Finding], contexts: list[dict | None]) -> None:
    for f in findings:
        if not f.kept:
            continue
        evidence = list(f.supporting_signals)
        ctx = contexts[f.hunk_index] if f.hunk_index >= 0 else None
        if ctx:
            evidence += [f"retrieved {u['reason']} context: {u['name']} ({u['file']})" for u in ctx["units"][:3]]
        data = extract_json(backend.generate(explain_prompt(f, _code_line(cs, f), evidence)))
        if not isinstance(data, dict):
            data = {"problem": f.message, "evidence": f"Line {f.line} of {f.file}",
                    "why_it_matters": "", "suggestion": ""}
        f.explanation = {k: str(data.get(k, "")) for k in ("problem", "evidence", "why_it_matters", "suggestion")}
