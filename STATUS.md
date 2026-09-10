# Applicatiestatus

Datum: 2026-09-10

## Eindstatus

**NOT READY als volledige V2/V2.5-productrelease.**

**V1 READY voor de geteste lokale BIN/ORI-workflow.**

De huidige applicatie werkt betrouwbaar voor de bestaande lokale analyse van raw `.bin`/`.ori`-bestanden, bevestigde Original/Tuned-paren, diffs, matching en kandidaat-Tuning-DNA. De OLS-laag is veilig en read-only, maar kan het proprietary WinOLS-formaat nog niet volledig reconstrueren.

## Wat daadwerkelijk werkt

- Applicatie initialiseert de SQLite-database automatisch.
- Desktop-GUI start zonder Python- of applicatiefout.
- CLI start en accepteert de beschikbare commando's.
- Raw `.bin` en `.ori` kunnen worden geïmporteerd.
- Bestaande lokale `.bin`/`.ori`-paden die aantoonbaar in OLS-records staan, worden als `unknown` in Files geïndexeerd en aan het OLS-project gekoppeld.
- Beheerde kopieën worden gehasht en tegen wijziging gecontroleerd.
- Original/Tuned-paren kunnen worden aangemaakt en bevestigd.
- Automatische pair-voorstellen blijven onbevestigd.
- Automatische classificatie gebruikt expliciete labels, exacte hashes en zeer sterke unieke binary-evidence.
- Ambigue bestanden blijven `unknown` en gaan naar review.
- Binary similarity en compatibility confidence zijn aparte velden in analyse-resultaten.
- Diffanalyse werkt en slaat diff-regio's op in SQLite.
- Hexweergave en rapportexport werken.
- Bevestigde paren kunnen kandidaat-Tuning-DNA opleveren.
- Tuning-DNA-patronen zijn idempotent en bewaren bron-pair-ID's.
- OLS-bestanden worden gekopieerd en nooit gewijzigd.
- Zichtbare OLS-strings worden als beperkte inventory opgeslagen.
- Numerieke/interne zichtbare namen blijven `unknown` tenzij handmatig beoordeeld.
- OLS-objectreviews blijven behouden na herimport.
- Herhaalde batchimport maakt geen dubbele records voor dezelfde bron, hash en type.
- ECU- en softwarefamilievoorstellen worden opgeslagen met reviewstatus.
- Database schema-versie en startup-validatie zijn aanwezig.

## Uitgevoerde tests

Volledige testsuite met de project-`.venv`:

```text
41 passed, 2 warnings
```

De warnings komen uit FastAPI/Starlette/httpx-deprecations en veroorzaken geen testfout.

Daarnaast zijn geïsoleerde runtimechecks uitgevoerd voor:

- databasecreatie;
- BIN-import als Original en Tuned;
- diffanalyse;
- aparte similarity- en compatibility-velden;
- read-only OLS-import;
- behoud van de originele OLS-bytes;
- opslag van zichtbare OLS-objecten;
- numerieke objectnaam blijft `unknown`;
- UNKNOWN-review naar Original;
- traceerbaarheid van OLS-object naar project-ID;
- herhaalde batchimport;
- CLI-help en `init`;
- GUI-start in offscreen-modus.

## Wat nog niet volledig werkt

- De importer leest niet alle interne objecten uit een echte WinOLS 5 `.ols`-database.
- De importer kan geen betrouwbare Original/Stage 1-relatie reconstrueren wanneer WinOLS die informatie niet als leesbare tekst beschikbaar maakt.
- Binary-objecten in een opaque `.ols`-bestand worden niet geëxtraheerd.
- WinOLS-mapdefinities, assen, units en mapwaarden worden niet betrouwbaar uit `.ols` gelezen.
- Raw BIN-bestanden zijn nog niet automatisch aan hun oorspronkelijke OLS-project of OLS-object gekoppeld. OLS-source traceability werkt dus voor geïmporteerde OLS-objecten, maar niet volledig voor een later geëxporteerde BIN.
- Tuning-DNA maakt kandidaat-structuurkennis, maar voert geen structurele mapalignment naar een nieuwe softwarevariant uit.
- Er is geen automatische mapnaamherkenning zoals Boost, Torque Limiter of Ignition zonder echte bronmetadata.
- Binary similarity en compatibility confidence worden in analyse-resultaten apart berekend; ze zijn niet als afzonderlijke historische match-records opgeslagen.
- Batchimport kan veilig opnieuw worden gestart en dubbele imports overslaan, maar heeft nog geen echte checkpoint die midden in een onderbroken import exact hervat.
- Er is geen automatische tuning-output en er wordt geen BIN gewijzigd.

## Placeholders of beperkte implementaties

- `OlsImporter.extract_files()` rapporteert bewust `unsupported` voor opaque binary-objecten.
- `extract_available_calibration_information()` rapporteert bewust `not_available` zolang betrouwbare mapinformatie ontbreekt.
- OLS-`objects` zijn zichtbare ASCII-inventory-objecten, niet gegarandeerd alle echte WinOLS-objecten.
- Tuning-DNA-regio's krijgen bewust `unknown` als label wanneer geen verifieerbare mapnaam beschikbaar is.
- Structurele alignment is een analysevoorstel en geen overdraagbare tuninginstructie.
- De nearest-neighbor-learninglaag gebruikt bytehistogrammen als baseline, geen getraind model dat tuningwaarden leert.

## Afhankelijk van echte WinOLS-data

De volgende onderdelen kunnen pas betrouwbaar worden uitgebreid met een echte, representatieve WinOLS 5-export of ondersteunde projectinformatie:

- volledige objectinventaris;
- Original/Modified/Stage-versies;
- projectrelaties;
- mapnamen en mapstructuren;
- assen, factoren, units en waarden;
- cross-software calibration alignment;
- Tuning-DNA-validatie over meerdere echte projecten.

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
3. Importeer eerst één klein `.ols`-bestand via **WinOLS .ols-project importeren**.
4. Controleer hash, bestandsgrootte en de opgeslagen objectinventory.
5. Vergelijk daarna SHA256 van het originele bestand met de backup.
6. Verwacht op dit moment alleen zichtbare strings en expliciete metadata; verwacht geen volledige WinOLS-mapextractie.
7. Controleer numerieke objectnamen in **OLS Object Review**; laat twijfelgevallen `unknown`.
8. Exporteer raw Original/Tuned-bestanden vanuit WinOLS afzonderlijk als `.bin`/`.ori` en importeer die pas daarna voor byteanalyse.
9. Bevestig een pair alleen na controle in WinOLS.
10. Genereer pas daarna kandidaat-Tuning-DNA.

## Conclusie

De V1 raw-BIN-workflow is klaar en getest. De huidige V2 is een werkende, veilige basis met OLS-inventory, evidence, review en kandidaat-Tuning-DNA, maar is **niet volledig klaar als V2/V2.5** zolang echte WinOLS-objecten, projectrelaties, mapdata en hervatbare checkpoint-import niet betrouwbaar beschikbaar zijn.

## Echte OLS-analyse

Op 2026-09-10 is de aanwezige beheerde kopie `data/winols_projects/GASDROP_100119.ols` read-only onderzocht. Het bestand is 8,738,048 bytes groot, heeft de header `WinOLS File` en SHA256 `dcfc2d8d03b035e7d559fa6fb4c80b492c79e937cf1df0729f0912605782e3e8`.

Waargenomen zijn BMW/Bosch/MG1CS003-metadata, `Origineel`, meerdere Stage-gerelateerde projectnamen, vijf importreferenties en 265 zichtbare `Kaart`-labels. De huidige importer rapporteert deze evidence nu in een forensic summary. Binary-objectgrenzen, embedded BIN-relaties, version-tree, pointers en volledige mapdefinities zijn nog niet bewezen en blijven daarom `UNKNOWN`/`NOT_DECODED`.

De volledige technische bevindingen staan in [OLS_ANALYSIS_REPORT.md](OLS_ANALYSIS_REPORT.md).
