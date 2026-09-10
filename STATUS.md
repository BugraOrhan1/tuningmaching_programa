# Applicatiestatus

Datum: 2026-09-10

## Eindstatus

**NOT READY als volledige V2/V2.5-productrelease.**

**V1 READY voor de lokale BIN/ORI-workflow én de automatische WinOLS-extractie.**

De applicatie werkt betrouwbaar voor: import van raw `.bin`/`.ori`, het automatisch extraheren van alle embedded version-binaries uit een echte WinOLS 5 `.ols` (read-only), rolbepaling (Original/Tuned/unknown) met gescheiden role-/relation-confidence, automatische pair-voorstellen, diffanalyse, matching, kandidaat-Tuning-DNA uit bevestigde paren en kandidaat-tunebestanden met expliciete waarschuwing. Mapdefinities, assen, units en cross-software alignment zijn nog niet betrouwbaar gedecodeerd — daarom blijft de volledige V2/V2.5 NOT READY.

## Wat daadwerkelijk werkt

- Applicatie initialiseert de SQLite-database automatisch (schema v4 met `ols_version_binaries` en `tune_candidates`).
- Desktop-GUI start zonder Python- of applicatiefout; Quick Workflow heeft twee knoppen: (1) WinOLS-project volledig automatisch verwerken, (2) nieuwe BIN automatisch matchen + kandidaat-tune vanaf 70%.
- CLI (`auto-ols`, `auto-process`, `generate-candidate`, `tune-candidates`) en REST API (`/winols-projects/{id}/versions`, `/auto-process`, `/files/{id}/generate-candidate`, `/tune-candidates`) bestrijken dezelfde flow.
- Raw `.bin` en `.ori` kunnen worden geïmporteerd; beheerde kopieën worden gehasht en tegen wijziging gecontroleerd.
- **Automatische binary-extractie uit echte OLS:** embedded version-binaries worden rechtstreeks uit de `.ols` gehaald (geen handmatige WinOLS-exports meer nodig) via twee bewezen methoden: `explicit_import_header` (filenaamrecord + padrecord + vast nulveld vóór de binary) en `repeating_identity_header` (identiteitsheaders met vaste stride direct na nul-padding, ≥99% blokgelijkenis).
- Rolbepaling met prioriteit: expliciete WinOLS-metadata > version/project-relatie > object-relatie > volgorde-inferentie; `role_confidence` en `relation_confidence` zijn gescheiden velden (geverifieerd op de echte OLS: `Origineel` role_conf 100 + relation explicit, Stage-versies role_conf 95 + relation inferred 75).
- Numerieke/interne OLS-objectnamen blijven altijd `unknown`.
- Automatische pair-voorstellen bij gelijke binary-grootte; auto-bevestiging alleen bij role_confidence ≥ 95 voor beide kanten, anders blijven ze onbevestigd voor review.
- Original/Tuned-paren kunnen worden aangemaakt en bevestigd; automatische classificatie gebruikt expliciete labels, exacte hashes en zeer sterke unieke binary-evidence; ambigue bestanden blijven `unknown` + review.
- Diffanalyse, hexweergave en rapportexport werken; similarity en compatibility confidence zijn aparte velden.
- Tuning-DNA wordt alleen opgebouwd uit bevestigde paren; regio's krijgen nooit automatisch een mapnaam (Boost/Torque e.d. blijven `unknown`).
- `generate_tune_candidate` produceert een kandidaat-bestand (output `reports/candidates/<sha256>.bin`) met guards: drempel 50–100, minimaal één match ≥ drempel, bevestigd pair, regionale similarity ≥ 98%; het doelbestand wordt nooit gewijzigd en checksums worden niet gecorrigeerd (expliciete waarschuwing in GUI-dialoog).
- OLS-bestanden worden gekopieerd en nooit gewijzigd (read-only); herimport van dezelfde OLS vernieuwt records zonder duplicaten en behoudt reviews.
- Herhaalde batchimport maakt geen dubbele records voor dezelfde bron, hash en type.
- Database schema-versie en startup-validatie zijn aanwezig.

## Uitgevoerde tests

Volledige testsuite met de project-`.venv` (incl. GUI-tests in offscreen-modus):

```text
49 passed, 2 warnings
```

De warnings komen uit FastAPI/Starlette/httpx-deprecations en veroorzaken geen testfout.

Belangrijkste testdekking deze ronde:

- `tests/test_ols_structure.py` (5 synthetische OLS-fixtures): structuurparser (versies, binaries, stride, identiteit), auto-process extractie met rollen en paren, paren + DNA bij gelijke grootte, en beide candidate-guards (drempelgrenzen, geen bevestigd pair).
- `tests/test_ols_real.py` (2 tests op de echte `GASDROP_100119.ols`): aantoonbare structuur zonder verzonnen links en herimport zonder duplicaten; verifieert de confidence-split op het echte bestand (role_conf 100 / relation inferred 75).

## Verificatie op de echte OLS (GASDROP_100119.ols)

SHA256 `dcfc2d8d03b035e7d559fa6fb4c80b492c79e937cf1df0729f0912605782e3e8`, 8.738.048 bytes, header `WinOLS File`. Bewezen en getest:

- Identiteit: `53/1/MG1CS003/11/MG1CS003_BX8_R1C2J772B//R1C2J772B///`, stride 2.097.152 bytes.
- 5 binaries geëxtraheerd: Original via `explicit_import_header` (855.132 B, `f65abeea…`), 3 complete 2 MiB-pages (`d2b0cdef…`, `c195636e…` ×2 — pages 3 en 4 zijn byte-identiek), 1 onvolledige staart (1.289.608 B, `446af799…`, compleet=False).
- Versies: v1 `Origineel` → original (role_conf 100, relation `version_to_binary_explicit`), v2 `Stage1+vmax` en v3/v4 `+pops and bang` → tuned (role_conf 95, relation `version_to_binary_order_inferred` 75), vNone naamloos → unknown.
- Alle 5 binaries belanden automatisch in Files (`originals/`|`tuned/`|`unknown/<sha256>.bin`).
- Correct conservatief gedrag: Original (855.132 B) vs 2 MiB-pages → alle paren `size_mismatch_not_paired`, DNA leeg. Het programma verzint geen paren bij grootteverschil.

## Wat nog niet volledig werkt

- WinOLS-mapdefinities, assen, units en mapwaarden worden niet betrouwbaar uit `.ols` gelezen; `Kaart`-labels zijn alleen zichtbare-string inventory met adresvoorstel.
- Geen structurele mapalignment naar een nieuwe softwarevariant; Tuning-DNA is kandidaat-structuurkennis.
- Checksums/Eeprom-corrections in gegenereerde kandidaat-bestanden: niet gecorrigeerd, alleen kandidaat voor review.
- Er is geen automatische mapnaamherkenning zoals Boost, Torque Limiter of Ignition zonder echte bronmetadata.
- Binary similarity en compatibility confidence zijn geen afzonderlijke historische match-records.
- Batchimport heeft nog geen checkpoint die midden in een onderbroken import exact hervat.
- Identieke kandidaat-regeneratie maakt een tweede `tune_candidates`-rij (bestand wordt wel hergebruikt); dedupe-beleid is open.
- De binary-extractiegrens van de eerste binary loopt door tot de volgende recordgrens inclusief nul-padding; de exacte payload-lengte is niet bewezen.
- Stride < 1024 bytes (kleine synthetische projecten) wordt bewust niet als pagina-anker gedetecteerd; echte WinOLS-projecten zitten daar ruim boven.

## Placeholders of beperkte implementaties

- `extract_available_calibration_information()` rapporteert bewust `not_available` zolang betrouwbare mapinformatie ontbreekt.
- Onbekende recordtypen worden als `UNKNOWN_RECORD_TYPE` opgeslagen, nooit geraden.
- OLS-`objects` zijn zichtbare ASCII-inventory-objecten, niet gegarandeerd alle echte WinOLS-objecten.
- Tuning-DNA-regio's krijgen bewust `unknown` als label wanneer geen verifieerbare mapnaam beschikbaar is.
- Structurele alignment is een analysevoorstel en geen overdraagbare tuninginstructie.
- De nearest-neighbor-learninglaag gebruikt bytehistogrammen als baseline, geen getraind model dat tuningwaarden leert.

## Afhankelijk van echte WinOLS-data

De volgende onderdelen kunnen pas betrouwbaar worden uitgebreid met meer echte, representatieve WinOLS 5-exports:

- mapnamen, mapstructuren, assen, factoren, units en waarden;
- cross-software calibration alignment;
- Tuning-DNA-validatie over meerdere echte projecten;
- paren binnen projecten waar Original en Stage dezelfde binary-grootte hebben (verificatie of de pair-regels daar ook goed uitkomen).

De bron-`.ols` mag niet worden aangepast en moet read-only worden aangeleverd voor onderzoek.

## Applicatie starten

Open PowerShell in de projectmap:

```powershell
cd C:\tuningmaching_programa
.\start.ps1
```

Als PowerShell scripts blokkeert:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\start.ps1
```

Direct met de projectomgeving:

```powershell
.\.venv\Scripts\python.exe -m app.main gui
```

CLI-databasecontrole:

```powershell
.\.venv\Scripts\python.exe -m app.main init
```

## Echte OLS-database veilig testen

1. Maak eerst een volledige backup van de originele WinOLS-database en `.ols`-bestanden.
2. Test uitsluitend met een kopie, nooit met de actieve WinOLS-database.
3. Kies in de GUI **Quick Workflow → WinOLS-project volledig automatisch verwerken** (of CLI `auto-ols <pad>`).
4. Controleer hash, bestandsgrootte en de geëxtraheerde versies/binaries in het resultaatvenster.
5. Vergelijk daarna SHA256 van het origineel met de backup — het bronbestand wordt nooit gewijzigd.
6. Controleer in **Files** de automatisch geëxtraheerde binaries en hun rol/confidence; twijfelgevallen blijven `unknown`.
7. Bevestig een voorgesteld pair alleen na controle in WinOLS.
8. Genereer pas daarna kandidaat-Tuning-DNA en kandidaat-tunebestanden (≥ 70% drempel); kandidaten zijn nooit definitieve ECU-bestanden en checksums zijn niet gecorrigeerd.

## Conclusie

De V1-workflow — inclusief automatische extractie van alle embedded Original/Tuned-binaries uit een echte OLS, rolbepaling met evidence en confidence, paren en kandidaat-DNA — is klaar en getest (49 passed, inclusief verificatie op de echte `GASDROP_100119.ols`). De applicatie is **niet klaar als volledige V2/V2.5** zolang echte WinOLS-mapdata, assen/units, structurele alignment en hervatbare checkpoint-import niet betrouwbaar beschikbaar zijn. V2.7 (automatische ECU-file-modificatie) blijft bewust buiten scope: boven de drempel wordt uitsluitend een kandidaat getoond.

## Echte OLS-analyse (eerste forensische ronde)

Op 2026-09-10 is de aanwezige beheerde kopie `data/winols_projects/GASDROP_100119.ols` read-only onderzocht. Waargenomen zijn BMW/Bosch/MG1CS003-metadata, `Origineel`, meerdere Stage-gerelateerde projectnamen, vijf importreferenties en 265+ zichtbare `Kaart`-labels. De volledige technische bevindingen staan in [OLS_ANALYSIS_REPORT.md](OLS_ANALYSIS_REPORT.md) en de structuurdetails in [OLS_STRUCTURE_REPORT.md](OLS_STRUCTURE_REPORT.md).
