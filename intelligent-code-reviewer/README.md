# ICR Reviewer — Intelligent Code Review and Error Detection System

Final-year project software by Gift Morris Abia (Department of Computer Science, University of Ibadan; supervisor Mr. S.O. Fawale).

A standalone desktop application (plus command-line tool) that reviews Python and Java pull requests through the pipeline of Figure 3.1: change ingestion, repository context (AST units + vector retrieval), static analysis, an open-weight code LLM that writes review comments and detects logic/security/quality faults, a false-positive filter, plain-language explanations, and advisory output (HTML report, optional GitHub comments).

**Read `README.txt`** for the complete step-by-step guide to installing, launching and operating the software. **Read `docs/STEP_BY_STEP.md`** for how each stage maps to the methodology, for the defence.

## Quick start from source

```bash
pip install -r requirements.txt
python -m pytest -q
python -m icr gui
```

## Build the executable

Windows: double-click `build_windows.bat`. macOS/Linux: `./build_unix.sh`. Or run the **Build executables** workflow on GitHub (Actions tab) to get Windows, macOS and Linux builds.
