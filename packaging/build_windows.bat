@echo off
REM ============================================================
REM  TuningMatching — Windows-build (één klik, geen Python nodig
REM  op de doelmachine; alleen op deze build-machine)
REM  Vereisten op de buildmachine: Python 3.11+ met
REM    pip install -r requirements.txt pyinstaller
REM  Optioneel: Inno Setup 6 in PATH voor TuningMatchingSetup.exe
REM ============================================================
setlocal
cd /d "%~dp0.."

echo [1/3] Virtualenv en dependencies controleren...
if not exist .venv (
    python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller

echo [2/3] Tests draaien vóór de build...
python -m pytest -q || goto :error

echo [3/3] PyInstaller-build...
pyinstaller packaging\tuningmatching.spec --noconfirm --clean || goto :error

echo Portable build klaar: dist\TuningMatching\TuningMatching.exe
where iscc >nul 2>nul
if %errorlevel%==0 (
    echo Installer bouwen met Inno Setup...
    iscc packaging\installer.iss || goto :error
    echo Installer klaar: dist\TuningMatchingSetup.exe
) else (
    echo Inno Setup niet gevonden; alleen portable build gemaakt.
)
exit /b 0
:error
echo BUILD GEFAALD
exit /b 1
