"""Prompt templates (Section 3.4.3 and 3.4.5).

IMPORTANT DESIGN POINT: the comment generator and the error detector receive the
SAME context block (format_context_block). The training data in training/prepare_data.py
is built with these same functions, so what the model sees during LoRA fine-tuning
matches what it sees at inference time.
"""
from __future__ import annotations
from .models import Hunk, Signal, Finding

SYSTEM = ("You are a careful senior code reviewer. You only report problems you can "
          "justify from the code shown. You answer with JSON only, no other text.")


def format_context_block(hunk: Hunk, context: dict | None, signals: list[Signal] | None,
                         description: str = "", language: str = "python") -> str:
    parts = [f"### FILE\n{hunk.file} ({language})"]
    if description:
        parts.append(f"### PULL REQUEST DESCRIPTION\n{description[:600]}")
    parts.append(f"### CHANGED CODE (added lines, with line numbers)\n{hunk.numbered_code()}")
    if hunk.removed:
        parts.append("### REMOVED LINES\n" + "\n".join(hunk.removed[:30]))
    if context and context.get("units"):
        ctx = []
        for u in context["units"]:
            ctx.append(f"--- [{u['reason']}] {u['name']} ({u['file']}:{u['start']}-{u['end']})\n{u['code']}")
        parts.append("### REPOSITORY CONTEXT\n" + "\n".join(ctx))
    if context and context.get("guidelines"):
        parts.append("### PROJECT GUIDELINES\n" + "\n".join(g["text"] for g in context["guidelines"]))
    if signals:
        parts.append("### STATIC ANALYSIS WARNINGS (hints, may be wrong)\n" +
                     "\n".join(f"L{s.line} [{s.tool}:{s.rule}] {s.message}" for s in signals[:15]))
    return "\n\n".join(parts)


def review_prompt(block: str) -> str:
    return ("TASK: REVIEW_COMMENTS\n"
            "Write review comments a senior reviewer would leave on the changed code. "
            "Only comment on added lines. Prefer specific, actionable comments over generic ones.\n\n"
            f"{block}\n\n"
            'Respond as JSON: {"comments": [{"line": <int>, "comment": "<text>", '
            '"confidence": <0.0-1.0>}]}. Use an empty list if nothing is worth saying.')


def detect_prompt(block: str) -> str:
    return ("TASK: DETECT_ERRORS\n"
            "Decide whether the changed code is faulty or clean. If faulty, list each fault "
            "with the exact line and one category: logic (wrong behaviour), security "
            "(vulnerability), or quality (maintainability problem likely to cause bugs).\n\n"
            f"{block}\n\n"
            'Respond as JSON: {"label": "faulty"|"clean", "findings": [{"line": <int>, '
            '"category": "logic"|"security"|"quality", "message": "<text>", "confidence": <0.0-1.0>}]}')


def explain_prompt(finding: Finding, code_line: str, evidence: list[str]) -> str:
    ev = "\n".join(f"- {e}" for e in evidence) or "- none"
    return ("TASK: EXPLAIN_FINDING\n"
            "Explain this review finding in plain language for the developer. Do not rewrite their code.\n\n"
            f"FINDING: {finding.message}\nCATEGORY: {finding.category}\n"
            f"LOCATION: {finding.file} line {finding.line}\nCODE: {code_line.strip()}\n"
            f"SUPPORTING EVIDENCE:\n{ev}\n\n"
            'Respond as JSON: {"problem": "<what is wrong>", "evidence": "<what in the code shows it>", '
            '"why_it_matters": "<impact>", "suggestion": "<direction for fixing, not a full patch>"}')
