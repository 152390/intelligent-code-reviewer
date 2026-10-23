===============================================================================
  ICR REVIEWER  -  Intelligent Code Review and Error Detection System
  Version 0.1.0
===============================================================================

  Final-year project software
  Author:      Gift Morris Abia (Matric No. E050899)
  Department:  Computer Science, University of Ibadan
  Supervisor:  Mr. S.O. Fawale

  This file explains, step by step, how to install, launch and operate the
  software. Read Sections 1 to 5 before first use. The remaining sections are
  reference material: come back to them when you need them.


-------------------------------------------------------------------------------
CONTENTS
-------------------------------------------------------------------------------
   1. What the software does
   2. What is in the download
   3. System requirements
   4. Installation
        4.1 Windows
        4.2 macOS
        4.3 Linux
        4.4 Installing Git (all systems)
        4.5 Building the executable yourself
   5. First launch: the five-minute demo
   6. The Review tab, field by field
   7. The Results tab, the Log tab and the report files
   8. Using a real AI model (Ollama, LM Studio, your trained model)
   9. Reviewing a GitHub pull request (and posting comments)
  10. Reviewing your own project or a patch file
  11. Running the evaluation variants (ablations and baselines)
  12. The command-line tool (ICR-Reviewer-cli)
  13. Troubleshooting
  14. Where settings and reports are stored; uninstalling
  15. Privacy and safety
  16. Running from source code, training and evaluation
  17. Quick reference card


===============================================================================
1. WHAT THE SOFTWARE DOES
===============================================================================

ICR Reviewer reads a code change (a "pull request") in Python or Java and
produces review comments and error reports, the way a careful human reviewer
would. It works in six stages, as in Figure 3.1 of the project report:

  Stage 1  Change ingestion      Reads the changed lines, the changed files and
                                 the pull request description.
  Stage 2  Context builder       Splits the whole project into functions and
                                 classes, indexes them, and finds the code
                                 related to the change (for example, the
                                 definition of a function the change calls,
                                 even if it is in another file).
           Static analysis       Runs rule-based checkers (Pylint, plus security
                                 rules) and keeps their warnings as evidence.
  Stage 3  Comment generator     The model writes review comments and detects
           and error detector    logic bugs, security vulnerabilities and code
                                 quality problems, pointing at exact lines.
  Stage 4  False-positive filter Each finding gets a score from three parts:
                                 model confidence, agreement with the static
                                 checkers, and whether the code it talks about
                                 really exists. Weak findings are hidden.
  Stage 5  Explanation generator Each remaining finding gets a plain-language
                                 explanation: the problem, the evidence, why it
                                 matters, and a suggested direction for a fix.
  Stage 6  Output                A report you can open in any web browser, and
                                 (optionally) comments posted on GitHub.

IMPORTANT: The software is ADVISORY. It never changes, merges or approves your
code. A human always decides. It can be wrong.


===============================================================================
2. WHAT IS IN THE DOWNLOAD
===============================================================================

A) The ready-to-run program (folder "ICR-Reviewer"):

   ICR-Reviewer        (ICR-Reviewer.exe on Windows)
                       The desktop application. Double-click to start.
   ICR-Reviewer-cli    (ICR-Reviewer-cli.exe on Windows)
                       The command-line version, for use in a terminal.
   _internal\          Libraries the program needs. DO NOT move, rename or
                       delete anything in this folder, and do not move the
                       two programs out of the "ICR-Reviewer" folder.
   README.txt          This file.

B) The source code (folder "intelligent-code-reviewer"), which contains:

   icr\                The system itself (one file per pipeline stage).
   rules\              Security rules used by the static analysis stage.
   training\           Data preparation, LoRA fine-tuning, threshold tuning,
                       export of the trained model for Ollama, Colab notebook.
   evaluation\         Accuracy / false-positive / efficiency evaluation and
                       the human-study tools.
   tests\              Automated tests.
   docs\STEP_BY_STEP.md  Explanation of every stage for the project defence.
   build.py, build_windows.bat, build_unix.sh
                       Scripts that build the executable.
   .github\workflows\  GitHub Actions: build the executables for Windows,
                       macOS and Linux; review pull requests automatically.


===============================================================================
3. SYSTEM REQUIREMENTS
===============================================================================

  Operating system  Windows 10 or 11 (64-bit), macOS 12 or newer,
                    or a 64-bit Linux desktop (e.g. Ubuntu 22.04 or newer).
  Memory (RAM)      4 GB is enough for the demo model.
                    8 GB or more if you run a real AI model on the same
                    computer (16 GB recommended for a 7-billion-parameter
                    model).
  Disk space        About 300 MB for the program.
                    Plus 1 to 5 GB for a real AI model, if you use one.
  Screen            At least 1024 x 700 pixels.
  Git               Needed for the "Git repository" mode and for the demo
                    project (see 4.4). Not needed for the "Patch file" and
                    "GitHub pull request" modes.
  Internet          Not needed, except for the "GitHub pull request" mode
                    and for downloading an AI model the first time.
  Python            NOT needed to run the executable.


===============================================================================
4. INSTALLATION
===============================================================================

The program is "portable": there is no installer. You unzip a folder and run
the program inside it.

-------------------------------------------------------------------------------
4.1 WINDOWS
-------------------------------------------------------------------------------

Step 1. Get the Windows version, in ONE of these two ways.

   Way A (easiest) - let GitHub build it for you:
     a) Create a free account at https://github.com and create a new
        repository (it can be private).
     b) Upload the contents of the "intelligent-code-reviewer" folder to it
        (on the repository page: "Add file" -> "Upload files", or use Git).
        Make sure the hidden folder ".github" is included. If you upload
        with the website, drag the folder in from File Explorer with
        "Hidden items" switched on (View -> Show -> Hidden items).
     c) Open the "Actions" tab of the repository. If asked, click
        "I understand my workflows, go ahead and enable them".
     d) Click "Build executables" on the left, then "Run workflow", then the
        green "Run workflow" button.
     e) Wait about 10 to 15 minutes until the run shows a green tick.
     f) Click the run. At the bottom, under "Artifacts", download
        "ICR-Reviewer-Windows". It is a zip file.

   Way B - build it on your own Windows computer:
     a) Install Python 3.12 from https://www.python.org/downloads/windows/
        On the first installer screen tick "Add python.exe to PATH".
        Keep the default optional features (they include "tcl/tk", which the
        window needs).
     b) Open the "intelligent-code-reviewer" folder and double-click
        "build_windows.bat". A black window shows the progress. It takes
        5 to 10 minutes. When it says SUCCESS, the program is in
        intelligent-code-reviewer\dist\ICR-Reviewer

Step 2. Unzip (Way A only). Right-click the downloaded zip ->
        "Extract All..." -> choose a simple location such as
        C:\Programs\ICR-Reviewer  (avoid folders synced by OneDrive if you
        can; syncing many small files slows the program down).

Step 3. Start the program: open the folder and double-click
        "ICR-Reviewer.exe".

Step 4. The first time, Windows may show a blue box "Windows protected your
        PC". This is normal for programs that are not digitally signed
        with a paid certificate. Click "More info", then "Run anyway".
        If your antivirus quarantines the file, add the ICR-Reviewer folder
        to its exclusions (this happens to many PyInstaller programs; the
        source code is included so anyone can check what it does).

Step 5. Optional: right-click ICR-Reviewer.exe -> "Send to" ->
        "Desktop (create shortcut)".

Step 6. Install Git if you do not have it (Section 4.4).

-------------------------------------------------------------------------------
4.2 macOS
-------------------------------------------------------------------------------

Step 1. Get the macOS version with Way A above (download the artifact
        "ICR-Reviewer-macOS"), or build it yourself:
        open Terminal in the "intelligent-code-reviewer" folder and run
            ./build_unix.sh
        (Python 3.12 from https://www.python.org is required for building.)

Step 2. Unzip it, for example into your Documents folder.

Step 3. macOS blocks unsigned programs downloaded from the internet. Open
        Terminal and run (adjust the path to where you unzipped it):
            xattr -dr com.apple.quarantine ~/Documents/ICR-Reviewer
            chmod +x ~/Documents/ICR-Reviewer/ICR-Reviewer*

Step 4. Start the program by double-clicking "ICR-Reviewer" in Finder, or in
        Terminal:
            ~/Documents/ICR-Reviewer/ICR-Reviewer
        If macOS still refuses: System Settings -> Privacy & Security ->
        scroll down -> "Open Anyway".

-------------------------------------------------------------------------------
4.3 LINUX
-------------------------------------------------------------------------------

Step 1. Unzip "ICR-Reviewer-Linux-x64.zip" (included in this delivery, built
        and tested on Ubuntu 24.04), for example:
            unzip ICR-Reviewer-Linux-x64.zip -d ~/apps

Step 2. Make the programs executable (unzip usually keeps this, but to be
        sure):
            chmod +x ~/apps/ICR-Reviewer/ICR-Reviewer ~/apps/ICR-Reviewer/ICR-Reviewer-cli

Step 3. Start it:
            ~/apps/ICR-Reviewer/ICR-Reviewer
        A graphical desktop session is needed for the window. On a server
        without a screen, use ICR-Reviewer-cli instead (Section 12).

        The Linux build was made with glibc 2.39 (Ubuntu 24.04). On an older
        distribution, if you see "GLIBC_2.xx not found", build it yourself
        with ./build_unix.sh on that machine.

-------------------------------------------------------------------------------
4.4 INSTALLING GIT (ALL SYSTEMS)
-------------------------------------------------------------------------------

Git lets the program compare two versions of a project. Check whether you
already have it: open a terminal (Windows: press Win+R, type cmd, Enter)
and type:
        git --version
If you see a version number, you are done. Otherwise:

  Windows  Download from https://git-scm.com/downloads/win and install with
           the default options. Then close and reopen ICR Reviewer.
  macOS    Run "xcode-select --install" in Terminal, or install from
           https://git-scm.com/downloads/mac
  Linux    sudo apt install git     (Ubuntu/Debian)
           sudo dnf install git     (Fedora)

-------------------------------------------------------------------------------
4.5 BUILDING THE EXECUTABLE YOURSELF (DETAILS)
-------------------------------------------------------------------------------

The build uses PyInstaller, which creates a program for the operating system
it runs on. A Windows .exe must therefore be built on Windows (or by the
GitHub workflow, Way A), a macOS program on a Mac, and so on.

  Windows: double-click build_windows.bat
  macOS / Linux: ./build_unix.sh

Both scripts create a private Python environment (.venv-build), install the
packages listed in requirements-app.txt and PyInstaller, then run build.py.
The finished program appears in dist\ICR-Reviewer. Building twice is safe.


===============================================================================
5. FIRST LAUNCH: THE FIVE-MINUTE DEMO
===============================================================================

This demo works offline and proves every stage of the system works.

Step 1. Start ICR Reviewer (Section 4). The window opens on the
        "1  Review" tab.

Step 2. Click "Create demo project..." (top right of box 1).
        Choose an EMPTY folder, or create one, e.g. Documents\icr-demo.
        WARNING: if the folder is not empty, the program asks first, and then
        deletes its contents. Always use a new folder.
        A message confirms the demo was created. The fields "Project folder",
        "Base" (HEAD~1) and "Head" (HEAD) are filled in for you.

        What the demo contains: a small "shop" project in Python with two
        saved versions (commits). The second version plays the role of a
        pull request and contains deliberately planted problems:
          - logic bugs: a loop that goes one step too far; a value that can
            be None used in arithmetic (the function returning None is in a
            DIFFERENT file - only the context builder can see it); a mutable
            default argument; a division by the length of a list that may be
            empty;
          - security problems: SQL injection, eval(), a hard-coded API key;
          - quality problems: a bare "except:", "== None";
          - low-value noise: print(), a magic number, a TODO, a missing
            docstring;
          - one completely correct new function (is_known) that should get
            no findings.

Step 3. Leave "Backend" on "Demo stub (offline, no AI model)".
        Leave "Variant" on "Full system (recommended)".

Step 4. Click the large "Run review" button at the bottom.
        The green bar shows progress. It takes a few seconds.

Step 5. The program switches to the "2  Results" tab automatically. You
        should see "10 finding(s) shown, 3 filtered out".
        Click any row: the lower panel shows the code (the problem line is
        highlighted), the explanation, and the score calculation.

Step 6. Tick "Show filtered findings" to see, in grey, the 3 low-value
        comments the false-positive filter hid.

Step 7. Click "Open HTML report" to see the full report in your web browser.

Step 8. Open the "Log" tab to see what each of the five stages did.

Step 9. To see why the design matters, go back to the Review tab, choose the
        Variant "Ablation: without repository context" and click Run review
        again. The bug about get_price() returning None disappears, because
        without context the model cannot see that function's definition in
        the other file. Try "Baseline: static analysers only" as well: it
        misses the loop, None and division bugs.

ABOUT THE DEMO STUB: "Demo stub" is a set of built-in pattern rules that
behaves like a model, so every other stage can be demonstrated on any
computer without an AI model. It is NOT the research model, and its results
are not research results. Section 8 explains how to use a real model.


===============================================================================
6. THE REVIEW TAB, FIELD BY FIELD
===============================================================================

BOX 1 - WHAT TO REVIEW
  Choose one of three modes with the round buttons. Only the fields that
  apply to the chosen mode are shown.

  (a) Git repository - compare two versions of a project on your computer.
      Project folder  The folder of the project. It must be a Git repository
                      (it contains a hidden ".git" folder). Use "Browse...".
      Base (before)   The version the change starts from. Examples:
                        HEAD~1   the previous commit
                        HEAD~3   three commits back
                        main     the "main" branch
                        a1b2c3d  a commit id
      Head (after)    The version that contains the change. Usually HEAD
                      (the latest commit) or the name of a feature branch.
      The program reviews what changed from the point where Head branched
      off Base, exactly like a GitHub pull request. Uncommitted edits are NOT
      included: commit them first (git add -A, then git commit -m "msg").

  (b) Patch file - review a .diff or .patch file.
      Project folder  The folder that ALREADY CONTAINS the changed code.
      Patch file      The .patch/.diff file. Create one with, for example:
                        git diff main > change.patch
                      or download a GitHub pull request as a patch by adding
                      ".diff" to its web address
                      (https://github.com/owner/repo/pull/12.diff).

  (c) GitHub pull request - review a pull request directly from GitHub.
      Local clone (optional)  If you have the repository cloned on your
                      computer (ideally at the pull request's version), choose
                      it here so the whole repository is used as context.
                      If empty, only the changed files are used as context.
      Pull request URL  e.g. https://github.com/owner/repo/pull/12
      GitHub token (optional)  See Section 9. Needed for private
                      repositories, for more than 60 requests per hour, and
                      for posting comments. It is never saved to disk.

  "Create demo project..."  Creates the demo described in Section 5.

  Only Python (.py) and Java (.java) files are reviewed. Other files in the
  change are ignored.

BOX 2 - MODEL
  Backend         "Demo stub (offline, no AI model)" - see Section 5.
                  "Local LLM server (Ollama / LM Studio / vLLM)" - a real
                  open-weight model running on your computer or network.
  Server URL      Shown for the LLM server. Defaults:
                    Ollama      http://localhost:11434/v1
                    LM Studio   http://localhost:1234/v1
  Model name      The model to use, exactly as the server names it, e.g.
                  qwen2.5-coder:7b (Ollama) or icr-reviewer (your trained
                  model, Section 8.4).
  Test connection Checks that the server answers and lists its models.

BOX 3 - OPTIONS
  Variant         What to run (Section 11). Use "Full system" normally.
  Filter threshold  0.00 to 1.00 (default 0.45). Findings scoring below it
                  are hidden as likely false alarms. Higher = fewer findings
                  and fewer false alarms but more missed problems. Lower = the
                  opposite. Every finding's score is shown in the results.
  Tuned filter file (optional)  The filter_config.json produced by threshold
                  tuning (Section 16). When given, it REPLACES the slider: it
                  sets the threshold and the three weights found best on the
                  validation data.
  Save reports to Where reports are saved. Default: a folder "ICR-Reviews"
                  in your home folder. Each run creates its own sub-folder,
                  named with the date, time and variant, e.g.
                  review-20261022-143005-full
  Post findings to the GitHub pull request  (GitHub mode only) - Section 9.

RUN REVIEW
  Click "Run review". The program checks your inputs first and tells you if
  something is missing. While it runs, the window stays usable; the bar and
  the status line show progress. Your choices (except the token) are
  remembered for next time.


===============================================================================
7. THE RESULTS TAB, THE LOG TAB AND THE REPORT FILES
===============================================================================

RESULTS TAB
  Summary line     Number of findings shown and filtered, variant, time.
  Table columns    Status    "shown" or "filtered" (grey)
                   Category  security | logic | quality | review
                               security = a vulnerability
                               logic    = the code does the wrong thing
                               quality  = a maintainability problem likely
                                          to cause bugs
                               review   = a general reviewer comment
                   File, Line  Where the problem is.
                   Score     The false-positive filter score (0 to 1).
                   Finding   One-line description.
  Order            Security first, then logic, quality, review.
  Detail panel     Click a row to see:
                   - the code around the line (problem line highlighted);
                   - Problem / Evidence / Why it matters / Suggested direction;
                   - the score calculation, e.g.
                     0.6 x confidence 0.85 + 0.25 x static agreement 1.0
                     + 0.15 x context support 0.50
                     (static agreement: 1 = a checker flagged the same line,
                      0.5 = a neighbouring line, 0 = none;
                      context support: 1 = everything the finding mentions
                      exists in the code, 0 = it mentions things that do not
                      exist, which suggests the model invented them);
                   - which static-analysis warnings agree.
  Show filtered findings  Shows hidden findings in grey.
  Open HTML report        Opens the report in your web browser.
  Open output folder      Opens the folder containing the report files.

LOG TAB
  A record of each stage: how many code units were indexed, how many static
  warnings were found, the verdict for each changed block, how many findings
  the filter kept, and where the reports were saved. If something fails, the
  technical error details appear here.

REPORT FILES (in each run's folder)
  review_report.html  For people. Opens in any browser, works offline,
                      follows your system's light/dark setting.
  review_report.md    The same content in Markdown (readable as plain text,
                      displayed nicely on GitHub).
  review_report.json  Everything, for analysis: every finding (also the
                      filtered ones) with its scores, the static warnings,
                      the retrieved context, the settings used and the time
                      taken by each stage.


===============================================================================
8. USING A REAL AI MODEL
===============================================================================

The executable talks to an AI model through a "local LLM server". The model
runs on your computer (or another computer you control); your code is not
sent to any online AI service.

-------------------------------------------------------------------------------
8.1 WITH OLLAMA (RECOMMENDED)
-------------------------------------------------------------------------------
Step 1. Download and install Ollama from https://ollama.com/download
        (Windows, macOS and Linux). On Windows and macOS it starts
        automatically in the background after installing (look for the llama
        icon near the clock).
Step 2. Open a terminal (Windows: Win+R, cmd, Enter) and download a code
        model. Choose ONE according to your computer:
            ollama pull qwen2.5-coder:1.5b   (about 1 GB;  4-8 GB RAM; fast)
            ollama pull qwen2.5-coder:7b     (about 4.7 GB; 16 GB RAM; better)
        Wait until it says "success".
Step 3. Optional check in the terminal:
            ollama run qwen2.5-coder:1.5b "Say hello"
Step 4. In ICR Reviewer, box 2: Backend = "Local LLM server ...",
        Server URL = http://localhost:11434/v1,
        Model name = the exact name you pulled (e.g. qwen2.5-coder:1.5b).
Step 5. Click "Test connection". It should say "Connected. Models: ...".
Step 6. Click "Run review". A real model is much slower than the demo stub:
        from several seconds to a few minutes per changed block, depending
        on your computer. The green bar moves after each block.

-------------------------------------------------------------------------------
8.2 WITH LM STUDIO
-------------------------------------------------------------------------------
Step 1. Install LM Studio from https://lmstudio.ai
Step 2. In LM Studio, search for and download a coder model, e.g.
        "Qwen2.5 Coder 7B Instruct" (GGUF).
Step 3. Open the "Developer" (server) section, load the model and click
        "Start Server". Note the address, normally http://localhost:1234
Step 4. In ICR Reviewer: Server URL = http://localhost:1234/v1 ; click
        "Test connection" and copy the model name it lists into
        "Model name".

-------------------------------------------------------------------------------
8.3 A SERVER ON ANOTHER COMPUTER
-------------------------------------------------------------------------------
Any OpenAI-compatible server works (vLLM, llama.cpp server, Ollama on another
machine). Enter its address with /v1 at the end, e.g.
http://192.168.1.20:11434/v1  (for Ollama, start it on that machine with the
environment variable OLLAMA_HOST=0.0.0.0 so other computers can reach it).
If the server needs a key, set the environment variable ICR_LLM_KEY before
starting ICR Reviewer.

-------------------------------------------------------------------------------
8.4 USING YOUR OWN TRAINED (LoRA) MODEL
-------------------------------------------------------------------------------
The research model is an open-weight code model adapted with LoRA
(Chapter 3.4.3). Training happens on a GPU (e.g. Google Colab), see
Section 16. To use the trained model in this program:
Step 1. On the training machine run:
            python training/export_for_ollama.py --model Qwen/Qwen2.5-Coder-1.5B-Instruct --adapter outputs/lora-reviewer --out outputs/merged
        This merges the adapter into the model and prints the next commands.
Step 2. Convert the merged model to a GGUF file with llama.cpp, using the
        command the script prints.
Step 3. Copy the .gguf file and the generated "Modelfile" to the computer
        running ICR Reviewer, open a terminal in that folder and run:
            ollama create icr-reviewer -f Modelfile
        (If you moved the .gguf file, first edit the FROM line in Modelfile
        so it points to the file's new location.)
Step 4. In ICR Reviewer: Local LLM server, Model name = icr-reviewer.
Step 5. If you tuned the filter (training/tune_threshold.py), select its
        filter_config.json in "Tuned filter file".

Note: the executable deliberately does not include PyTorch (it would add
several gigabytes). The "hf" backend (loading the model directly with
PyTorch) is available only when running from source code (Section 16).


===============================================================================
9. REVIEWING A GITHUB PULL REQUEST (AND POSTING COMMENTS)
===============================================================================

Step 1. In box 1 choose "GitHub pull request".
Step 2. Paste the pull request's web address, for example
        https://github.com/owner/repo/pull/12
Step 3. For a PUBLIC repository and occasional use, the token can stay empty
        (GitHub allows 60 requests per hour without one; a review uses about
        2 requests plus one per changed file).
Step 4. Click Run review. The program downloads the title, description,
        changes and the new versions of the changed files.

CREATING A GITHUB TOKEN (needed for private repositories, frequent use or
posting comments):
  a) On github.com click your profile picture -> Settings ->
     Developer settings (bottom of the left menu) -> Personal access tokens
     -> Fine-grained tokens -> "Generate new token".
  b) Name: ICR Reviewer. Expiration: e.g. 30 days.
  c) Repository access: "Only select repositories" -> choose the
     repositories you will review.
  d) Permissions -> Repository permissions:
        Contents       Read-only
        Pull requests  Read and write   (Read-only if you will not post)
  e) Click "Generate token" and copy it (it starts with github_pat_).
     GitHub shows it only once.
  f) Paste it into "GitHub token". The program does not save it; you paste
     it each session. Treat it like a password and never commit it to code.

POSTING THE FINDINGS ON THE PULL REQUEST:
  Tick "Post findings to the GitHub pull request as comments" before
  clicking Run review. The program posts ONE review of type "Comment" with
  an inline comment on each shown finding (filtered findings are not
  posted). It never approves, requests changes or merges. If GitHub refuses
  an inline comment, the whole report is posted as a single comment instead.

AUTOMATIC REVIEWS ON EVERY PULL REQUEST:
  The source code includes .github/workflows/ai-review.yml, which runs the
  reviewer automatically whenever a pull request is opened. See
  docs/STEP_BY_STEP.md, Section 4.


===============================================================================
10. REVIEWING YOUR OWN PROJECT OR A PATCH FILE
===============================================================================

YOUR OWN PROJECT WITH GIT
  1) Make sure your project is a Git repository. If not, open a terminal in
     the project folder and run once:
         git init
         git add -A
         git commit -m "Before my change"
  2) Make your change, then save it as a commit:
         git add -A
         git commit -m "My change"
  3) In ICR Reviewer: mode "Git repository", Project folder = your project,
     Base = HEAD~1, Head = HEAD, Run review.
  If you work on a branch, use Base = main and Head = your branch name to
  review everything on the branch.

A PATCH FILE
  1) Make sure the project folder contains the NEW code (the change applied).
  2) Mode "Patch file", choose the folder and the .patch/.diff file.
  This mode does not need Git.


===============================================================================
11. RUNNING THE EVALUATION VARIANTS (ABLATIONS AND BASELINES)
===============================================================================

The "Variant" list contains the configurations compared in Chapter 3.8.5:

  Full system (recommended)               everything switched on
  Ablation: without repository context    no context builder
  Ablation: without static analysis       no static checkers
  Ablation: without false-positive filter every finding is shown
  Ablation: without explanations          no explanation step
  Baseline: LLM with the diff only        the model sees only the changed
                                          lines: no context, no checkers, no
                                          filter, no explanations. For a fair
                                          baseline, use the ORIGINAL base
                                          model here, not your trained one.
  Baseline: static analysers only         no AI model at all

Run the same change with several variants and compare the reports. Each run
is saved in its own folder named after the variant. For large-scale
measurement on datasets (precision, recall, F1, false-positive rate, time),
use evaluation/run_eval.py from the source code (Section 16).


===============================================================================
12. THE COMMAND-LINE TOOL (ICR-Reviewer-cli)
===============================================================================

Open a terminal IN the ICR-Reviewer folder:
  Windows: open the folder in File Explorer, click the address bar, type cmd
           and press Enter. Commands start with  ICR-Reviewer-cli.exe
  macOS/Linux: cd to the folder; commands start with  ./ICR-Reviewer-cli

Check that everything is available (Git, Pylint, Semgrep, model server):
    ICR-Reviewer-cli check
    ICR-Reviewer-cli check --base-url http://localhost:1234/v1

Create the demo project:
    ICR-Reviewer-cli demo --path C:\icr-demo

Review (Git mode) and open the report when finished:
    ICR-Reviewer-cli review --repo C:\icr-demo --base HEAD~1 --open

Review with a real model through Ollama:
    ICR-Reviewer-cli review --repo C:\icr-demo --base HEAD~1 --backend openai --model qwen2.5-coder:1.5b

Review a patch file:
    ICR-Reviewer-cli review --repo C:\myproject --patch C:\change.patch

Review a GitHub pull request and post the findings:
    ICR-Reviewer-cli review --pr-url https://github.com/owner/repo/pull/12 --token github_pat_XXXX --post-github

Run an ablation or baseline:
    ICR-Reviewer-cli review --repo C:\icr-demo --base HEAD~1 --variant no_context
    (variants: full, no_context, no_static, no_filter, no_explanation,
     llm_diff_only, static_only)

All review options:
    --repo PATH          project folder
    --base REF --head REF   Git mode (head defaults to HEAD)
    --patch FILE         patch mode
    --pr-url URL         GitHub mode
    --token TOKEN        GitHub token (or set the GITHUB_TOKEN variable)
    --description TEXT   pull request description to give the model
    --variant NAME       see above
    --backend heuristic|openai|hf   (hf only when running from source)
    --model NAME  --base-url URL    model server settings
    --filter-config FILE  tuned filter settings
    --threshold 0.45     filter threshold
    --out FOLDER         where to save reports (default review_output)
    --open               open the HTML report afterwards
    --post-github        post findings to the pull request
Help for any command:
    ICR-Reviewer-cli --help
    ICR-Reviewer-cli review --help
Open the desktop window from the terminal:
    ICR-Reviewer-cli gui

Exit codes: 0 = success, 1 = error (message printed), 2 = wrong options.


===============================================================================
13. TROUBLESHOOTING
===============================================================================

PROBLEM: Windows says "Windows protected your PC".
  -> Click "More info" -> "Run anyway" (Section 4.1, step 4).

PROBLEM: Nothing happens when I double-click, or the window closes at once.
  -> Make sure you unzipped the WHOLE folder (do not run the program from
     inside the zip) and that "_internal" is next to the program.
  -> Run ICR-Reviewer-cli check in a terminal (Section 12): it prints the
     error instead of closing.
  -> Antivirus may have removed a file: restore it and add an exclusion.

PROBLEM: "Git is not installed or not on PATH".
  -> Install Git (Section 4.4), then close and reopen ICR Reviewer.

PROBLEM: "The project folder is not a Git repository".
  -> Use the folder that contains the hidden .git folder (the top of the
     project), or run git init as in Section 10, or use Patch file mode.

PROBLEM: "No reviewable Python or Java changes were found".
  -> The change contains no added lines in .py or .java files, or Base and
     Head are the same version. Check with: git log --oneline
  -> Uncommitted edits are not reviewed in Git mode: commit them first.
  -> Deleted files and lines are not reviewed (only added/changed code).

PROBLEM: Git error mentioning "unknown revision" or "bad revision".
  -> Base or Head does not exist. HEAD~1 needs at least two commits. Branch
     names are case-sensitive. List branches with: git branch -a

PROBLEM: "Cannot reach the LLM server".
  -> Start Ollama (or the LM Studio server) and click Test connection.
  -> Check the Server URL ends with /v1 and uses the right port
     (Ollama 11434, LM Studio 1234).

PROBLEM: "The server does not have the model ...".
  -> The model name must match exactly. Run: ollama list
     and copy the name, or pull it: ollama pull qwen2.5-coder:1.5b

PROBLEM: The review with a real model is very slow or the computer freezes.
  -> Use a smaller model (qwen2.5-coder:1.5b), close other programs,
     review smaller changes. Large changes are split into blocks of 80
     added lines; each block needs several model calls.

PROBLEM: A real model gives few or strange findings.
  -> General models are not trained for this task; that is why the project
     fine-tunes one with LoRA (Section 8.4). Small models also make more
     mistakes. Try the 7B model, or lower the threshold to see weaker
     findings.

PROBLEM: "GitHub's limit of 60 requests per hour without a token was
         reached" or "Pull request not found".
  -> Create and enter a token (Section 9). Private repositories always need
     one, with access to that repository.

PROBLEM: Posting to GitHub fails with 403 or "Resource not accessible".
  -> The token needs "Pull requests: Read and write" on that repository,
     and must not be expired.

PROBLEM: Semgrep shows "not found" in "check".
  -> This is fine. Semgrep does not run natively on Windows; the program
     uses its built-in security rules instead, which cover the same
     patterns. On macOS/Linux you can optionally install Semgrep
     (pip install semgrep) and it will be used automatically.

PROBLEM: macOS: "cannot be opened because the developer cannot be
         verified".
  -> Section 4.2, step 3.

PROBLEM: Linux: "GLIBC_2.xx not found".
  -> Build on your own machine with ./build_unix.sh (Section 4.5).

PROBLEM: The window is too large for my screen.
  -> Maximise the window (double-click its title bar). The minimum useful
     size is 860 x 600.

PROBLEM: Building with build_windows.bat fails.
  -> Make sure Python 3.10-3.12 from python.org is installed with
     "Add python.exe to PATH" and "tcl/tk" ticked. Check with: python --version
  -> Delete the folders .venv-build, build and dist and run it again.
  -> Or use the GitHub method (Section 4.1, Way A).

If a problem is not listed: open the Log tab (or run the same review with
ICR-Reviewer-cli) and read the last lines of the error message.


===============================================================================
14. WHERE SETTINGS AND REPORTS ARE STORED; UNINSTALLING
===============================================================================

  Settings  <your home folder>/.icr_reviewer/settings.json
            (Windows: C:\Users\<you>\.icr_reviewer\settings.json)
            Holds the last values you entered, except the GitHub token.
            Delete this file to reset the program to its defaults.
  Reports   <your home folder>/ICR-Reviews/  unless you chose another
            folder in "Save reports to".
  Temporary files  Created in the system temporary folder during a review
            and removed afterwards.

UNINSTALLING: delete the ICR-Reviewer folder, the .icr_reviewer folder in
your home folder and, if you no longer need them, the ICR-Reviews folder and
any demo project folders. Nothing is written to the Windows registry. Ollama
and Git, if you installed them, are uninstalled separately.


===============================================================================
15. PRIVACY AND SAFETY
===============================================================================

- With the demo stub or a local model, your code never leaves your computer
  (or the server you chose).
- In GitHub mode the program only talks to api.github.com, and only for the
  pull request you entered.
- The GitHub token is kept in memory only and is never written to disk or
  to the reports.
- The program never modifies the project it reviews. It only reads files and
  runs read-only Git commands (git diff, git show). The only exception is
  "Create demo project", which writes into the folder you choose.
- The findings are advisory and can be wrong (false positives and missed
  problems). Always check them yourself before acting on them.


===============================================================================
16. RUNNING FROM SOURCE CODE, TRAINING AND EVALUATION
===============================================================================

For the research work (training the model and measuring results), use the
source code folder "intelligent-code-reviewer" with Python 3.10-3.12:

    python -m venv .venv
    .venv\Scripts\activate            (macOS/Linux: source .venv/bin/activate)
    pip install -r requirements.txt
    python -m pytest -q               (all tests should pass)
    python -m icr gui                 (the same desktop window)
    python -m icr review --repo examples/demo_repo --base HEAD~1

Research workflow (details in docs/STEP_BY_STEP.md):
  1) Collect data          training/make_bug_samples.py
                           (CVEfixes, Defects4J, BugsInPy)
  2) Prepare data          training/prepare_data.py
                           (filter, de-duplicate, split by project)
  3) Fine-tune with LoRA   training/train_lora.py
                           or training/colab_train.ipynb on a free Colab GPU
                           (pip install -r requirements-train.txt)
  4) Tune the filter       training/tune_threshold.py  -> filter_config.json
  5) Evaluate              evaluation/run_eval.py      -> metrics table
  6) Human study           evaluation/make_rating_sheet.py and
                           evaluation/analyze_human_study.py
  7) Use the model in the executable   training/export_for_ollama.py
                                       (Section 8.4)

Dry run of the whole chain on a toy dataset (no GPU needed):
    python examples/make_toy_dataset.py
    python training/prepare_data.py --codereviewer examples/toy_data/reviews.jsonl --bugs examples/toy_data/bugs.jsonl --out data/toy --val-frac 0.3 --test-frac 0.3
    python training/tune_threshold.py --val data/toy/val_bugs.jsonl --backend heuristic --out outputs/toy
    python evaluation/run_eval.py --test examples/toy_data/bugs.jsonl --backend heuristic --out results/toy


===============================================================================
17. QUICK REFERENCE CARD
===============================================================================

  Start the program ........... double-click ICR-Reviewer(.exe)
  Try it in 1 minute .......... Create demo project... -> Run review
  Review my project ........... Git repository, folder, Base HEAD~1, Run
  Review a GitHub PR .......... GitHub pull request, paste URL, Run
  Use a real model ............ install Ollama, ollama pull qwen2.5-coder:1.5b,
                                Backend = Local LLM server, Test connection
  Fewer false alarms .......... move Filter threshold to the right
  See hidden findings ......... Results tab -> Show filtered findings
  Full report ................. Results tab -> Open HTML report
  Something failed ............ Log tab, then Section 13
  Reset settings .............. delete ~/.icr_reviewer/settings.json

===============================================================================
  End of README
===============================================================================
