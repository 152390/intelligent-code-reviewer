"""Command-line interface (also the 'ICR-Reviewer-cli' executable).

  ICR-Reviewer-cli check                          check that Git, Pylint, Semgrep, the LLM server are available
  ICR-Reviewer-cli demo --path demo_repo          create the demo project
  ICR-Reviewer-cli review --repo demo_repo --base HEAD~1
  ICR-Reviewer-cli review --repo myproject --patch change.patch
  ICR-Reviewer-cli review --pr-url https://github.com/owner/repo/pull/12 --token ghp_...
  ICR-Reviewer-cli gui                            open the desktop window
"""
from __future__ import annotations
import argparse
import json
import os
import random
import shutil
import sys
import webbrowser
from . import __version__, ingestion, output
from .pipeline import PipelineConfig, VARIANTS, run
from .fp_filter import FilterConfig
from .llm import make_backend, test_server


def build_parser():
    p = argparse.ArgumentParser(prog="ICR-Reviewer-cli",
                                description="Intelligent code review and error detection system")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("review", help="review a change")
    src = r.add_argument_group("what to review (choose one)")
    src.add_argument("--repo", help="local project folder (a Git repository for --base mode)")
    src.add_argument("--base", help="base commit/branch, e.g. HEAD~1 or main")
    src.add_argument("--head", default="HEAD")
    src.add_argument("--patch", help="a .diff/.patch file; --repo must hold the code WITH the change applied")
    src.add_argument("--pr-url", help="a GitHub pull request URL")
    r.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"),
                   help="GitHub token (private repos, higher rate limit, posting comments)")
    r.add_argument("--description", default="", help="PR description text")
    r.add_argument("--variant", default="full", choices=list(VARIANTS) + ["static_only"])
    r.add_argument("--backend", default="heuristic", choices=["heuristic", "openai", "hf"])
    r.add_argument("--model", help="model name, e.g. qwen2.5-coder:7b")
    r.add_argument("--base-url", help="LLM server URL (default http://localhost:11434/v1 = Ollama)")
    r.add_argument("--adapter", help="LoRA adapter folder (hf backend, source install only)")
    r.add_argument("--load-4bit", action="store_true")
    r.add_argument("--filter-config", help="filter_config.json from threshold tuning")
    r.add_argument("--threshold", type=float, help="override the filter threshold (0-1)")
    r.add_argument("--out", default="review_output", help="folder for the reports")
    r.add_argument("--open", action="store_true", help="open the HTML report when finished")
    r.add_argument("--post-github", action="store_true", help="post the findings to the PR as comments")
    r.add_argument("--seed", type=int, default=42)

    d = sub.add_parser("demo", help="create the demo project (needs Git)")
    d.add_argument("--path", default="demo_repo")

    c = sub.add_parser("check", help="check the environment")
    c.add_argument("--base-url", default="http://localhost:11434/v1")

    sub.add_parser("gui", help="open the desktop application")
    return p


def cmd_check(args) -> int:
    print(f"ICR Reviewer {__version__}")
    print(f"  Git ............ {'found: ' + shutil.which('git') if shutil.which('git') else 'NOT FOUND (needed for Git and demo modes)'}")
    try:
        import pylint
        print(f"  Pylint ......... bundled ({pylint.__version__})")
    except ImportError:
        print("  Pylint ......... NOT FOUND")
    print(f"  Semgrep ........ {'found' if shutil.which('semgrep') else 'not found -> built-in security rules will be used'}")
    try:
        import tree_sitter  # noqa: F401
        print("  Tree-sitter .... available")
    except ImportError:
        print("  Tree-sitter .... not available -> Python ast fallback")
    try:
        models = test_server(args.base_url)
        print(f"  LLM server ..... reachable at {args.base_url}; models: {', '.join(models) or '(none pulled)'}")
    except Exception as e:
        print(f"  LLM server ..... not reachable at {args.base_url} ({type(e).__name__}); "
              f"the offline demo backend still works")
    return 0


def cmd_review(args) -> int:
    random.seed(args.seed)
    meta = None
    if args.pr_url:
        print(f"Downloading {args.pr_url} ...")
        cs, meta = ingestion.from_github_pr(args.pr_url, args.token, args.repo)
        if args.description:
            cs.description = args.description
    elif args.patch:
        if not args.repo:
            print("--patch needs --repo (the folder with the change applied)")
            return 2
        cs = ingestion.from_patch_file(args.patch, args.repo, args.description)
    elif args.repo and args.base:
        cs = ingestion.from_git(args.repo, args.base, args.head,
                                args.description or ingestion.pr_description_from_github_event())
    else:
        print("Choose what to review: --repo + --base, --repo + --patch, or --pr-url")
        return 2
    if not cs.hunks:
        print("No reviewable Python/Java changes found.")
        return 0

    fcfg = FilterConfig()
    if args.filter_config:
        with open(args.filter_config, encoding="utf-8") as f:
            fcfg = FilterConfig(**json.load(f))
    if args.threshold is not None:
        fcfg.threshold = args.threshold
    cfg = PipelineConfig.for_variant(args.variant, filter=fcfg)
    backend = None if args.variant == "static_only" else make_backend(
        args.backend, args.model, args.adapter, args.base_url, args.load_4bit)

    print(f"Reviewing {len(cs.hunks)} changed block(s) in {len(cs.files)} file(s), variant '{args.variant}'")
    report = run(cs, backend, cfg, verbose=True)
    output.save(report, args.out)
    kept = sum(f["kept"] for f in report["findings"])
    html_path = os.path.abspath(os.path.join(args.out, "review_report.html"))
    print(f"\n{kept} finding(s) shown, {len(report['findings']) - kept} filtered out.")
    print(f"Reports: {html_path}\n         {os.path.abspath(os.path.join(args.out, 'review_report.md'))}")
    if args.open:
        webbrowser.open("file://" + html_path)

    if args.post_github:
        token = args.token
        if meta:
            repo, pr, sha = meta["repo"], meta["number"], meta["head_sha"]
        else:
            repo, pr, sha = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("PR_NUMBER"), os.environ.get("HEAD_SHA")
        if not (repo and pr and token):
            print("Posting needs a PR (--pr-url, or GITHUB_REPOSITORY and PR_NUMBER) and a token.", file=sys.stderr)
            return 1
        output.post_to_github(report, repo, int(pr), token, sha)
        print("Posted the advisory review to GitHub.")
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "review":
            return cmd_review(args)
        if args.cmd == "demo":
            from .demo import create_demo_repo
            root = create_demo_repo(args.path)
            print(f"Demo project created at {root}\nNext: ICR-Reviewer-cli review --repo \"{root}\" --base HEAD~1 --open")
            return 0
        if args.cmd == "check":
            return cmd_check(args)
        if args.cmd == "gui":
            from .gui import main as gui_main
            gui_main()
            return 0
    except Exception as e:      # friendly one-line errors instead of tracebacks
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0
