"""Desktop application (the 'ICR-Reviewer' executable).

Tabs
  Review   choose what to review, the model, and the options; press Run review
  Results  every finding with its explanation, score breakdown and code snippet
  Log      what each pipeline stage did (useful when presenting the pipeline)
  Help     short instructions; full instructions are in README.txt

The review runs in a background thread so the window never freezes; messages come
back to the window through a queue that is checked every 100 ms.
"""
from __future__ import annotations
import json
import os
import queue
import subprocess
import sys
import threading
import traceback
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

from . import __version__, ingestion, output
from .pipeline import PipelineConfig, run
from .fp_filter import FilterConfig
from .llm import make_backend, test_server
from .resources import app_data_dir

SETTINGS = os.path.join(app_data_dir(), "settings.json")
BACKENDS = {"Demo stub (offline, no AI model)": "heuristic",
            "Local LLM server (Ollama / LM Studio / vLLM)": "openai"}
VARIANT_LABELS = {
    "full": "Full system (recommended)",
    "no_context": "Ablation: without repository context",
    "no_static": "Ablation: without static analysis",
    "no_filter": "Ablation: without false-positive filter",
    "no_explanation": "Ablation: without explanations",
    "llm_diff_only": "Baseline: LLM with the diff only",
    "static_only": "Baseline: static analysers only",
}
DEFAULTS = {"mode": "git", "repo": "", "base": "HEAD~1", "head": "HEAD", "patch": "", "pr_url": "",
            "backend": "Demo stub (offline, no AI model)", "base_url": "http://localhost:11434/v1",
            "model": "qwen2.5-coder:7b", "variant": "full", "threshold": 0.45, "filter_config": "",
            "out": os.path.join(os.path.expanduser("~"), "ICR-Reviews")}
HELP = """QUICK START
1. Click "Create demo project..." and choose an empty folder. (Needs Git.)
2. Leave the model on "Demo stub" and click "Run review".
3. Open the Results tab, click any finding to read its explanation, or click "Open HTML report".

WHAT TO REVIEW
- Git repository: a project folder that is a Git repository. Base = the commit/branch the change starts
  from (HEAD~1 = the previous commit, or a branch name such as main). Head = the commit with the change.
- Patch file: a .diff/.patch file plus the project folder that already contains the changed code.
- GitHub pull request: paste the PR web address. A token is needed for private repositories,
  for more than 60 requests per hour, and for posting comments.

MODEL
- Demo stub: built-in pattern rules so every stage can be shown without an AI model.
  It is NOT the research model.
- Local LLM server: an open-weight model served by Ollama or LM Studio on this computer.
  Click "Test connection" to check it and to list the models it has.

OPTIONS
- Variant: the full system, or one of the ablations / baselines used in the evaluation.
- Threshold: findings scoring below it are hidden as likely false positives (they still appear,
  greyed out, when "Show filtered findings" is ticked in the Results tab).

The review is advisory: nothing in your project is changed. See README.txt for the full guide."""


def open_path(path: str):
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"ICR Reviewer {__version__} - Intelligent Code Review and Error Detection")
        root.geometry("1040x720")
        root.minsize(860, 600)
        self.q: queue.Queue = queue.Queue()
        self.report: dict | None = None
        self.out_dir: str | None = None
        self.running = False
        self.s = {**DEFAULTS, **self._load_settings()}
        self.v = {k: tk.StringVar(value=str(self.s[k])) for k in DEFAULTS if k != "threshold"}
        self.v_threshold = tk.DoubleVar(value=float(self.s["threshold"]))
        self.v_token = tk.StringVar(value="")
        self.v_post = tk.BooleanVar(value=False)
        self.v_show_dropped = tk.BooleanVar(value=False)

        style = ttk.Style()
        if "clam" in style.theme_names() and not sys.platform.startswith("win"):
            style.theme_use("clam")
        style.configure("Run.TButton", font=("TkDefaultFont", 11, "bold"), padding=8)
        style.configure("Green.Horizontal.TProgressbar", background="#2e7d32")

        self.nb = ttk.Notebook(root)
        self.nb.pack(side="top", fill="both", expand=True, padx=8, pady=8)
        self.tab_review = ttk.Frame(self.nb, padding=10)
        self.tab_results = ttk.Frame(self.nb, padding=10)
        self.tab_log = ttk.Frame(self.nb, padding=10)
        self.tab_help = ttk.Frame(self.nb, padding=10)
        for tab, name in ((self.tab_review, "1  Review"), (self.tab_results, "2  Results"),
                          (self.tab_log, "Log"), (self.tab_help, "Help")):
            self.nb.add(tab, text=name)
        self._build_review()
        self._build_results()
        self._build_log()
        self._build_help()
        self._mode_changed()
        root.after(100, self._poll)

    # ------------------------------------------------------------------ settings
    def _load_settings(self) -> dict:
        try:
            with open(SETTINGS, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_settings(self):
        data = {k: var.get() for k, var in self.v.items()}
        data["threshold"] = round(self.v_threshold.get(), 2)
        try:
            with open(SETTINGS, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    # ------------------------------------------------------------------ review tab
    def _row(self, parent, r, label, var, browse=None, show=None, width=60):
        """One labelled input row. Returns its widgets so the row can be hidden/shown."""
        lab = ttk.Label(parent, text=label)
        lab.grid(row=r, column=0, sticky="w", pady=3, padx=(0, 8))
        e = ttk.Entry(parent, textvariable=var, width=width, show=show or "")
        e.grid(row=r, column=1, sticky="ew" if width >= 60 else "w", pady=3)
        widgets = [lab, e]
        if browse:
            b = ttk.Button(parent, text="Browse...", command=browse)
            b.grid(row=r, column=2, padx=(6, 0))
            widgets.append(b)
        return widgets

    @staticmethod
    def _show_rows(rows, on: bool):
        for w in rows:
            w.grid() if on else w.grid_remove()

    def _build_review(self):
        t = self.tab_review
        t.columnconfigure(0, weight=1)

        src = ttk.LabelFrame(t, text=" 1. What to review ", padding=10)
        src.grid(row=0, column=0, sticky="ew")
        src.columnconfigure(1, weight=1)
        modes = ttk.Frame(src)
        modes.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        for val, txt in (("git", "Git repository"), ("patch", "Patch file"), ("github", "GitHub pull request")):
            ttk.Radiobutton(modes, text=txt, value=val, variable=self.v["mode"],
                            command=self._mode_changed).pack(side="left", padx=(0, 18))
        self.w_repo = self._row(src, 1, "Project folder:", self.v["repo"], self._browse_repo)
        self.w_base = self._row(src, 2, "Base (before):", self.v["base"], width=24)
        self.w_head = self._row(src, 3, "Head (after):", self.v["head"], width=24)
        self.w_patch = self._row(src, 4, "Patch file:", self.v["patch"], self._browse_patch)
        self.w_pr = self._row(src, 5, "Pull request URL:", self.v["pr_url"])
        self.w_token = self._row(src, 6, "GitHub token (optional):", self.v_token, show="*")
        self.hint = ttk.Label(src, foreground="#666", wraplength=820, justify="left")
        self.hint.grid(row=7, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Button(src, text="Create demo project...", command=self._create_demo).grid(
            row=0, column=2, sticky="e", pady=(0, 6))

        mdl = ttk.LabelFrame(t, text=" 2. Model ", padding=10)
        mdl.grid(row=1, column=0, sticky="ew", pady=8)
        mdl.columnconfigure(1, weight=1)
        ttk.Label(mdl, text="Backend:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        cb = ttk.Combobox(mdl, textvariable=self.v["backend"], values=list(BACKENDS), state="readonly", width=48)
        cb.grid(row=0, column=1, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda e: self._backend_changed())
        self.lbl_backend_note = ttk.Label(mdl, foreground="#666")
        self.lbl_backend_note.grid(row=4, column=0, columnspan=3, sticky="w")
        self.w_url = self._row(mdl, 1, "Server URL:", self.v["base_url"])
        self.w_model = self._row(mdl, 2, "Model name:", self.v["model"], width=36)
        conn = self.conn = ttk.Frame(mdl)
        conn.grid(row=2, column=1, sticky="e", pady=3)
        self.btn_test = ttk.Button(conn, text="Test connection", command=self._test_connection)
        self.lbl_conn = ttk.Label(conn, text="", foreground="#666")
        self.lbl_conn.pack(side="left", padx=10)
        self.btn_test.pack(side="left")

        opt = ttk.LabelFrame(t, text=" 3. Options ", padding=10)
        opt.grid(row=2, column=0, sticky="ew")
        opt.columnconfigure(1, weight=1)
        ttk.Label(opt, text="Variant:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.v_variant_label = tk.StringVar(value=VARIANT_LABELS.get(self.v["variant"].get(), VARIANT_LABELS["full"]))
        ttk.Combobox(opt, textvariable=self.v_variant_label, values=list(VARIANT_LABELS.values()),
                     state="readonly", width=48).grid(row=0, column=1, sticky="w")
        ttk.Label(opt, text="Filter threshold:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        th = ttk.Frame(opt)
        th.grid(row=1, column=1, sticky="w")
        ttk.Scale(th, from_=0.0, to=1.0, variable=self.v_threshold, length=260,
                  command=lambda v: self.lbl_th.config(text=f"{float(v):.2f}")).pack(side="left")
        self.lbl_th = ttk.Label(th, text=f"{self.v_threshold.get():.2f}", width=6)
        self.lbl_th.pack(side="left", padx=8)
        ttk.Label(th, text="higher = fewer findings, fewer false alarms", foreground="#666").pack(side="left")
        self._row(opt, 2, "Tuned filter file (optional):", self.v["filter_config"], self._browse_filter)
        self._row(opt, 3, "Save reports to:", self.v["out"], self._browse_out)
        self.chk_post = ttk.Checkbutton(opt, text="Post findings to the GitHub pull request as comments (needs a token)",
                                        variable=self.v_post)
        self.chk_post.grid(row=4, column=1, sticky="w", pady=(4, 0))

        run = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        run.pack(side="bottom", fill="x", before=self.nb)
        run.columnconfigure(1, weight=1)
        self.btn_run = ttk.Button(run, text="Run review", style="Run.TButton", command=self._start_review)
        self.btn_run.grid(row=0, column=0, rowspan=2, padx=(0, 12))
        self.pb = ttk.Progressbar(run, mode="determinate", maximum=100,
                                  style="Green.Horizontal.TProgressbar")
        self.pb.grid(row=0, column=1, sticky="ew")
        self.lbl_status = ttk.Label(run, text="Ready.")
        self.lbl_status.grid(row=1, column=1, sticky="w")
        self._backend_changed()

    def _mode_changed(self):
        mode = self.v["mode"].get()
        self._show_rows(self.w_base + self.w_head, mode == "git")
        self._show_rows(self.w_patch, mode == "patch")
        self._show_rows(self.w_pr + self.w_token, mode == "github")
        self.w_repo[0].configure(text="Local clone (optional):" if mode == "github" else "Project folder:")
        self.chk_post.grid() if mode == "github" else self.chk_post.grid_remove()
        self.hint.configure(text={
            "git": "The project folder must be a Git repository. Base = where the change starts (HEAD~1 = previous "
                   "commit, or a branch such as main); Head = the commit containing the change (HEAD = latest).",
            "patch": "The project folder must already contain the changed code. Create a patch with: "
                     "git diff main > change.patch",
            "github": "Paste e.g. https://github.com/owner/repo/pull/12. Project folder is optional: if it is a "
                      "local clone of the repository, the rest of the repository is used as context.",
        }[mode])

    def _backend_changed(self):
        on = BACKENDS.get(self.v["backend"].get()) == "openai"
        self._show_rows(self.w_url + self.w_model + [self.conn], on)
        self.lbl_backend_note.configure(
            text="Built-in pattern rules: shows every pipeline stage without an AI model. Not the research model.")
        self._show_rows([self.lbl_backend_note], not on)

    def _browse_repo(self):
        d = filedialog.askdirectory(title="Choose the project folder")
        if d:
            self.v["repo"].set(d)

    def _browse_patch(self):
        f = filedialog.askopenfilename(title="Choose a patch file",
                                       filetypes=[("Patch files", "*.patch *.diff"), ("All files", "*.*")])
        if f:
            self.v["patch"].set(f)

    def _browse_filter(self):
        f = filedialog.askopenfilename(title="Choose filter_config.json", filetypes=[("JSON", "*.json")])
        if f:
            self.v["filter_config"].set(f)

    def _browse_out(self):
        d = filedialog.askdirectory(title="Where should reports be saved?")
        if d:
            self.v["out"].set(d)

    def _create_demo(self):
        d = filedialog.askdirectory(title="Choose (or create) an EMPTY folder for the demo project")
        if not d:
            return
        if os.listdir(d) and not messagebox.askyesno(
                "Folder not empty", f"{d} is not empty. Its contents will be DELETED and replaced by the demo "
                                    "project. Continue?"):
            return
        try:
            from .demo import create_demo_repo
            root = create_demo_repo(d)
        except Exception as e:
            messagebox.showerror("Could not create demo", str(e))
            return
        self.v["mode"].set("git")
        self.v["repo"].set(root)
        self.v["base"].set("HEAD~1")
        self.v["head"].set("HEAD")
        self._mode_changed()
        messagebox.showinfo("Demo project created",
                            f"The demo project was created in\n{root}\n\nIts last commit contains planted bugs. "
                            "The fields are filled in: click 'Run review'.")

    def _test_connection(self):
        url = self.v["base_url"].get().strip()
        self.lbl_conn.configure(text="Connecting...")

        def work():
            try:
                models = test_server(url)
                self.q.put(("conn", f"Connected. Models: {', '.join(models) or 'none pulled yet'}"))
            except Exception as e:
                self.q.put(("conn", f"Not reachable ({type(e).__name__}). Is Ollama / LM Studio running?"))
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ results tab
    def _build_results(self):
        t = self.tab_results
        t.columnconfigure(0, weight=1)
        t.rowconfigure(1, weight=1)
        top = ttk.Frame(t)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.lbl_summary = ttk.Label(top, text="No review yet. Run one from the Review tab.",
                                     font=("TkDefaultFont", 10, "bold"))
        self.lbl_summary.pack(side="left")
        ttk.Button(top, text="Open output folder", command=self._open_folder).pack(side="right")
        ttk.Button(top, text="Open HTML report", command=self._open_html).pack(side="right", padx=6)
        ttk.Checkbutton(top, text="Show filtered findings", variable=self.v_show_dropped,
                        command=self._fill_results).pack(side="right", padx=12)

        pw = ttk.PanedWindow(t, orient="vertical")
        pw.grid(row=1, column=0, sticky="nsew")
        tf = ttk.Frame(pw)
        cols = ("status", "category", "file", "line", "score", "message")
        self.tree = ttk.Treeview(tf, columns=cols, show="headings", height=12)
        for c, w, txt in (("status", 70, "Status"), ("category", 80, "Category"), ("file", 170, "File"),
                          ("line", 50, "Line"), ("score", 60, "Score"), ("message", 560, "Finding")):
            self.tree.heading(c, text=txt)
            self.tree.column(c, width=w, anchor="w", stretch=(c == "message"))
        ys = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        self.tree.tag_configure("dropped", foreground="#999")
        self.tree.bind("<<TreeviewSelect>>", self._show_detail)
        pw.add(tf, weight=3)
        self.detail = scrolledtext.ScrolledText(pw, height=12, wrap="word", font=("TkDefaultFont", 10))
        self.detail.tag_configure("h", font=("TkDefaultFont", 11, "bold"))
        self.detail.tag_configure("k", font=("TkDefaultFont", 10, "bold"))
        self.detail.tag_configure("code", font=("Courier", 10), background="#f2f1ec")
        self.detail.tag_configure("hit", font=("Courier", 10, "bold"), background="#fff1c2")
        self.detail.insert("1.0", "Click a finding above to see its code, explanation and score breakdown.")
        self.detail.configure(state="disabled")
        pw.add(self.detail, weight=2)

    def _fill_results(self):
        self.tree.delete(*self.tree.get_children())
        if not self.report:
            return
        order = {"security": 0, "logic": 1, "quality": 2, "review": 3}
        fs = sorted(enumerate(self.report["findings"]),
                    key=lambda x: (not x[1]["kept"], order.get(x[1]["category"], 9), x[1]["file"], x[1]["line"]))
        for i, f in fs:
            if not f["kept"] and not self.v_show_dropped.get():
                continue
            self.tree.insert("", "end", iid=str(i), tags=() if f["kept"] else ("dropped",),
                             values=("shown" if f["kept"] else "filtered", f["category"], f["file"], f["line"],
                                     f"{f['score']:.2f}", f["message"]))

    def _show_detail(self, _evt=None):
        sel = self.tree.selection()
        if not sel or not self.report:
            return
        f = self.report["findings"][int(sel[0])]
        d = self.detail
        d.configure(state="normal")
        d.delete("1.0", "end")
        d.insert("end", f"[{f['category'].upper()}] {f['message']}\n", "h")
        d.insert("end", f"{f['file']}, line {f['line']}   (from the {f['source']})\n\n")
        for n, text in f.get("snippet", []):
            d.insert("end", f"{n:>5}  {text}\n", "hit" if n == f["line"] else "code")
        d.insert("end", "\n")
        e = f.get("explanation") or {}
        for key, label in (("problem", "Problem"), ("evidence", "Evidence"),
                           ("why_it_matters", "Why it matters"), ("suggestion", "Suggested direction")):
            if e.get(key):
                d.insert("end", f"{label}: ", "k")
                d.insert("end", e[key] + "\n")
        d.insert("end", "\nScore: ", "k")
        d.insert("end", f"{f['score']:.2f} = {self._weights_text(f)}"
                        f"{'  -> shown' if f['kept'] else '  -> below threshold, filtered out'}\n")
        if f.get("supporting_signals"):
            d.insert("end", "Static analysis agreeing: ", "k")
            d.insert("end", "; ".join(f["supporting_signals"]) + "\n")
        d.configure(state="disabled")

    def _weights_text(self, f) -> str:
        c = (self.report or {}).get("config", {}).get("filter", {})
        return (f"{c.get('w_conf', 0.6)} x confidence {f['confidence']:.2f} + {c.get('w_static', 0.25)} x static "
                f"agreement {f['static_agreement']:.1f} + {c.get('w_ctx', 0.15)} x context support "
                f"{f['context_support']:.2f}")

    def _open_html(self):
        if self.out_dir:
            webbrowser.open("file://" + os.path.abspath(os.path.join(self.out_dir, "review_report.html")))

    def _open_folder(self):
        if self.out_dir:
            open_path(os.path.abspath(self.out_dir))

    # ------------------------------------------------------------------ log / help
    def _build_log(self):
        self.log = scrolledtext.ScrolledText(self.tab_log, wrap="word", font=("Courier", 10))
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")

    def _build_help(self):
        txt = scrolledtext.ScrolledText(self.tab_help, wrap="word", font=("TkDefaultFont", 10))
        txt.insert("1.0", HELP)
        txt.configure(state="disabled")
        txt.pack(fill="both", expand=True)

    def _log(self, msg: str):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ------------------------------------------------------------------ running
    def _validate(self) -> str | None:
        mode, repo = self.v["mode"].get(), self.v["repo"].get().strip()
        if mode in ("git", "patch") and not os.path.isdir(repo):
            return "Choose the project folder."
        if mode == "git" and not os.path.isdir(os.path.join(repo, ".git")):
            return "The project folder is not a Git repository (no .git folder). Use 'Patch file' mode or 'git init'."
        if mode == "patch" and not os.path.isfile(self.v["patch"].get().strip()):
            return "Choose the patch file."
        if mode == "github":
            try:
                ingestion.parse_pr_url(self.v["pr_url"].get().strip())
            except ValueError as e:
                return str(e)
            if self.v_post.get() and not self.v_token.get().strip():
                return "Posting comments to GitHub needs a token."
        if BACKENDS.get(self.v["backend"].get()) == "openai" and not self.v["model"].get().strip():
            return "Enter the model name (e.g. qwen2.5-coder:7b)."
        return None

    def _start_review(self):
        if self.running:
            return
        problem = self._validate()
        if problem:
            messagebox.showwarning("Check the inputs", problem)
            return
        for code, label in VARIANT_LABELS.items():
            if label == self.v_variant_label.get():
                self.v["variant"].set(code)
        self._save_settings()
        self.running = True
        self.btn_run.configure(state="disabled", text="Running...")
        self.pb["value"] = 0
        self.lbl_status.configure(text="Starting...")
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        params = {k: var.get().strip() for k, var in self.v.items()}
        params.update(threshold=self.v_threshold.get(), token=self.v_token.get().strip() or None,
                      post=self.v_post.get())
        threading.Thread(target=self._worker, args=(params,), daemon=True).start()

    def _worker(self, p: dict):
        log = lambda m: self.q.put(("log", m))          # noqa: E731
        try:
            meta = None
            if p["mode"] == "git":
                log(f"Reading the change {p['base']}...{p['head']} in {p['repo']}")
                cs = ingestion.from_git(p["repo"], p["base"], p["head"] or "HEAD")
            elif p["mode"] == "patch":
                log(f"Reading patch {p['patch']}")
                cs = ingestion.from_patch_file(p["patch"], p["repo"])
            else:
                log(f"Downloading {p['pr_url']} from GitHub")
                cs, meta = ingestion.from_github_pr(p["pr_url"], p["token"], p["repo"] or None)
                log(f"Pull request: {meta['title']}")
            if not cs.hunks:
                self.q.put(("error", "No reviewable Python or Java changes were found in that change."))
                return
            log(f"Change ingestion: {len(cs.hunks)} changed block(s) in {len(cs.files)} file(s)")
            fcfg = FilterConfig()
            if p["filter_config"]:
                with open(p["filter_config"], encoding="utf-8") as f:
                    fcfg = FilterConfig(**json.load(f))
                log(f"Using tuned filter settings from {p['filter_config']} (threshold {fcfg.threshold})")
            else:
                fcfg.threshold = round(p["threshold"], 2)
            cfg = PipelineConfig.for_variant(p["variant"], filter=fcfg)
            backend = None
            if p["variant"] != "static_only":
                kind = BACKENDS[p["backend"]]
                backend = make_backend(kind, p["model"] or None, None, p["base_url"] or None)
                log(f"Model: {backend.name}")
            report = run(cs, backend, cfg, log=log, progress=lambda x: self.q.put(("progress", x)))
            out_dir = os.path.join(p["out"], self._run_name(p))
            output.save(report, out_dir)
            log(f"Reports saved in {out_dir}")
            if p["post"] and meta:
                output.post_to_github(report, meta["repo"], meta["number"], p["token"], meta["head_sha"])
                log("Posted the advisory review to the pull request.")
            self.q.put(("done", (report, out_dir)))
        except Exception as e:
            log(traceback.format_exc())
            self.q.put(("error", str(e) or type(e).__name__))

    @staticmethod
    def _run_name(p: dict) -> str:
        import datetime
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"review-{stamp}-{p['variant']}"

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._log(payload)
                    self.lbl_status.configure(text=payload.strip().splitlines()[0][:110])
                elif kind == "progress":
                    self.pb["value"] = int(payload * 100)
                elif kind == "conn":
                    self.lbl_conn.configure(text=payload)
                elif kind == "done":
                    self.report, self.out_dir = payload
                    self._finish()
                    kept = sum(f["kept"] for f in self.report["findings"])
                    dropped = len(self.report["findings"]) - kept
                    self.lbl_summary.configure(
                        text=f"{kept} finding(s) shown, {dropped} filtered out  |  variant: {self.report['variant']}"
                             f"  |  {self.report['timings_sec'].get('total', 0):.1f}s")
                    self.lbl_status.configure(text=f"Done: {kept} finding(s). See the Results tab.")
                    self.pb["value"] = 100
                    self._fill_results()
                    self.nb.select(self.tab_results)
                elif kind == "error":
                    self._finish()
                    self.lbl_status.configure(text="Failed. See the Log tab.")
                    messagebox.showerror("Review failed", payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _finish(self):
        self.running = False
        self.btn_run.configure(state="normal", text="Run review")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
