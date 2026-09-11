# ROADMAP.md

Stand: na V5 productronde (2026-09-11). Statuswoorden volgens de
V3-conventie (IMPLEMENTED / PARTIALLY IMPLEMENTED / NOT IMPLEMENTED /
UNKNOWN), met bewijsverwijzingen. V3/V4-tabellen onderaan blijven geldig
voor de historie; dit kopblok beschrijft de actuele stand.

## Afgerond in V5 (Local Library + productlaag)

| Onderdeel | Status | Bewijs |
|---|---|---|
| Library-roots, content/location-model, dedup | IMPLEMENTED | `app/library.py`, `tests/test_library.py` (9) |
| Incrementeel + hervatbaar scannen, hash-cache | IMPLEMENTED | 10k-benchmark: 0 rehashes, resume-tests |
| Offline schijven / MOVED / DUPLICATE / ERROR | IMPLEMENTED | test_library + handtest |
| 10.000-files benchmark, bron onaangeroerd | IMPLEMENTED | `scripts/library_benchmark.py` (34,9 s; SHA-bewijs) |
| Content → deep analysis (één keer per content) | IMPLEMENTED | `analyze_content`, `tests/test_product_suite.py` |
| Multi-stage New BIN retrieval (§40) | IMPLEMENTED | `new_bin_library_report`, 3 ms exact-hit @5k |
| Watch folders, nooit auto Original/Tuned (§7) | IMPLEMENTED | `set_watch`/`process_watch` + test |
| Job-manager pauze/hervat/annuleer (§51) | IMPLEMENTED | `job_pause/resume/cancel` + 2 tests |
| Auditlog (§63) + hooks | IMPLEMENTED | `audit_log`-tabel + 4 hooks + test |
| Backup/restore/health (§64) | IMPLEMENTED | manifest-SHA256-verificatie + test |
| Rapportexport JSON/CSV/MD/HTML (§62) | IMPLEMENTED | `app/reporting.py` + test (incl. HTML-escaping) |
| FTS5-zoekindex (§41) | IMPLEMENTED | `library_fts` + prefix-zoekopdrachten |
| API-uitbreiding (15 endpoints) | IMPLEMENTED | `app/api.py` + `tests/test_api_ui.py` |
| CLI-uitbreiding (12 commando's) | IMPLEMENTED | `--help` |
| GUI: Library/Jobs & Audit/Backup & Health + wizard | IMPLEMENTED | 27 pagina's, smoketest groen |
| Metadata-schaal tot 5 m records (§45) | IMPLEMENTED | `scripts/db_scale_benchmark.py` (1 ms lookups @5 m) |
| Retrieval-benchmark (§71) | IMPLEMENTED | `scripts/retrieval_benchmark.py` |
| Windows-verpakking (§48/§78) | PARTIALLY IMPLEMENTED | spec + buildscript + Inno Setup aanwezig; alle 49 hiddenimports gevalideerd; daadwerkelijke .exe-build/schone-machine-test vereist Windows (zie STATUS) |
| Echte 10 TB-dataset in productie | NOT IMPLEMENTED (hier) | vereist de bedrijfsdata; alles voorbereid + 10k/5m-schaalbewijs |
| ML/kalibratielaag (§68/§75) | NOT IMPLEMENTED (bewust) | deterministisch eerst; evaluatie-infra klaar |

## Volgorde-naar-productie (korte lijst)

1. Windows-build draaien op een Windows-machine (`packaging\build_windows.bat`)
   en schone-machine-installatie testen.
2. Echte library-roots registreren + eerste scan; daarna bevestigde paren
   invoeren en `rebuild-patterns`.
3. Na ~1.000 echte bevestigde paren: confidence-kalibratie draaien
   (`confidence/evaluate`) en pas dan statistische claims doen.

 Statuswoorden volgens de
V3-conventie (IMPLEMENTED / PARTIALLY IMPLEMENTED / NOT IMPLEMENTED /
UNKNOWN), met bewijsverwijzingen.

## Afgerond in V3 (deze ronde)

| Fase | Onderdeel | Status | Bewijs |
|---|---|---|---|
| 1 | Inspectie bestaande codebase | IMPLEMENTED | FASE1_INSPECTIE.md |
| 2 | TuningRegion + diff-intelligence | IMPLEMENTED | `tuning_region.py`, `tuning_regions`, 6 regio-tests |
| 3 | Tuning DNA v2 (region_ids, metadata) | IMPLEMENTED | `generate_tuning_dna` + `test_dna_references_persisted_regions_and_metadata` |
| 4 | Pattern clustering (signatures, ECU-scoping, stages) | IMPLEMENTED | `rebuild_patterns` + 4 patroon-tests |
| 5 | Cross-software alignment | IMPLEMENTED | `align_pattern_across_software`, `find_pattern_matches` + 2 tests |
| 6 | OLS project graph + malformed-OLS-robustheid | IMPLEMENTED | `ols_graph` + `test_malformed_ols_is_rejected_without_invention` |
| 7 | New BIN Analysis-rapport | IMPLEMENTED | `new_bin_report` + API-smoke op echte OLS |
| 8 | GUI (5 nieuwe pagina's) | IMPLEMENTED | 21 pagina's, GUI-smoketest groen |
| 9 | Performance/checkpoints/schaal | IMPLEMENTED | analysis_runs + scale_test: 100/1k/5k paren |
| — | Documentatie | IMPLEMENTED | TUNING_DNA/ARCHITECTURE/EVIDENCE_MODEL/DATABASE_SCHEMA/ROADMAP/STATUS |

## Volgende stappen (voorgestelde prioriteit)

1. **Echte datavalidatie** — V3-kennis is getest op synthetische paren en
   één echte OLS. Volgende stap: duizenden echte bevestigde paren importeren
   en de patroon-confidence kalibreren op echte tunerpraktijk
   (PARTIALLY: infrastructuur klaar, kalibratie niet UNKNOWN-tot-dan).
2. **Map detection v2** — assen/factoren/dimensies verder bewijzen
   (bijv. via herhaalde tabelformaten over projecten heen); momenteel
   alleen ramp- en rijperiodiciteitskandidaten op begrensde scan
   (PARTIALLY IMPLEMENTED).
3. **OLS-recordinventaris v2** — meer recordtypes van het WinOLS-formaat
   bewezen decoderen; alleen op aantoonbare structuur (NOT IMPLEMENTED:
   het proprietary formaat is deels onbekend — UNKNOWN).
4. **Checksum-herkenning v2** — actieve checksum-algoritme-detectie op basis
   van cross-paar delta-analyse; nu alleen kandidaatmarkering
   (PARTIALLY IMPLEMENTED).
5. **Region Viewer hexdiff** — per-byte before/after-weergave per regio in
   de GUI (bestaat al op paarniveau in de Diff Viewer; regio-niveau is
   tekstueel) (PARTIALLY IMPLEMENTED).
6. **Merge/split-workflows** — technician kan patronen samenvoegen/splitsen;
   acties bestaan in het review-model, de herberekening ervan nog niet
   (PARTIALLY IMPLEMENTED).
7. **Schaal >10.000** — patroon-detailpagina paginateert nu op 40 leden;
   clustering is O(n²) afgekapt op 50 leden; voor >10k projecten
   waarschijnlijk pairwise-approximatie nodig (NOT IMPLEMENTED).
8. **ML/embedding-laag** — pas als de deterministische features zijn
   gekalibreerd op grote echte data (V3-§32) (NOT IMPLEMENTED, bewust).
9. **Automatische tune-generatie v3** — verboden volgens V3-§21; de
   bevroren V2.7-kandidaatstroom blijft de enige output-route en wordt pas
   heropend na technician-validatie op echte schaal (UNKNOWN/tijdsbeslissing).

## Bekende grenzen (eerlijk)

- Pattern confidence-formules zijn ontworpen en gedocumenteerd, maar niet
  statistisch gekalibreerd op echte tunerdata.
- Mapdetection is een begrensde schat scanning: ver buiten 1 MiB of fijnere
  structuren worden niet gevonden; endianness alleen als waarneming.
- De V2.7-kandidaatstroom corrigeert geen checksums en is nooit ECU-klaar.
- OLS-mapinhoud (assen/factoren/units) blijft ongedecodeerd tot het formaat
  het bewijst.
