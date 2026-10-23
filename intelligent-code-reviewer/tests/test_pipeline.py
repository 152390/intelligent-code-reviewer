"""Unit tests. Run with:  python -m pytest -q"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "evaluation"))

from icr.ingestion import parse_unified_diff, from_diff_text  # noqa: E402
from icr.context_builder import extract_units, ContextBuilder  # noqa: E402
from icr.fp_filter import FilterConfig, apply_filter, mentioned_identifiers  # noqa: E402
from icr.models import Finding, Signal  # noqa: E402
from icr.llm import extract_json, HeuristicBackend  # noqa: E402
from icr.pipeline import PipelineConfig, run  # noqa: E402
from metrics import sus_score, prf  # noqa: E402

DIFF = """diff --git a/app/m.py b/app/m.py
--- a/app/m.py
+++ b/app/m.py
@@ -1,3 +1,5 @@
 def f(x):
-    return x
+    y = x + 1
+    return y
 
+z = 3
"""


def test_diff_line_numbers():
    hunks = parse_unified_diff(DIFF)
    assert len(hunks) == 1
    assert hunks[0].added == [(2, "    y = x + 1"), (3, "    return y"), (5, "z = 3")]
    assert hunks[0].removed == ["    return x"]


def test_non_supported_files_skipped():
    d = DIFF.replace("app/m.py", "README.md")
    assert parse_unified_diff(d) == []


def test_large_hunk_split():
    body = "".join(f"+x{i} = {i}\n" for i in range(200))
    d = f"--- a/a.py\n+++ b/a.py\n@@ -0,0 +1,200 @@\n{body}"
    hunks = parse_unified_diff(d, max_hunk_lines=80)
    assert [len(h.added) for h in hunks] == [80, 80, 40]


def test_python_units():
    src = "class A:\n    def m(self):\n        return 1\n\ndef g():\n    pass\n"
    names = {(u.name, u.kind) for u in extract_units("a.py", src)}
    assert ("A", "class") in names and ("A.m", "method") in names and ("g", "function") in names


def test_java_units():
    src = "public class Shop {\n  public int total(int a) {\n    return a;\n  }\n}\n"
    names = {u.name for u in extract_units("Shop.java", src)}
    assert "Shop" in names and "Shop.total" in names


def test_context_retrieves_cross_file_definition(tmp_path):
    (tmp_path / "util.py").write_text("def helper(v):\n    return None\n")
    new = "from util import helper\n\ndef use(v):\n    return helper(v) + 1\n"
    d = "--- a/main.py\n+++ b/main.py\n@@ -0,0 +1,4 @@\n" + "".join("+" + l + "\n" for l in new.splitlines())
    cs = from_diff_text(d, {"main.py": new}, repo_root=str(tmp_path))
    ctx = ContextBuilder(str(tmp_path), cs).retrieve(cs.hunks[0])
    assert any(u["name"] == "helper" and u["reason"] == "definition" for u in ctx["units"])


def test_filter_scores():
    cs = from_diff_text(DIFF, {"app/m.py": "def f(x):\n    y = x + 1\n    return y\n\nz = 3\n"})
    f1 = Finding("app/m.py", 2, "logic", "`y` may overflow", 0.9, "detector", 0)
    f2 = Finding("app/m.py", 5, "quality", "`nonexistent_var` is unused", 0.2, "commenter", 0)
    sig = [Signal("pylint", "app/m.py", 2, "X", "msg")]
    apply_filter([f1, f2], cs.hunks, [None], sig, FilterConfig())
    assert f1.static_agreement == 1.0 and f1.kept
    assert f2.context_support == 0.0 and not f2.kept


def test_identifiers():
    assert {"get_price"} <= mentioned_identifiers("`get_price()` can return None")


def test_extract_json():
    assert extract_json('Sure!\n```json\n{"a": [1, 2]}\n```') == {"a": [1, 2]}
    assert extract_json("no json") is None


def test_metrics():
    assert sus_score([5, 1] * 5) == 100.0
    assert prf(1, 1, 0)["precision"] == 0.5


def test_demo_pipeline_end_to_end():
    subprocess.run([sys.executable, os.path.join(ROOT, "examples", "make_demo_repo.py")], check=True,
                   capture_output=True)
    from icr.ingestion import from_git
    cs = from_git(os.path.join(ROOT, "examples", "demo_repo"), "HEAD~1")
    rep = run(cs, HeuristicBackend(), PipelineConfig())
    kept = [f for f in rep["findings"] if f["kept"]]
    cats = {f["category"] for f in kept}
    assert {"logic", "security", "quality"} <= cats
    assert not any(f["file"] == "shop/utils.py" for f in kept)      # the clean change is not flagged
    assert all(f["explanation"] for f in kept)
    rep_nc = run(cs, HeuristicBackend(), PipelineConfig.for_variant("no_context"))
    assert not any("get_price" in f["message"] for f in rep_nc["findings"])


def test_github_pr_import(monkeypatch):
    import requests
    from icr.ingestion import from_github_pr, parse_pr_url
    assert parse_pr_url("https://github.com/a/b/pull/7") == ("a/b", 7)
    new = "def f(x):\n    return eval(x)\n"

    class Resp:
        def __init__(self, data=None, text="", status=200):
            self._d, self.text, self.status_code, self.ok, self.headers = data, text, status, status == 200, {}

        def json(self):
            return self._d

        def raise_for_status(self):
            pass

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/pulls/7"):
            return Resp({"title": "Add f", "body": "adds f", "head": {"sha": "abc"}})
        if url.endswith("/pulls/7/files"):
            return Resp([{"filename": "m.py", "status": "added",
                          "patch": "@@ -0,0 +1,2 @@\n+def f(x):\n+    return eval(x)"},
                         {"filename": "README.md", "status": "modified", "patch": "@@ -1 +1 @@\n-a\n+b"}])
        if "/contents/m.py" in url:
            return Resp(text=new)
        raise AssertionError(url)

    monkeypatch.setattr(requests, "get", fake_get)
    cs, meta = from_github_pr("https://github.com/a/b/pull/7")
    assert meta["head_sha"] == "abc" and cs.files == {"m.py": new}
    assert [n for n, _ in cs.hunks[0].added] == [1, 2] and cs.description.startswith("Add f")
    rep = run(cs, HeuristicBackend(), PipelineConfig())
    assert any(f["kept"] and f["category"] == "security" for f in rep["findings"])


def test_patch_file_and_html(tmp_path):
    from icr.ingestion import from_patch_file
    from icr.output import save
    (tmp_path / "m.py").write_text("def f(x):\n    return eval(x)\n")
    patch = tmp_path / "c.patch"
    patch.write_text("--- a/m.py\n+++ b/m.py\n@@ -0,0 +1,2 @@\n+def f(x):\n+    return eval(x)\n")
    cs = from_patch_file(str(patch), str(tmp_path))
    rep = run(cs, HeuristicBackend(), PipelineConfig())
    save(rep, str(tmp_path / "out"))
    page = (tmp_path / "out" / "review_report.html").read_text()
    assert "eval" in page and "<html" in page
