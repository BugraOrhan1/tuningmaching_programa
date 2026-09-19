# WINDOWS_INSTALL.md — TuningMatching op Windows 10/11 (§48/§78)

## Wat de technicus nodig heeft

Niets behalve Windows. Geen Python, geen Git, geen VS Code, geen
virtualenv. De installer of portable map bevat runtime, dependencies, GUI
én CLI.

## Optie A — installer (aanbevolen voor werkplekken)

1. Bouw op een Windows-buildmachine (één keer):
   ```bat
   git clone https://github.com/BugraOrhan1/tuningmaching_programa
   cd tuningmaching_programa
   packaging\build_windows.bat
   ```
   Het script maakt zelf een venv, installeert `requirements.txt` +
   PyInstaller, draait eerst de volledige test-suite (de build stopt bij een
   falende test) en produceert daarna:
   - `dist\TuningMatching\TuningMatching.exe` — portable build
   - `dist\TuningMatchingSetup.exe` — installer (Inno Setup, indien `iscc`
     in PATH)

2. Op de tuning-PC: `TuningMatchingSetup.exe` uitvoeren (geen admin nodig,
   `PrivilegesRequired=lowest`). Installer verzorgt: programma, runtime,
   dependencies, startmenu-snelkoppeling. Database-initialisatie,
   migratie en eerste configuratie doet de **first-run wizard** bij de
   eerste start.

## Optie B — portable map (USB/meerdere PC's)

`dist\TuningMatching` naar een map naar keuze kopiëren en
`TuningMatching.exe` starten. Data staat standaard in `data\` naast de exe
(of zoals gekozen in `config.json`).

## Eerste start (first-run wizard, §49)

De wizard vraagt: library-roots (bron blijft op eigen schijf), resource-
profiel (LOW/BALANCED/HIGH) en of de eerste (hervatbare) scan direct start.
Later toevoegen kan altijd via **Library (V5)** of
`TuningMatching.exe library-add D:\Tuning`.

## Configuratie

`config.json` naast de exe (of `TUNING_CONFIG`-omgevingsvariabele):
`data_dir`, `max_file_mb`, `top_matches`, `candidate_pool`, `block_size`,
`diff_merge_gap`, `scan_batch`, `resource_preset`. Wijzigen → herstart.

## Local API

`TuningMatching.exe api --port 8765` start de lokale REST-API op
127.0.0.1 (local-first, geen cloud). Bij elke start wordt een nieuwe
`X-API-Key` gegenereerd en in de console getoond; álle endpoints vereisen
die key (§72). Geen bestandsbewerkingen zonder autorisatie.

## Bekende bouwbeperking (eerlijk)

De PyInstaller-spec (`packaging/tuningmatching.spec`) en het buildscript
zijn gevalideerd op: entry-point (`app/__main__.py`), alle 49
hiddenimports (48 direct importeerbaar; GUI-module getest met de
Qt-runtimebibliotheken van de ontwikkel-omgeving) en de test-suite als
build-gate. Het daadwerkelijke `TuningMatchingSetup.exe` is nog niet op
een schone Windows-machine gebouwd/getest vanuit de Linux-ontwikkel-
sandbox; dat is de enige nog open stap van §48/§80 (zie STATUS.md).

## Fouten zoeken

- Logs: `data\app.log` (roterend, 3×2 MB).
- Health check: GUI **Backup & Health** of `TuningMatching.exe health`.
- Corrupte database: `TuningMatching.exe restore <backupmap>` (maakt
  automatisch eerst een veiligheidsbackup van de huidige staat).
