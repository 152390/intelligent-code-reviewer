"""Stage 2b - Static analysis module (Section 3.4.2).

Rule-based tools are not discarded: their output is treated as EVIDENCE.
  * Pylint   - Python bugs and code quality
  * Semgrep  - security patterns, Python and Java (local rules in rules/semgrep_rules.yml)
  * SpotBugs - Java bytecode analysis (needs compiled .class files; optional)
  * builtin  - the same security patterns as rules/semgrep_rules.yml, checked line by line in
               Python. Used automatically when Semgrep is not installed (e.g. on Windows, where
               Semgrep does not run natively), so security evidence is never missing.
All warnings are normalised into Signal objects so the rest of the pipeline does
not care which tool produced them. Signals are used twice: as hints in the
prompt, and as the 'static agreement' input of the false-positive filter.
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
import tempfile
import io
import re
import xml.etree.ElementTree as ET
from .models import ChangeSet, Signal
from .ingestion import language_of
from .resources import resource_path

DEFAULT_SEMGREP_RULES = resource_path("rules", "semgrep_rules.yml")
# Pylint checks that only produce noise for review purposes.
PYLINT_DISABLE = "C0114,C0115,C0116,E0401,C0411,C0412,C0413,R0903"


def _write_snapshot(cs: ChangeSet) -> str:
    """Write the new versions of the changed files to a temp folder, so the tools
    analyse exactly the code under review (works for git checkouts and for datasets)."""
    tmp = tempfile.mkdtemp(prefix="icr_")
    for path, src in cs.files.items():
        full = os.path.join(tmp, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(src)
    return tmp


def run_pylint(root: str, files: list[str]) -> list[Signal]:
    """Run Pylint inside this process (works inside the standalone executable too)."""
    if not files:
        return []
    try:
        from pylint.lint import Run
        from pylint.reporters.json_reporter import JSONReporter
    except ImportError:
        print("[static] pylint not installed")
        return []
    buf = io.StringIO()
    args = [f"--disable={PYLINT_DISABLE}", "--score=n", "--persistent=n",
            f"--rcfile={os.devnull}", *[os.path.join(root, f) for f in files]]
    try:
        Run(args, reporter=JSONReporter(buf), exit=False)
        items = json.loads(buf.getvalue() or "[]")
    except Exception as e:
        print(f"[static] pylint failed: {e}")
        return []
    out = []
    for i in items:
        if i["message-id"].startswith("F"):        # pylint's own crashes are not evidence about the code
            continue
        rel = os.path.relpath(os.path.abspath(i["path"]), root).replace(os.sep, "/")
        out.append(Signal("pylint", rel, int(i["line"]), f'{i["message-id"]}:{i["symbol"]}',
                          i["message"], i["type"]))
    return out


# Line-based equivalents of rules/semgrep_rules.yml: (rule id, languages, regex, message, severity)
BUILTIN_RULES = [
    ("sql-injection-string-format", {"python"}, r"\.execute\(\s*(f[\"']|[\"'][^\"']*[\"']\s*(%|\+|\.format))",
     "SQL query built with string formatting; user input may reach the database unescaped.", "error"),
    ("dangerous-eval", {"python"}, r"(?<![\w.])(eval|exec)\s*\(",
     "eval()/exec() on dynamic input can execute arbitrary code.", "error"),
    ("subprocess-shell-true", {"python"}, r"subprocess\.\w+\(.*shell\s*=\s*True",
     "subprocess call with shell=True is vulnerable to command injection.", "warning"),
    ("hardcoded-secret", {"python", "java"},
     r"(?i)(password|passwd|secret|api_key|apikey|token)\w*\s*=\s*[\"'][^\"']{6,}[\"']",
     "Possible hard-coded secret or credential.", "warning"),
    ("pickle-load", {"python"}, r"pickle\.loads?\(", "Unpickling untrusted data can execute arbitrary code.",
     "warning"),
    ("java-sql-concat", {"java"}, r"\.(executeQuery|executeUpdate|execute)\(\s*\"[^\"]*\"\s*\+",
     "SQL query built by string concatenation; use a PreparedStatement.", "error"),
]


def run_builtin_rules(cs: ChangeSet) -> list[Signal]:
    out = []
    for path, src in cs.files.items():
        lang = language_of(path)
        for n, line in enumerate(src.splitlines(), 1):
            if line.lstrip().startswith(("#", "//")):
                continue
            for rid, langs, pat, msg, sev in BUILTIN_RULES:
                if lang in langs and re.search(pat, line):
                    out.append(Signal("builtin", path, n, rid, msg, sev))
    return out


def run_semgrep(root: str, files: list[str], config: str = DEFAULT_SEMGREP_RULES) -> list[Signal]:
    if not files or not shutil.which("semgrep"):
        return []
    cmd = ["semgrep", "scan", "--config", config, "--json", "--metrics=off", "--quiet", *files]
    try:
        out = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=300).stdout
        data = json.loads(out or "{}")
    except Exception as e:
        print(f"[static] semgrep failed: {e}")
        return []
    sigs = []
    for r in data.get("results", []):
        sigs.append(Signal("semgrep", r["path"].replace(os.sep, "/"), int(r["start"]["line"]),
                           r["check_id"].split(".")[-1], r["extra"].get("message", ""),
                           r["extra"].get("severity", "WARNING").lower()))
    return sigs


def run_spotbugs(classes_dir: str | None, java_files: list[str]) -> list[Signal]:
    """SpotBugs analyses compiled bytecode. Build the project first (mvn/gradle),
    then pass the classes folder with --spotbugs-classes."""
    if not classes_dir or not java_files or not shutil.which("spotbugs"):
        return []
    out_xml = os.path.join(tempfile.mkdtemp(), "spotbugs.xml")
    try:
        subprocess.run(["spotbugs", "-textui", "-xml:withMessages", "-output", out_xml, classes_dir],
                       capture_output=True, timeout=600)
        tree = ET.parse(out_xml)
    except Exception as e:
        print(f"[static] spotbugs failed: {e}")
        return []
    sigs = []
    for bug in tree.getroot().iter("BugInstance"):
        sl = bug.find("SourceLine")
        if sl is None or sl.get("start") is None:
            continue
        src = sl.get("sourcepath", "")
        match = next((f for f in java_files if f.endswith(src)), None)
        if match:
            msg = bug.findtext("LongMessage") or bug.get("type")
            sigs.append(Signal("spotbugs", match, int(sl.get("start")), bug.get("type"), msg))
    return sigs


def analyse(cs: ChangeSet, spotbugs_classes: str | None = None,
            semgrep_config: str = DEFAULT_SEMGREP_RULES) -> list[Signal]:
    root = _write_snapshot(cs)
    py = [p for p in cs.files if language_of(p) == "python"]
    java = [p for p in cs.files if language_of(p) == "java"]
    signals = run_pylint(root, py)
    if shutil.which("semgrep"):
        signals += run_semgrep(root, py + java, semgrep_config)
    else:
        signals += run_builtin_rules(cs)
    signals += run_spotbugs(spotbugs_classes, java)
    shutil.rmtree(root, ignore_errors=True)
    return signals


def signals_near(signals: list[Signal], file: str, line: int, tolerance: int = 1) -> list[Signal]:
    """Static warnings on the same file within +/- `tolerance` lines."""
    return [s for s in signals if s.file == file and abs(s.line - line) <= tolerance]


def signals_for_hunk(signals: list[Signal], file: str, start: int, end: int) -> list[Signal]:
    return [s for s in signals if s.file == file and start - 1 <= s.line <= end + 1]
