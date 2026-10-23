"""Shared data structures passed between the pipeline stages.

Every stage of Figure 3.1 reads and writes these objects, so this file is the
"vocabulary" of the whole system.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Hunk:
    """One contiguous block of changed code in one file (a 'changed block', Section 3.8.1)."""
    file: str
    header: str                                   # the "@@ -a,b +c,d @@" line
    added: list[tuple[int, str]] = field(default_factory=list)   # (new line number, text)
    removed: list[str] = field(default_factory=list)
    raw: str = ""                                 # the hunk as unified-diff text

    @property
    def start(self) -> int:
        return min(n for n, _ in self.added) if self.added else 0

    @property
    def end(self) -> int:
        return max(n for n, _ in self.added) if self.added else 0

    @property
    def added_line_numbers(self) -> set[int]:
        return {n for n, _ in self.added}

    def numbered_code(self) -> str:
        """Added lines prefixed with their line number, e.g. 'L12: x = 1'.
        Line numbers let the model point at exact lines (error localisation)."""
        return "\n".join(f"L{n}: {t}" for n, t in self.added)


@dataclass
class ChangeSet:
    """Output of change ingestion: the diff, changed files and PR description."""
    hunks: list[Hunk]
    files: dict[str, str]          # path -> full new contents of each changed file
    description: str = ""
    repo_root: str = "."


@dataclass
class ContextUnit:
    """An AST-based unit (function, class, method) or a guideline chunk."""
    uid: str
    file: str
    name: str
    kind: str                      # function | class | method | module_chunk | guideline
    start: int
    end: int
    code: str


@dataclass
class Signal:
    """A normalised warning from a static analyser (Section 3.4.2)."""
    tool: str
    file: str
    line: int
    rule: str
    message: str
    severity: str = "warning"


@dataclass
class Finding:
    """A candidate issue produced by the comment generator or the error detector."""
    file: str
    line: int
    category: str                  # logic | security | quality | review
    message: str
    confidence: float
    source: str                    # 'detector' or 'commenter'
    hunk_index: int = -1
    # Filled in by the false-positive filter (Section 3.4.4)
    static_agreement: float = 0.0
    context_support: float = 0.0
    score: float = 0.0
    kept: bool = True
    supporting_signals: list[str] = field(default_factory=list)
    # Filled in by the explanation generator (Section 3.4.5)
    explanation: Optional[dict] = None

    def to_dict(self) -> dict:
        return asdict(self)
