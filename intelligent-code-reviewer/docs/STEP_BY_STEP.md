# Step-by-step guide: Intelligent Code Review and Error Detection System

This guide walks through the prototype in the same order as Chapter Three. For each step it tells you what the step does, which thesis section it implements, which file holds the code, how to show it working, and what to say when you explain it. Read it once from top to bottom, then run every command yourself so you can describe what you saw.

## 0. Map from thesis to code

| Thesis section | What it is | File |
|---|---|---|
| 3.3 Change ingestion | Read the diff, changed files and PR description | `icr/ingestion.py` |
| 3.4.1 Context builder | AST units, vector index, retrieval (RAG) | `icr/context_builder.py` |
| 3.4.2 Static analysis | Pylint, Semgrep, SpotBugs as evidence | `icr/static_analysis.py`, `rules/semgrep_rules.yml` |
| 3.4.3 Comment generator + error detector | Open-weight LLM with LoRA, shared context | `icr/reviewer.py`, `icr/prompts.py`, `icr/llm.py` |
| 3.4.4 False-positive filter | Confidence + static agreement + context support | `icr/fp_filter.py` |
| 3.4.5 Explanation generator | Problem, evidence, why it matters, suggestion | `icr/explainer.py` |
| 3.3 Output | Report + advisory GitHub comments | `icr/output.py`, `.github/workflows/ai-review.yml` |
| Figure 3.1 as a whole | Wires the stages together, variants | `icr/pipeline.py`, `icr/__main__.py` |
| 3.5 Data collection | CVEfixes, Defects4J/BugsInPy → labelled blocks | `training/make_bug_samples.py` |
| 3.6 Data preparation | Filter, de-duplicate, split by project/time | `training/prepare_data.py` |
| 3.4.3 LoRA training | Fine-tuning script and Colab notebook | `training/train_lora.py`, `training/colab_train.ipynb` |
| 3.4.4 Threshold tuning | Sweep weights/threshold on validation set | `training/tune_threshold.py` |
| 3.8.1, 3.8.3, 3.8.4, 3.8.5 | Accuracy, false positives, efficiency, baselines, ablations | `evaluation/run_eval.py`, `evaluation/metrics.py` |
| 3.8.2 Usefulness | Blind rating sheet, SUS, time saved | `evaluation/make_rating_sheet.py`, `evaluation/analyze_human_study.py` |

## 1. Setup

You need Python 3.10 or newer and Git.

```bash
cd intelligent-code-reviewer
python -m venv .venv
# Windows:  .venv\Scripts\activate        Linux/macOS:  source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q          # should print "11 passed"
```

Semgrep does not run natively on Windows. Either use WSL (Windows Subsystem for Linux), or run without it: the pipeline detects that Semgrep is missing and continues with Pylint only. For your defence demo, WSL or Google Colab gives the full result.

## 2. The five-minute demo (do this first)

```bash
python examples/make_demo_repo.py
python -m icr review --repo examples/demo_repo --base HEAD~1 --backend heuristic
```

The first command creates a small "shop" project with two commits. The second commit plays the role of a pull request and contains planted problems:

- **Logic bugs:** an off-by-one loop, a `None` from `get_price()` used in arithmetic, a mutable default argument, and division by `len()` of a possibly empty list.
- **Security problems:** SQL injection, `eval`, and a hard-coded API key.
- **Quality problems:** a bare `except` and `== None`.
- **Noise:** `print`, a magic number, a TODO and a missing docstring.

It also contains one completely correct change, `is_known()` in `utils.py`.

The terminal prints the five stages as they run. Open `review_output/review_report.md`. You should see 10 findings shown, each with an explanation and its score breakdown. Three low-value comments are listed under "Dropped by the false-positive filter", and nothing is reported on the correct `is_known()` function.

**What to say:** "The system receives the pull request, builds context from the whole repository, runs static analysers, asks the model for review comments and faults, filters weak findings and explains the rest. Nothing is merged or changed; the output is advisory."

**Be honest about the backend.** `--backend heuristic` is a stub made of pattern rules. It lets you demonstrate every other stage without a GPU. It is not the research model, and the report header says so. Your Chapter Four results must come from the `hf` backend with your trained adapter (Section 6 of this guide), or from the `openai` backend running an open-weight model.

Now show the ablations live, because they prove the design choices matter:

```bash
python -m icr review --repo examples/demo_repo --base HEAD~1 --backend heuristic --variant no_context --out out_nc
python -m icr review --repo examples/demo_repo --base HEAD~1 --backend heuristic --variant no_filter  --out out_nf
python -m icr review --repo examples/demo_repo --base HEAD~1 --variant static_only --out out_static
```

- **Without context**, the `get_price()` bug disappears, because the model can no longer see that `get_price` (defined in another file) returns `None`. This is exactly the problem in Section 2.3.1: "a comment about a function call may need to know how that function is defined three files away."
- **Without the filter**, all 13 findings are shown, including the noise.
- **The static-only baseline** catches the security problems and the mutable default, but misses the off-by-one loop, the `None` arithmetic and the division by an empty list. That supports the claim in Section 2.2.2 that rule-based tools work well for quality problems but much less well for logic bugs.

## 3. Walking through the pipeline, stage by stage

### Step 1: Change ingestion (`icr/ingestion.py`)

`from_git()` runs `git diff base...head`, and `parse_unified_diff()` turns the text into `Hunk` objects. A hunk is one "changed block", the unit you evaluate in Section 3.8.1. The parser tracks line numbers in the *new* file, which is what makes line-level error localisation possible. Files that are not Python or Java are skipped (the scope in Section 3.5). Hunks with more than 80 added lines are split (Section 3.6).

**Show it:** run `python -m pytest -q -k diff`. The test `test_diff_line_numbers` checks that added lines get the right numbers.

**Likely question:** "Why the three-dot diff?" Answer: `base...head` compares the PR head with the point where it branched from base. That is exactly what GitHub shows as the PR's changes, so later commits on main do not pollute the diff.

### Step 2: Context builder (`icr/context_builder.py`)

This is your RAG component (Lewis et al., 2020). It works in four parts:

1. **Parse into units.** Every Python and Java file in the repository is parsed with Tree-sitter into functions, classes and methods (`extract_units`). If Tree-sitter is missing, Python's built-in `ast` module is used. Units are meaningful pieces of code, not arbitrary text blocks, which is the point made in Section 3.4.1.
2. **Embed the units.** The units are embedded and stored in `VectorIndex`. By default the embedding is TF-IDF over split identifiers, so `getUserName` and `get_user_name` share tokens. This runs offline on any laptop. Pass `--embedding-model sentence-transformers/all-MiniLM-L6-v2` (or a code embedding model) to use dense neural embeddings instead. That comparison is a nice small experiment for Chapter Four.
3. **Retrieve context for each changed block.** Retrieval is done three ways:
   - The **enclosing** unit (the surrounding class or function, minus the changed lines, which are already in the prompt).
   - **Definitions** of every function the change calls, found by name anywhere in the repository. This is structural retrieval.
   - The **top-k similar** units from the vector index. This is semantic retrieval.
4. **Retrieve guidelines and respect a budget.** Project guidelines (CONTRIBUTING.md, .pylintrc, pyproject.toml, checkstyle.xml) are chunked and retrieved the same way. A character budget keeps the prompt within the model's context window.

**Show it:** open `review_output/review_report.json` and look at `"contexts"`. For the cart change you will see `get_price` from `shop/utils.py` retrieved with reason `definition`.

**Likely question:** "Why combine structural and semantic retrieval?" Answer: similarity search alone can miss the one definition that matters, because a function call and its definition may not look alike. Name-based lookup guarantees the callee is found; similarity search adds related code the reviewer might also check.

### Step 3: Static analysis module (`icr/static_analysis.py`)

The changed files are written to a temporary folder and analysed with:
- **Pylint** for Python bugs and quality.
- **Semgrep** for security patterns, using `rules/semgrep_rules.yml` so it works offline.
- **SpotBugs** for Java. SpotBugs needs compiled `.class` files, so you build the Java project first and pass `--spotbugs-classes target/classes`.

Every warning becomes a `Signal`. Signals are used twice: as hints inside the prompt (`STATIC ANALYSIS WARNINGS (hints, may be wrong)`), and as the static-agreement input of the filter. Some noisy Pylint checks, such as missing module docstrings and import errors, are disabled in `PYLINT_DISABLE`. Say this openly: Beller et al. (2016) found most projects keep default configurations, and part of your contribution is using the tools as evidence instead of as the final answer.

### Step 4: Review comment generator and error detector (`icr/reviewer.py`, `icr/prompts.py`)

`format_context_block()` builds one block of text containing:
- the file and language,
- the PR description,
- the changed lines with line numbers (`L18: for i in ...`),
- the removed lines,
- the retrieved context,
- the guidelines,
- the static warnings.

The **same block** goes to both tasks. `review_prompt()` asks for review comments and `detect_prompt()` asks for a faulty/clean label with line, category (logic, security, quality) and message. Both answer in JSON. This shared input is what Section 3.4.3 means by "both tasks share the same context input, which is what allows review and error detection to be combined in one system".

`reviewer.py` checks the model's answer:
- broken JSON is recovered by `extract_json`,
- line numbers that do not belong to the change are snapped to the nearest changed line or discarded,
- unknown categories become "quality".

**Model confidence.** With the `hf` backend, confidence is the average probability the model gave to the tokens it generated (`HFBackend.generate`). This comes from the model itself, rather than a number it writes about itself, which matters because LLMs are poorly calibrated when grading their own answers. One limitation to state in Chapter Five: the confidence is per response, so all findings in one answer share it.

### Step 5: False-positive filter (`icr/fp_filter.py`)

Each candidate gets a score:

```
score = 0.60 × model confidence + 0.25 × static agreement + 0.15 × context support
```

- **Static agreement** is 1 if an analyser flags the same line, 0.5 if it flags a neighbouring line, and 0 otherwise.
- **Context support** checks whether the identifiers the finding talks about (for example `get_price`) actually exist in the change or the retrieved context. A finding about a variable that does not exist is a typical hallucination and scores 0. A finding that names no checkable identifier gets a neutral 0.5.

Findings below the threshold (default 0.45) are marked `kept = false`. They are not deleted: they stay in the JSON report so the ablation can count them. If the detector and commenter flag the same line, only one finding is kept (`deduplicate`).

The weights and threshold above are defaults. The real values are chosen on the validation set by `training/tune_threshold.py` (Section 6, Step C), which you then report, as promised in Section 3.4.4.

**Show it:** in the demo report each finding shows `score 0.74 = confidence 0.70, static agreement 1, context support 0.50`. Point to one kept and one dropped finding and explain the arithmetic.

### Step 6: Explanation generator (`icr/explainer.py`)

For every kept finding the model is asked for four fields: the problem, the evidence, why it matters, and a suggested direction. The evidence list given to the model contains the agreeing static warnings and the names of retrieved context units, so the explanation is grounded in something checkable. The fix is never applied.

### Step 7: Output (`icr/output.py`)

`save()` writes `review_report.json` (for evaluation) and `review_report.md` (for people). `post_to_github()` posts one review with `event: "COMMENT"`. It never uses "APPROVE" or "REQUEST_CHANGES", so the system cannot block or merge anything. If GitHub rejects an inline comment (a line outside the diff), it falls back to a single summary comment. Every comment ends with a line saying it is advisory and can be wrong (Section 3.9).

## 4. Running on a real GitHub repository

Copy `icr/`, `rules/`, `requirements.txt` and `.github/workflows/ai-review.yml` into a test repository on GitHub, then open a pull request. The workflow checks out the code with full history, installs the tool, runs the review against the base branch and posts the results. The report is also uploaded as a workflow artifact.

The model has to run somewhere. A GitHub-hosted runner has no GPU, so you have three options:
- **`ICR_BACKEND=heuristic`**, which only demonstrates the workflow.
- **`ICR_BACKEND=openai`**, with a secret `ICR_LLM_URL` pointing to a machine you control that runs Ollama or vLLM. This is the most practical option.
- **A self-hosted runner with a GPU**, using `ICR_BACKEND=hf`.

Take screenshots of a PR with the posted comments for Chapter Four.

## 5. Running with a real open-weight model locally

The quickest way is Ollama, which runs open-weight models on a normal laptop:

```bash
ollama pull qwen2.5-coder:7b            # or :1.5b on a weak machine
python -m icr review --repo examples/demo_repo --base HEAD~1 --backend openai --model qwen2.5-coder:7b
```

After training (next section), use your adapter:

```bash
python -m icr review --repo examples/demo_repo --base HEAD~1 --backend hf \
   --model Qwen/Qwen2.5-Coder-1.5B-Instruct --adapter outputs/lora-reviewer \
   --filter-config outputs/filter_config.json
```

Section 3.4.3 says the model is chosen at implementation time based on hardware. `Qwen2.5-Coder-1.5B-Instruct` fits a free Colab T4 with 4-bit loading. A 7B model gives better results if you have a 24 GB GPU. Whatever you choose, state it in Chapter Four together with the trainable-parameter count that `train_lora.py` prints.

## 6. Training and tuning (Sections 3.5, 3.6, 3.4.3, 3.4.4)

First do a dry run on the toy data, so you know every script works before you spend GPU time:

```bash
python examples/make_toy_dataset.py
python training/prepare_data.py --codereviewer examples/toy_data/reviews.jsonl --bugs examples/toy_data/bugs.jsonl --out data/toy --val-frac 0.3 --test-frac 0.3
python training/tune_threshold.py --val data/toy/val_bugs.jsonl --backend heuristic --out outputs/toy
python evaluation/run_eval.py --test examples/toy_data/bugs.jsonl --backend heuristic --out results/toy
```

Then follow the same steps with the real data, ideally in `training/colab_train.ipynb`.

**Step A: Collect the data (`training/make_bug_samples.py`).** Every bug-fix pair is turned into two labelled changed blocks:
- The diff from the fixed version to the buggy version is a change that *introduces* the fault. It is labelled faulty, and its added lines are the faulty lines.
- The diff from buggy to fixed is the fix itself. It is labelled clean.

This is how you get line-level labels and clean examples from the same data. Sources:
- **CVEfixes** (security, Python and Java): `cvefixes --db CVEfixes.db`.
- **Defects4J** (Java logic bugs): check out the buggy and fixed versions with the `defects4j` tool, then use `pair`.
- **BugsInPy** (Python logic bugs): same idea.
- **CodeReviewer** (review comments): use its `msg-*.jsonl` files directly.

The CVEfixes query follows the published schema. Check your copy with `.schema file_change` in sqlite3 before running it.

**Step B: Prepare the data (`training/prepare_data.py`).** Explain these points in order:
1. Meaningless comments ("LGTM", "ok", "+1", and anything under three words) are removed.
2. Exact duplicates are removed by hashing the normalised tokens, and near-duplicates are removed with MinHash at 0.9 Jaccard similarity. This is your response to Ding et al. (2024).
3. The split is by project (or by time with `--split-by time`), never random, so no project appears in both training and test. Pull requests reserved for the final human evaluation are listed in a file and passed with `--exclude`.
4. Training examples are built with the *same* prompt functions as the live system. The model is trained on exactly the input format it will see in use.
5. The CVE description is used as the target message but is never put into the prompt. Putting it there would leak the answer.

`data_stats.json` records how many samples each step removed. Put that table in Chapter Four.

**Step B (continued): Train with LoRA (`training/train_lora.py`).** One adapter learns both tasks, because the review and detection examples are mixed and distinguished by their TASK line. Only the answer tokens count in the loss (prompt tokens get label -100). The defaults are r=16, alpha=32 and dropout 0.05, on the attention projections, with 4-bit loading. The seed, library versions, arguments and full loss history are saved to `run_info.json` (Section 3.7, reproducibility).

**Step C: Tune the filter (`training/tune_threshold.py`).** The pipeline runs once on the validation set with the filter switched off. Each candidate is marked correct if it lands on a labelled faulty line (±1). Weight combinations and thresholds from 0 to 1 are then tried offline, without re-running the model. The best F1 setting goes into `filter_config.json`, and the whole sweep goes into `threshold_sweep.csv`. Plot precision and recall against threshold from that CSV. That plot is the "visible trade-off" Section 3.4.4 promises.

**Step D: Evaluate (`evaluation/run_eval.py`).** This runs the full system, the four ablations and baseline 1 (static only) on the test set. Run baseline 2 (general LLM, diff only) separately with the base model and no adapter. The results merge into one table in `results/metrics.md`. The table reports:
- block-level and line-level precision, recall and F1;
- block false-positive rate, FP / (FP + TN): how often clean code is flagged;
- false-alarm share: the proportion of shown findings that miss every labelled line;
- seconds per block.

`efficiency.csv` lists time against change size for the scaling plot (Section 3.8.4). BLEU for comment generation goes to `comment_bleu.json`. As Section 3.8.1 says, BLEU is reported only for comparison with earlier work.

The "without explanation" ablation does not change accuracy, because explanations come after detection. Its effect shows up in run time and in the human ratings, so evaluate it there.

## 7. Human evaluation (Section 3.8.2)

1. **Choose the pull requests.** Pick 8–15 recent PRs from public repositories that were excluded from training, and run the full system and both automated baselines on each, saving into `study/<pr>/<system>/`.
2. **Get the manual baseline.** Have one human reviewer write their comments for each PR in `study/<pr>/manual.csv` (columns: file, line, comment). This is baseline 3.
3. **Build the blind sheet.** Run `python evaluation/make_rating_sheet.py --study study --out study_out --hide-explanations`. Raters receive `rating_sheet.csv`, in which items from all systems are shuffled under random ids. You keep `rating_key.csv` private. Explanations are hidden in this first pass because only the full system has them, which would reveal the source. Rate the explanations in a second, separate pass.
4. **Collect the remaining data.** Each participant completes the 10-item SUS, saved as `participant,q1..q10`. Record review times in a CSV with columns `participant,pr,condition,minutes`, where `condition` is `unaided` or `assisted`.
5. **Analyse.** Run `python evaluation/analyze_human_study.py --ratings r1.csv r2.csv --key study_out/rating_key.csv --sus sus.csv --timing timing.csv`. It reports:
   - mean and median scores per system;
   - Mann-Whitney U tests of the full system against each other system (Likert data is ordinal, so a non-parametric test is appropriate);
   - the human-judged false-positive rate, which is the definitive one in Section 3.8.3;
   - rater agreement;
   - the SUS score (68 is the commonly cited average);
   - the percentage of review time saved.

Get informed consent and keep responses anonymous (Section 3.9).

## 8. What is real, and what you must still do

**Real and tested:**
- ingestion, the context builder (Tree-sitter, vector index, structural and semantic retrieval), static analysis, prompts, the filter, the explainer, the output, GitHub posting and the workflow;
- the data conversion, preparation, threshold tuning and evaluation scripts, which were all run end to end on the toy data;
- 11 unit tests.

**Written but not run here, because it needs a GPU and model downloads:** `train_lora.py` and the `hf` backend. They use standard transformers and PEFT calls. Run the Colab notebook early, so that any library version issue shows up with time to fix it.

**Not part of the research:** the heuristic backend, and every number it produces, including the toy-data metrics.

## 9. Inconsistencies in Chapters Two and Three worth fixing before submission

- **Big-Vul is mostly C/C++ code**, but Section 3.5 limits the study to Python and Java. Either drop Big-Vul, or say you use it only to train general vulnerability patterns. CVEfixes (filtered to Python and Java), Defects4J (Java) and BugsInPy (Python) match your scope.
- **The Codex citation is wrong.** Section 2.2.3 cites Codex as "Chen (2024)", but the Codex paper is Chen et al. (2021).
- **Typos and leftovers.** "Which are" is stray text before the stage list in Section 3.3. "trailed" in Section 2.3.3 should be "trialled". "most project keeps" in Section 2.2.2 should be "most projects keep". "CodeT5(Wang" needs a space.
- **The code uses SpotBugs and Semgrep exactly as Figure 3.1 names them.** If you end up not running SpotBugs (it needs compiled Java), say so in Chapter Four rather than leaving it in the figure unexplained.

## 10. Suggested shape for Chapter Four

Use this order:
1. Implementation environment, with versions from `run_info.json`.
2. Screenshots of each stage: terminal output, the context JSON, the report, the GitHub PR comments.
3. The data statistics table from `data_stats.json`.
4. Training curves from `log_history`.
5. The threshold sweep plot.
6. The main results table from `metrics.md`, with baselines and ablations.
7. Efficiency against PR size.
8. The human evaluation results.

Each design choice in Chapter Three then has a row in the ablation table that shows whether it was worth its cost.
