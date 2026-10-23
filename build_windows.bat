@echo off
REM Builds ICR-Reviewer.exe and ICR-Reviewer-cli.exe on Windows.
REM Needs Python 3.10-3.12 from python.org (tick "Add python.exe to PATH" and keep "tcl/tk" selected).
cd /d "%~dp0"
python -m venv .venv-build || goto :error
call .venv-build\Scripts\activate.bat || goto :error
python -m pip install --upgrade pip
pip install -r requirements-app.txt pyinstaller || goto :error
python build.py || goto :error
echo.
echo SUCCESS. The program is in: %~dp0dist\ICR-Reviewer
echo Double-click ICR-Reviewer.exe in that folder.
pause
exit /b 0
:error
echo.
echo BUILD FAILED. Read the messages above. See README.txt section 13 (Troubleshooting).
pause
exit /b 1
