"""Build the standalone executables with PyInstaller.

    pip install -r requirements.txt pyinstaller
    python build.py

Result (in dist/ICR-Reviewer/):
    ICR-Reviewer(.exe)       desktop application
    ICR-Reviewer-cli(.exe)   command-line tool
    README.txt, rules/       instructions and Semgrep rules
PyInstaller builds for the operating system it runs on: build on Windows to get .exe files,
on macOS for macOS, on Linux for Linux (or use .github/workflows/build-executables.yml).
"""
import os
import shutil
import sys
import PyInstaller.__main__

HERE = os.path.dirname(os.path.abspath(__file__))
SEP = os.pathsep            # ';' on Windows, ':' elsewhere
COMMON = [
    "--noconfirm", "--clean", "--onedir",
    f"--add-data={os.path.join(HERE, 'rules')}{SEP}rules",
    "--collect-all=pylint", "--collect-all=astroid", "--collect-all=isort", "--collect-all=dill",
    "--collect-all=platformdirs", "--collect-all=tomlkit", "--collect-all=mccabe",
    "--collect-all=tree_sitter_python", "--collect-all=tree_sitter_java", "--collect-all=tree_sitter",
    "--hidden-import=icr.gui", "--hidden-import=icr.demo",
    # not used by the executable; keeps it small
    "--exclude-module=torch", "--exclude-module=transformers", "--exclude-module=sklearn",
    "--exclude-module=scipy", "--exclude-module=matplotlib", "--exclude-module=pandas",
    "--exclude-module=sacrebleu", "--exclude-module=pytest", "--exclude-module=PIL",
    "--exclude-module=cryptography", "--exclude-module=yaml", "--exclude-module=IPython",
]


def mypyc_helpers() -> list[str]:
    """Some packages (isort, black) are compiled with mypyc and import a hidden top-level helper
    module such as '24eba0d7...__mypyc'. PyInstaller cannot see it, so add it explicitly."""
    import glob
    import importlib.util
    out = []
    for pkg in ("isort",):
        spec = importlib.util.find_spec(pkg)
        if spec and spec.origin:
            site = os.path.dirname(os.path.dirname(spec.origin))
            for f in glob.glob(os.path.join(site, "*__mypyc*")):
                out.append(f"--hidden-import={os.path.basename(f).split('.')[0]}")
    return out


def build(name, script, windowed):
    PyInstaller.__main__.run([*COMMON, *mypyc_helpers(), f"--name={name}", "--windowed" if windowed else "--console",
                              "--distpath", os.path.join(HERE, "build_out", name), os.path.join(HERE, script)])


if __name__ == "__main__":
    shutil.rmtree(os.path.join(HERE, "build_out"), ignore_errors=True)
    build("ICR-Reviewer", "app_gui.py", windowed=True)
    build("ICR-Reviewer-cli", "app_cli.py", windowed=False)
    # Merge both into one folder: they share the same libraries.
    final = os.path.join(HERE, "dist", "ICR-Reviewer")
    shutil.rmtree(final, ignore_errors=True)
    shutil.copytree(os.path.join(HERE, "build_out", "ICR-Reviewer", "ICR-Reviewer"), final)
    cli_dir = os.path.join(HERE, "build_out", "ICR-Reviewer-cli", "ICR-Reviewer-cli")
    for item in os.listdir(cli_dir):
        src, dst = os.path.join(cli_dir, item), os.path.join(final, item)
        if not os.path.exists(dst):
            (shutil.copytree if os.path.isdir(src) else shutil.copy2)(src, dst)
    shutil.copy2(os.path.join(HERE, "README.txt"), final)
    shutil.rmtree(os.path.join(HERE, "build_out"), ignore_errors=True)
    print(f"\nDone. Executables are in {final}")
    if sys.platform == "darwin":
        print("macOS: the .app bundle is in build_out before merging; run ICR-Reviewer from the folder or use the CLI.")
