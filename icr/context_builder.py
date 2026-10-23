"""Stage 2a - Context builder (Section 3.4.1).

Gives the model the information a human reviewer would look up:
  1. Parse every source file into an AST and split it into meaningful units
     (functions, classes, methods) instead of arbitrary blocks of text.
  2. Embed the units and store them in a vector index.
  3. For each changed block, retrieve
       a) STRUCTURAL context: the unit that encloses the change, and the
          definitions of functions the change calls (even if three files away);
       b) SEMANTIC context: the top-k most similar units from the vector index.
  4. Retrieve project guidelines (CONTRIBUTING.md, lint config) the same way.
This is retrieval-augmented generation (Lewis et al., 2020) applied to a repository.
"""
from __future__ import annotations
import ast
import os
import re
import numpy as np
from .models import ContextUnit, Hunk, ChangeSet
from .ingestion import language_of

SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "build", "dist", "target", ".idea"}
GUIDELINE_FILES = ["CONTRIBUTING.md", "CODING_STANDARDS.md", "STYLE.md", ".pylintrc",
                   "setup.cfg", "pyproject.toml", "checkstyle.xml", ".editorconfig"]

# ---------------------------------------------------------------- 1. AST parsing
_TS_NODE_TYPES = {
    "python": {"function_definition": "function", "class_definition": "class"},
    "java": {"method_declaration": "method", "constructor_declaration": "method",
             "class_declaration": "class", "interface_declaration": "class"},
}


def _tree_sitter_parser(lang: str):
    """Return a Tree-sitter parser for the language, or None if not installed."""
    try:
        from tree_sitter import Language, Parser
        if lang == "python":
            import tree_sitter_python as grammar
        elif lang == "java":
            import tree_sitter_java as grammar
        else:
            return None
        return Parser(Language(grammar.language()))
    except Exception:
        return None


def _units_tree_sitter(path: str, source: str, lang: str) -> list[ContextUnit] | None:
    parser = _tree_sitter_parser(lang)
    if parser is None:
        return None
    data = source.encode("utf-8")
    tree = parser.parse(data)
    lines = source.splitlines()
    units: list[ContextUnit] = []

    def walk(node, parents: list[str]):
        kind = _TS_NODE_TYPES[lang].get(node.type)
        name_parts = parents
        if kind:
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode("utf-8") if name_node is not None else "<anon>"
            qual = ".".join(parents + [name])
            start, end = node.start_point[0] + 1, node.end_point[0] + 1
            if kind == "function" and parents:
                kind = "method"
            units.append(ContextUnit(uid=f"{path}::{qual}", file=path, name=qual, kind=kind,
                                     start=start, end=end, code="\n".join(lines[start - 1:end])))
            name_parts = parents + [name]
        for child in node.children:
            walk(child, name_parts)

    walk(tree.root_node, [])
    return units


def _units_python_ast(path: str, source: str) -> list[ContextUnit]:
    """Fallback for Python using the standard-library `ast` module."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _units_chunks(path, source)
    lines = source.splitlines()
    units: list[ContextUnit] = []

    def visit(node, parents):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                kind = "class" if isinstance(child, ast.ClassDef) else ("method" if parents else "function")
                qual = ".".join(parents + [child.name])
                units.append(ContextUnit(uid=f"{path}::{qual}", file=path, name=qual, kind=kind,
                                         start=child.lineno, end=child.end_lineno,
                                         code="\n".join(lines[child.lineno - 1:child.end_lineno])))
                visit(child, parents + [child.name])
            else:
                visit(child, parents)

    visit(tree, [])
    return units


def _units_chunks(path: str, source: str, size: int = 40) -> list[ContextUnit]:
    """Last resort when a file cannot be parsed: fixed-size chunks."""
    lines = source.splitlines()
    return [ContextUnit(uid=f"{path}::chunk{i}", file=path, name=f"{os.path.basename(path)}:{i + 1}",
                        kind="module_chunk", start=i + 1, end=min(i + size, len(lines)),
                        code="\n".join(lines[i:i + size])) for i in range(0, len(lines), size)]


def extract_units(path: str, source: str) -> list[ContextUnit]:
    lang = language_of(path)
    if lang is None:
        return []
    units = _units_tree_sitter(path, source, lang)
    if units is None:
        units = _units_python_ast(path, source) if lang == "python" else _units_chunks(path, source)
    return units or _units_chunks(path, source)


def guideline_units(repo_root: str, chunk_lines: int = 25) -> list[ContextUnit]:
    units = []
    for name in GUIDELINE_FILES:
        p = os.path.join(repo_root, name)
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="ignore") as f:
                lines = f.read().splitlines()
            for i in range(0, len(lines), chunk_lines):
                units.append(ContextUnit(uid=f"{name}::{i}", file=name, name=name, kind="guideline",
                                         start=i + 1, end=i + chunk_lines,
                                         code="\n".join(lines[i:i + chunk_lines])))
    return units


# ---------------------------------------------------------------- 2. Embedding + vector index
def code_tokens(text: str) -> str:
    """Split identifiers so 'getUserName' and 'get_user_name' share tokens."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return " ".join(t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9]*", text.replace("_", " ")))


class TfidfEmbedder:
    """TF-IDF over identifier tokens, written with numpy only (no scikit-learn), so the
    standalone executable stays small. tf = 1 + log(count); idf = log((1+N)/(1+df)) + 1."""

    def __init__(self):
        self.vocab: dict[str, int] = {}
        self.idf = None

    def fit(self, texts: list[str]):
        df: dict[str, int] = {}
        for t in texts:
            for tok in set(code_tokens(t).split()):
                df[tok] = df.get(tok, 0) + 1
        self.vocab = {tok: i for i, tok in enumerate(sorted(df))}
        n = len(texts)
        self.idf = np.array([np.log((1 + n) / (1 + df[t])) + 1 for t in sorted(df)]) if df else np.ones(1)
        return self

    def transform(self, texts: list[str]) -> np.ndarray:
        m = np.zeros((len(texts), max(1, len(self.vocab))))
        for r, t in enumerate(texts):
            counts: dict[int, int] = {}
            for tok in code_tokens(t).split():
                if tok in self.vocab:
                    counts[self.vocab[tok]] = counts.get(self.vocab[tok], 0) + 1
            for c, k in counts.items():
                m[r, c] = (1 + np.log(k)) * self.idf[c]
        return m


class Embedder:
    """Dense embeddings with sentence-transformers when available; otherwise a
    TF-IDF embedding over identifier tokens (works offline, no GPU)."""

    def __init__(self, model_name: str | None = None):
        self.model = None
        self.tfidf = None
        self.kind = "tfidf"
        if model_name:
            try:
                from sentence_transformers import SentenceTransformer
                self.model = SentenceTransformer(model_name)
                self.kind = f"dense:{model_name}"
            except Exception as e:  # no package or no internet
                print(f"[context] could not load embedding model ({e}); using TF-IDF")

    def fit(self, texts: list[str]):
        if self.model is None:
            self.tfidf = TfidfEmbedder().fit(texts or ["empty"])
        return self

    def encode(self, texts: list[str]) -> np.ndarray:
        if self.model is not None:
            vecs = np.asarray(self.model.encode(texts, normalize_embeddings=True))
        else:
            vecs = self.tfidf.transform(texts)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / np.maximum(norms, 1e-9)


class VectorIndex:
    """A minimal in-memory vector store using cosine similarity."""

    def __init__(self, embedder: Embedder):
        self.embedder = embedder
        self.units: list[ContextUnit] = []
        self.matrix = None

    def build(self, units: list[ContextUnit]):
        self.units = units
        texts = [f"{u.name}\n{u.code}" for u in units]
        self.embedder.fit(texts)
        self.matrix = self.embedder.encode(texts) if units else None
        return self

    def search(self, query: str, k: int = 3, kinds: set[str] | None = None,
               exclude: set[str] | None = None) -> list[tuple[ContextUnit, float]]:
        if self.matrix is None:
            return []
        sims = self.matrix @ self.embedder.encode([query])[0]
        out = []
        for i in np.argsort(-sims):
            u = self.units[i]
            if kinds and u.kind not in kinds:
                continue
            if exclude and u.uid in exclude:
                continue
            if sims[i] <= 0:
                break
            out.append((u, float(sims[i])))
            if len(out) >= k:
                break
        return out


# ---------------------------------------------------------------- 3. Retrieval
CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
KEYWORDS = {"if", "for", "while", "return", "print", "len", "range", "int", "str", "float", "list",
            "dict", "set", "tuple", "super", "isinstance", "new", "switch", "catch", "sizeof"}


class ContextBuilder:
    def __init__(self, repo_root: str, changeset: ChangeSet, top_k: int = 3,
                 max_chars: int = 6000, embedding_model: str | None = None):
        self.repo_root = repo_root
        self.top_k = top_k
        self.max_chars = max_chars
        units: list[ContextUnit] = []
        seen_files = set()
        # Changed files: use the NEW contents from the change set.
        for path, src in changeset.files.items():
            units += extract_units(path, src)
            seen_files.add(path)
        # The rest of the repository.
        for path in self._repo_files():
            if path not in seen_files:
                try:
                    with open(os.path.join(repo_root, path), encoding="utf-8", errors="ignore") as f:
                        units += extract_units(path, f.read())
                except OSError:
                    pass
        units += guideline_units(repo_root)
        self.units = units
        self.by_name: dict[str, list[ContextUnit]] = {}
        for u in units:
            if u.kind != "guideline":
                self.by_name.setdefault(u.name.split(".")[-1], []).append(u)
        self.index = VectorIndex(Embedder(embedding_model)).build(units)
        self._files = dict(changeset.files)

    def units_file_lines(self, path: str) -> list[str]:
        if path not in self._files:
            try:
                with open(os.path.join(self.repo_root, path), encoding="utf-8", errors="ignore") as f:
                    self._files[path] = f.read()
            except OSError:
                self._files[path] = ""
        return self._files[path].splitlines()

    def _repo_files(self):
        for root, dirs, files in os.walk(self.repo_root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fn in files:
                full = os.path.join(root, fn)
                if language_of(fn):
                    yield os.path.relpath(full, self.repo_root).replace(os.sep, "/")

    def enclosing_unit(self, hunk: Hunk) -> ContextUnit | None:
        best = None
        for u in self.units:
            if u.file == hunk.file and u.kind != "guideline" and u.start <= hunk.start and u.end >= hunk.end:
                if best is None or (u.end - u.start) < (best.end - best.start):
                    best = u           # innermost unit wins
        return best

    @staticmethod
    def _inside_change(u: ContextUnit, hunk: Hunk) -> bool:
        """True if the unit is (mostly) the changed code itself - no new information."""
        if u.file != hunk.file:
            return False
        span = set(range(u.start, u.end + 1))
        return len(span & hunk.added_line_numbers) >= 0.5 * len(span)

    def retrieve(self, hunk: Hunk) -> dict:
        """Return the context for one changed block."""
        code = "\n".join(t for _, t in hunk.added)
        picked: list[tuple[str, ContextUnit]] = []
        used: set[str] = set()

        enc = self.enclosing_unit(hunk)
        if enc and not self._inside_change(enc, hunk):
            # Show only the SURROUNDING lines of the enclosing unit (the changed lines are
            # already in the prompt), e.g. the class header and the other methods.
            src = self.units_file_lines(enc.file)
            around = [f"{src[n - 1]}" for n in range(enc.start, enc.end + 1)
                      if n not in hunk.added_line_numbers and n - 1 < len(src)]
            picked.append(("enclosing", ContextUnit(enc.uid, enc.file, enc.name, enc.kind,
                                                    enc.start, enc.end, "\n".join(around))))
            used.add(enc.uid)
        # Definitions of functions called in the changed lines (structural retrieval).
        for name in dict.fromkeys(CALL_RE.findall(code)):
            if name in KEYWORDS:
                continue
            for u in self.by_name.get(name, [])[:2]:
                if u.uid not in used and not self._inside_change(u, hunk):
                    picked.append(("definition", u))
                    used.add(u.uid)
        used |= {u.uid for u in self.units if self._inside_change(u, hunk)}
        # Semantic neighbours from the vector index.
        for u, _ in self.index.search(code, k=self.top_k, kinds={"function", "method", "class", "module_chunk"},
                                      exclude=used):
            picked.append(("similar", u))
            used.add(u.uid)
        guidelines = [u for u, _ in self.index.search(code, k=2, kinds={"guideline"})]

        # Respect a character budget so the prompt fits the model's context window.
        budget, units = self.max_chars, []
        for reason, u in picked:
            if len(u.code) > budget:
                continue
            budget -= len(u.code)
            units.append({"reason": reason, "name": u.name, "file": u.file,
                          "start": u.start, "end": u.end, "code": u.code})
        return {"units": units,
                "guidelines": [{"file": g.file, "text": g.code[:800]} for g in guidelines]}
