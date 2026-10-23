"""Stage 6 - Output (Section 3.3).

Writes a JSON report (for evaluation) and a Markdown report (for people), and can
post the kept findings to the pull request as review comments.

Posting uses the GitHub review event "COMMENT" - never "APPROVE" or
"REQUEST_CHANGES" - so nothing is merged, approved or changed automatically.
"""
from __future__ import annotations
import html
import json
import os

DISCLAIMER = "_Advisory comment from an automated reviewer. It can be wrong; a human decides._"


def finding_markdown(f: dict) -> str:
    head = f"**[{f['category']}] {f['message']}**"
    e = f.get("explanation") or {}
    rows = [f"- **Problem:** {e['problem']}" if e.get("problem") else "",
            f"- **Evidence:** {e['evidence']}" if e.get("evidence") else "",
            f"- **Why it matters:** {e['why_it_matters']}" if e.get("why_it_matters") else "",
            f"- **Suggested direction:** {e['suggestion']}" if e.get("suggestion") else ""]
    meta = (f"<sub>score {f['score']:.2f} = confidence {f['confidence']:.2f}, static agreement "
            f"{f['static_agreement']:.0f}, context support {f['context_support']:.2f}</sub>")
    return "\n".join([head, *[r for r in rows if r], meta, DISCLAIMER])


def markdown_report(report: dict) -> str:
    kept = [f for f in report["findings"] if f["kept"]]
    dropped = [f for f in report["findings"] if not f["kept"]]
    lines = [f"# Automated review report ({report['variant']})", "",
             f"Model: `{report['model']}`  ", f"Added lines reviewed: {report['pr_size_added_lines']}  ",
             f"Findings shown: **{len(kept)}** (filtered out as likely false positives: {len(dropped)})  ",
             f"Time: {report['timings_sec'].get('total', 0):.2f}s", "", "## Findings", ""]
    for f in sorted(kept, key=lambda x: (x["file"], x["line"])):
        lines += [f"### `{f['file']}` line {f['line']}", finding_markdown(f), ""]
    if dropped:
        lines += ["## Dropped by the false-positive filter", "",
                  "| File | Line | Source | Message | Score |", "|---|---|---|---|---|"]
        for f in dropped:
            lines.append(f"| {f['file']} | {f['line']} | {f['source']} | {f['message']} | {f['score']:.2f} |")
    lines += ["", "## Time per stage (seconds)", "", "| Stage | Seconds |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in report["timings_sec"].items()]
    return "\n".join(lines) + "\n"


def _e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def html_report(report: dict) -> str:
    """A self-contained HTML page (no internet needed) that opens in any browser."""
    kept = sorted([f for f in report["findings"] if f["kept"]], key=lambda x: (x["file"], x["line"]))
    dropped = [f for f in report["findings"] if not f["kept"]]
    cards = []
    for f in kept:
        e = f.get("explanation") or {}
        code = "".join(f'<div class="ln{" hit" if n == f["line"] else ""}"><span>{n}</span>{_e(t)}</div>'
                       for n, t in f.get("snippet", []))
        rows = "".join(f"<dt>{label}</dt><dd>{_e(e[k])}</dd>" for k, label in
                       (("problem", "Problem"), ("evidence", "Evidence"), ("why_it_matters", "Why it matters"),
                        ("suggestion", "Suggested direction")) if e.get(k))
        sig = "".join(f"<li>{_e(s)}</li>" for s in f.get("supporting_signals", []))
        cards.append(f"""<article class="card {f['category']}">
<header><span class="tag">{_e(f['category'])}</span><code>{_e(f['file'])}:{f['line']}</code>
<span class="score" title="confidence {f['confidence']:.2f}, static {f['static_agreement']:.1f}, context {f['context_support']:.2f}">score {f['score']:.2f}</span></header>
<h3>{_e(f['message'])}</h3><pre class="code">{code}</pre><dl>{rows}</dl>
{f'<details><summary>Static analysis evidence</summary><ul>{sig}</ul></details>' if sig else ''}
</article>""")
    drop_rows = "".join(f"<tr><td>{_e(f['file'])}</td><td>{f['line']}</td><td>{_e(f['source'])}</td>"
                        f"<td>{_e(f['message'])}</td><td>{f['score']:.2f}</td></tr>" for f in dropped)
    time_rows = "".join(f"<tr><td>{_e(k)}</td><td>{v}</td></tr>" for k, v in report["timings_sec"].items())
    counts = {c: sum(1 for f in kept if f["category"] == c) for c in ("logic", "security", "quality", "review")}
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Code review report</title>
<style>
:root{{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#6b6b66;--card:#fff;--line:#e2e1dc;--code:#f1f0ec;--hit:#fff1c2;
--logic:#b45309;--security:#b91c1c;--quality:#1d4ed8;--review:#4d7c0f}}
@media (prefers-color-scheme: dark){{:root{{--bg:#151514;--fg:#ecebe6;--muted:#a3a29c;--card:#1f1f1d;--line:#34332f;
--code:#262624;--hit:#4a3d12;--logic:#f59e0b;--security:#f87171;--quality:#60a5fa;--review:#a3e635}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,Segoe UI,Arial,sans-serif}}
main{{max-width:980px;margin:0 auto;padding:28px 18px}} h1{{margin:0 0 4px;font-size:24px}}
.meta{{color:var(--muted);margin-bottom:18px}} .stats{{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0 24px}}
.stat{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px;min-width:110px}}
.stat b{{display:block;font-size:22px}} .card{{background:var(--card);border:1px solid var(--line);
border-left:5px solid var(--c);border-radius:8px;padding:14px 16px;margin:0 0 14px}}
.logic{{--c:var(--logic)}}.security{{--c:var(--security)}}.quality{{--c:var(--quality)}}.review{{--c:var(--review)}}
.card header{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}} .tag{{background:var(--c);color:#fff;
border-radius:4px;padding:1px 8px;font-size:12px;text-transform:uppercase;font-weight:600}}
.score{{margin-left:auto;color:var(--muted);font-size:13px}} h3{{margin:8px 0;font-size:16px}}
.code{{background:var(--code);border-radius:6px;padding:8px 0;overflow-x:auto;font:13px/1.45 Consolas,monospace;margin:8px 0}}
.ln{{padding:0 10px;white-space:pre}} .ln span{{display:inline-block;width:36px;color:var(--muted)}} .hit{{background:var(--hit)}}
dl{{display:grid;grid-template-columns:150px 1fr;gap:4px 12px;margin:8px 0}} dt{{color:var(--muted)}} dd{{margin:0}}
table{{border-collapse:collapse;width:100%;background:var(--card)}} td,th{{border:1px solid var(--line);padding:6px 8px;text-align:left;font-size:14px}}
.wrap{{overflow-x:auto}} .note{{color:var(--muted);font-size:13px;margin-top:28px}}
@media (max-width:600px){{dl{{grid-template-columns:1fr}}}}
</style></head><body><main>
<h1>Automated code review report</h1>
<div class="meta">Variant: <b>{_e(report['variant'])}</b> &middot; Model: {_e(report['model'])} &middot;
{report['pr_size_added_lines']} added lines in {len(report['blocks'])} changed block(s)</div>
<div class="stats"><div class="stat"><b>{len(kept)}</b>findings shown</div>
<div class="stat"><b>{len(dropped)}</b>filtered out</div>
<div class="stat"><b>{counts['logic']}</b>logic</div><div class="stat"><b>{counts['security']}</b>security</div>
<div class="stat"><b>{counts['quality']}</b>quality</div><div class="stat"><b>{counts['review']}</b>review comments</div>
<div class="stat"><b>{report['timings_sec'].get('total', 0):.1f}s</b>total time</div></div>
<h2>Findings</h2>{''.join(cards) or '<p>No findings. The change looks clean to the reviewer.</p>'}
<h2>Dropped by the false-positive filter</h2>
{f'<div class="wrap"><table><tr><th>File</th><th>Line</th><th>Source</th><th>Message</th><th>Score</th></tr>{drop_rows}</table></div>' if dropped else '<p>None.</p>'}
<h2>Time per stage (seconds)</h2><div class="wrap"><table><tr><th>Stage</th><th>Seconds</th></tr>{time_rows}</table></div>
<p class="note">Advisory output from an automated reviewer. It can be wrong; a human decides.
Nothing was merged, approved or changed.</p></main></body></html>"""


def save(report: dict, out_dir: str) -> tuple[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    jp, mp = os.path.join(out_dir, "review_report.json"), os.path.join(out_dir, "review_report.md")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    with open(mp, "w", encoding="utf-8") as f:
        f.write(markdown_report(report))
    with open(os.path.join(out_dir, "review_report.html"), "w", encoding="utf-8") as f:
        f.write(html_report(report))
    return jp, mp


def post_to_github(report: dict, repo: str, pr_number: int, token: str, commit_sha: str | None = None):
    """Post kept findings as inline comments in one review with event=COMMENT."""
    import requests
    api = f"https://api.github.com/repos/{repo}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    kept = [f for f in report["findings"] if f["kept"]]
    body = (f"Automated review: {len(kept)} finding(s); "
            f"{len(report['findings']) - len(kept)} likely false positive(s) filtered out.\n\n{DISCLAIMER}")
    payload = {"event": "COMMENT", "body": body,
               "comments": [{"path": f["file"], "line": f["line"], "side": "RIGHT",
                             "body": finding_markdown(f)} for f in kept]}
    if commit_sha:
        payload["commit_id"] = commit_sha
    r = requests.post(f"{api}/pulls/{pr_number}/reviews", headers=headers, json=payload, timeout=60)
    if r.status_code == 422:      # a line was not part of the diff: fall back to one summary comment
        r = requests.post(f"{api}/issues/{pr_number}/comments", headers=headers,
                          json={"body": markdown_report(report)}, timeout=60)
    r.raise_for_status()
    return r.json()
