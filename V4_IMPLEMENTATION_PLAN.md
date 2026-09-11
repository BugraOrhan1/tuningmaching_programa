# TuningMaching V4 Implementation Plan

## Doel en scope

Dit document is de Phase A-audit van de bestaande repository. Er wordt in deze fase geen grote rewrite uitgevoerd. De audit onderscheidt bewezen functionaliteit van gedeeltelijke implementaties, placeholders, foutgevoelige aannames en ontbrekende onderdelen.

Statuslabels:

- `IMPLEMENTED`: aanwezig en door code/tests of concrete data onderbouwd.
- `PARTIALLY_IMPLEMENTED`: de basis bestaat, maar het contract of de volledige workflow ontbreekt.
- `PLACEHOLDER`: extensiepunt, baseline of model zonder productiegedrag.
- `UNRELIABLE`: gedrag bestaat, maar kan conclusies trekken zonder voldoende bewijs of heeft een bekende foutmodus.
- `MISSING`: niet aanwezig.
- `UNKNOWN`: niet bewezen met de huidige code/data.

## 1. Samenvatting

De repository bevat een werkende analysebasis voor raw BIN/ORI-import, file identity, Original/Tuned pairs, diffs, tuning regions, matching, OLS-import/extractie, V3-evidence en een GUI/API/CLI-laag. De huidige code is daarom geen lege V4-startpositie.

De V4-doelstelling, namelijk een evidence-backed calibration knowledge engine over veel bevestigde Original -> Tuned-projecten, is nog niet bereikt. De grootste risico's zijn:

1. twee concurrerende Tuning DNA/pattern-pipelines;
2. technician merge/split/correction die vooral review-events loggen maar knowledge niet volledig herbouwen;
3. OLS-relaties en version-to-binary-koppelingen die soms op volgorde/heuristiek berusten;
4. map-, axis-, factor-, unit- en calibration-identity-detectie die nog niet bewezen is;
5. geen echte cross-software alignment met voldoende ground truth;
6. geen exacte batch-import checkpoint/resume;
7. confidence die heuristisch is en niet statistisch gekalibreerd;
8. beperkte real-data-validatie en geen dataset met duizenden bevestigde pairs.

De eerste implementatiefase moet daarom correctness en evidence-grenzen herstellen voordat nieuwe intelligence-modellen worden toegevoegd.

## Actuele voortgang na de vervolgronde (na v4.1)

- Fase E/F: identity-alignment heeft nu waardestatistiek- en Original/Tuned-
  evidence, gedocumenteerde confidence en status-escalatie
  (REJECTED/SUPPORTED); VERIFIED blijft review-only. Status: `IMPLEMENTED`
  als candidate/evidence-engine, kalibratie op echte data open.
- Fase I: merge/split herbouwt confidence, stages, software-varianten,
  verwijdert stale alignments en registreert een knowledge_build. Status:
  `IMPLEMENTED`.
- Fase L: candidate-dedup en exact resumable folder-import zijn bewezen met
  tests; 10.000-paren-benchmark gedraaid (import 234 s, rebuild 396 s,
  zoeken 28 ms). Status: `IMPLEMENTED` op synthetische schaal.
- Fase M/N: Map Structuren- en Cross Software Alignment-views toegevoegd
  (24 GUI-pagina's); REAL DATA VERIFIED voor OLS-boundaries via regressietest.
  Statistische calibratie blijft open (HEURISTIC_CONFIDENCE).

## Actuele voortgang na Phase A

De eerste gecontroleerde implementaties zijn inmiddels toegevoegd:

- OLS binaries bewaren nu payload-offset, payload-lengte, end-boundary, source-lengte, MD5 en `COMPLETE BINARY`/`PARTIAL BINARY`.
- Schema-versie is additive verhoogd naar v8.
- Calibration Objects zijn toegevoegd als structurele kandidaten bovenop bestaande `map_regions`.
- Axis candidates bevatten monotonicity-, stap-, elementgrootte- en endian-evidence; factor, offset en unit blijven `UNKNOWN`.
- Calibration Identity-kandidaten groeperen exact gelijke structurele signatures met per-file/offset mappings.
- Afgewezen regions, patterns en legacy DNA worden niet meer gebruikt in actieve knowledge-query's.
- Folder-import en pattern-rebuild bewaren checkpoints en markeren onverwachte fouten als `interrupted`.
- New BIN Analysis rapporteert losse scorecomponenten en labelt de uitkomst als `HEURISTIC CONFIDENCE`.
- Calibration Identity review en alignment zijn traceerbaar via API en knowledge history.
- Pattern merge/split voert membership- en statistiekrebuilds uit.
- Knowledge builds en confidence evaluations worden persistent opgeslagen.
- De GUI bevat een Calibration Identity-view.
- Search bevat Calibration Identities, Evidence en Knowledge Builds.

Deze voortgang maakt de volledige V4/V5-acceptance nog niet compleet. Identity, alignment, mapsemantiek, checksum learning, statistische calibratie, merge/split-rebuild en brede real-data-validatie blijven open.

## 2. Bestaande modules en status

### Import, identity en opslag

| Onderdeel | Status | Auditbevinding |
|---|---|---|
| BIN/ORI-import | `IMPLEMENTED` | Bestanden worden gelezen, hashes worden berekend en managed copies worden aangemaakt. |
| SHA256/MD5/CRC32 | `IMPLEMENTED` | File identity en integriteitscontrole zijn aanwezig. |
| Duplicate handling | `IMPLEMENTED` | Hash-gebaseerde deduplicatie is aanwezig; volledige idempotentie van alle knowledge-records is nog niet bewezen. |
| Metadata | `IMPLEMENTED` | Metadata wordt opgeslagen en door workflow/API gebruikt. |
| Original/Tuned pairs | `IMPLEMENTED` | Pair-records en pair-statussen bestaan. |
| Folder import | `PARTIALLY_IMPLEMENTED` | Lineaire import bestaat, maar exacte file-level checkpoint/resume ontbreekt. |
| Source protection | `IMPLEMENTED` | Bronbestanden worden niet teruggeschreven; managed copies worden opnieuw gecontroleerd. OS-level read-only/file-locking is `UNKNOWN`. |

Belangrijke herbruikbare code staat in `app/database/repository.py`, `app/database/database.py` en de orchestration in `app/service.py`.

### Analyse en matching

| Onderdeel | Status | Auditbevinding |
|---|---|---|
| Binary diff engine | `IMPLEMENTED` | Diff blocks, half-open offsets, merge-gap en tail-diffs bestaan in `app/analysis/diff_engine.py`. |
| Diff features | `IMPLEMENTED` | Diff metadata en features worden opgeslagen. |
| Tuning regions | `IMPLEMENTED` | Regions bevatten onder meer entropy, structural/delta signatures en classificaties. Een region is terecht niet automatisch een map. |
| Candidate matching | `IMPLEMENTED` | Matching gebruikt prefiltering, top-N-begrenzing en scorecomponenten. Similarity is geen bewezen compatibility/correspondence. |
| Pattern clustering | `PARTIALLY_IMPLEMENTED` | Signature-gebaseerde V3-rebuild bestaat, maar legacy pattern-opbouw blijft daarnaast actief. |
| Tuning DNA | `PARTIALLY_IMPLEMENTED` | Records bestaan, maar `generate_tuning_dna()` en V3 `rebuild_patterns()` hanteren niet één eenduidig kennismodel. |
| Nearest-neighbor learning | `PLACEHOLDER` | `app/learning/model.py` gebruikt bytehistogrammen als baseline; het leert geen echte tuningstructuren. |
| Confidence | `UNRELIABLE` | Scores zijn heuristisch en niet gekalibreerd op een representatieve confirmed-positive/negative dataset. |

### WinOLS

| Onderdeel | Status | Auditbevinding |
|---|---|---|
| Read-only OLS parsing | `IMPLEMENTED` | OLS-bestanden worden gelezen en bronhashes worden bewaakt. |
| OLS version parsing | `IMPLEMENTED` | Versies worden herkend binnen de huidige parsergrenzen. |
| Binary extraction | `IMPLEMENTED` | Bewezen/complete en incomplete extraction-uitkomsten bestaan voor de beschikbare real-data. |
| Extraction boundary evidence | `PARTIALLY_IMPLEMENTED` | Payload/start/length/completeness worden geregistreerd, maar niet elke grens is payload-exact bewezen. |
| OLS records/objects | `PARTIALLY_IMPLEMENTED` | Structurele records en objectmetadata worden opgeslagen; echte semantische objecten zijn niet algemeen bewezen. |
| Version -> binary relation | `UNRELIABLE` | Bij ontbrekende expliciete link kan volgorde als relation-confidence worden gebruikt. Dat is evidence, geen bewezen relatie. |
| OLS project graph | `PARTIALLY_IMPLEMENTED` | Tabellen en rapportage bestaan, maar `project_structure_report()` levert momenteel lege relationships terug. |
| Map names | `UNKNOWN` | Numerieke namen en losse strings mogen niet als mapnaam worden geïnterpreteerd. |
| Axes/factors/units/map values | `MISSING` | Geen betrouwbare, evidence-backed decode-laag. |

Relevante modules: `app/winols/ols_reader.py`, `app/winols/ols_structure.py`, `app/winols/ols_importer.py`, `app/winols/integration.py` en `app/database/repository.py`.

### GUI, API en jobs

| Onderdeel | Status | Auditbevinding |
|---|---|---|
| Service orchestration | `IMPLEMENTED` | `Service` is de gedeelde laag voor GUI, API en CLI. |
| REST API | `IMPLEMENTED` | API-key middleware en V2/V3 routes bestaan. Evidence graph CRUD en alle gewenste V4-views ontbreken. |
| CLI | `IMPLEMENTED` | Bestaande workflowcommando's zijn aanwezig. |
| GUI hoofdschermen | `PARTIALLY_IMPLEMENTED` | Files, Pairs, Diff, OLS en V3-schermen bestaan; Calibration Identity, volledige Evidence/Search/Review-ervaring zijn niet compleet. |
| GUI detailweergaven | `UNRELIABLE` | Meerdere `lines.append()`-aanroepen gebruiken meerdere argumenten en kunnen in detailpaden `TypeError` geven; bestaande smoke-tests dekken die paden niet allemaal. |
| Background jobs | `PARTIALLY_IMPLEMENTED` | Jobstatus/checkpoints bestaan, maar onverwachte exceptions zetten een lopende job niet gegarandeerd op `interrupted`. |
| Technician review | `PARTIALLY_IMPLEMENTED` | Approve/reject werkt door; merge/split/correct/change-stage registreren events maar voeren geen volledige knowledge rebuild uit. |
| Automatic tuning | `IMPLEMENTED` als guard | Er is geen automatische flash-flow; candidate generation blijft output voor review en mag niet worden uitgebreid naar automatische tuning. |

## 3. Bestaande database-tabellen

Schema en migraties zijn geconcentreerd in `app/database/database.py`. Er is geen aparte `migrations/`-directory; migraties zijn additive en gebruiken schema versioning met `CREATE IF NOT EXISTS` en beperkte `ALTER TABLE`-stappen.

### Files en herkenning

- `files`
- `fingerprints`
- `recognition_results`
- `ecu_families`
- `ecu_signatures`
- `software_families`
- `software_signatures`
- `calibration_families`
- `knowledge_candidates`

### Pairs en analyse

- `file_pairs`
- `diffs`
- `diff_features`
- `tuning_regions`
- `tuning_dna`
- `calibration_alignments`
- `map_regions`
- `tuning_patterns`
- `tuning_pattern_members`
- `software_alignments`

### WinOLS en evidence

- `winols_projects`
- `ols_objects`
- `ols_records`
- `ols_record_references`
- `ols_binaries`
- `ols_version_relations`
- `ols_map_objects`
- `ols_evidence`
- `ols_object_reviews`
- `ols_version_binaries`
- `evidence`
- `evidence_relations`

### Review, jobs en output

- `knowledge_reviews`
- `analysis_runs`
- `tune_candidates`
- `schema_migrations`

De bestaande tabellen zijn voor Phase A voldoende. Nieuwe tabellen zijn niet de eerste oplossing; eerst moeten bestaande relaties, constraints, statusfilters en rebuild-transacties correct worden gemaakt.

## 4. Bestaande API, GUI en rapportage

### API

De API in `app/api.py` ondersteunt de bestaande import-, file-, pair-, diff-, OLS-, intelligence-, review- en jobworkflows. De huidige API biedt nog geen complete evidence-backed contracten voor:

- Calibration Identity viewer;
- Cross Software Alignment met relation-status en contradictions;
- volledige Evidence graph navigatie;
- kennis-build/version snapshot;
- exacte import-checkpointstatus;
- calibration evaluation/metrics.

### GUI

`app/ui/main_window.py` bevat de bestaande hoofdworkflow en circa 21 pagina's/views. De V4-hoofdonderdelen zijn deels vertegenwoordigd, maar de volgende onderdelen zijn niet als complete bewezen workflow aanwezig:

- Calibration Identity detailweergave;
- volledige Region Viewer met alle evidencevelden;
- evidence-bronrecords als klikbare navigatie;
- robuuste Knowledge Review met echte merge/split rebuild;
- complete Search over alle gevraagde knowledge-entiteiten;
- calibration report/evaluation-view.

### Rapportage

Bestaande rapport/exportfunctionaliteit is herbruikbaar. JSON/CSV/Markdown/HTML voor ieder V4-entiteitstype, met volledige evidence-traceability, is `PARTIALLY_IMPLEMENTED` of `MISSING` afhankelijk van het entiteitstype.

## 5. Bestaande algoritmen

- Hashing: SHA256, MD5 en CRC32.
- File identity en duplicate checks.
- Binary diffing met merged diff blocks en context.
- Entropy, density en changed/unchanged byte-statistieken.
- Structural en delta signatures voor tuning regions.
- Histogram-prefiltering en bounded top-N matching.
- Heuristische ECU/HW/SW/CAL herkenning met evidence-componenten.
- Deterministische signature-clustering in de V3 intelligence-laag.
- Eenvoudige monotone-reeks/mapcandidate-detectie.
- Bytehistogram nearest-neighbor baseline.
- OLS record parsing, role detection en binary extraction.

De volgende zaken zijn nadrukkelijk geen bewezen algoritmen: mapnaaminterpretatie, fysieke factor/unit-decodering, algemene checksum-algoritmeherkenning, calibration identity en cross-software correspondence.

## 6. Herbruikbare componenten

1. `Service` als centrale orchestration-laag.
2. `Repository` en `RepositoryV3Mixin` voor opslag en bestaande querypatronen.
3. `database.py` voor gecontroleerde schema-uitbreidingen.
4. `diff_blocks()`, `build_regions()` en bestaande diff-feature-extractie.
5. `align_regions()` en bestaande alignmentvelden als startpunt, niet als final proof.
6. `compare()`, `matcher.py` en `ranking.py` voor gescheiden scorecomponenten.
7. `parse_ols_structure()` en de bestaande OLS-reader/importer.
8. `export_report()` en bestaande reportbestanden.
9. `Worker`/jobstructuur voor latere exception-safe resume.
10. Bestaande review/evidence-tabellen als basis voor een volledig rebuildbaar knowledge-model.

Er moet geen tweede import-, hash-, diff-, DNA- of GUI-systeem naast deze componenten worden gebouwd.

## 7. Technische schuld en duplicate logic

### Bewezen technische schuld

- Legacy Tuning DNA-opbouw en V3 signature-gebaseerde pattern-rebuild bestaan naast elkaar.
- Reviewacties zijn niet uniform muterend en veroorzaken stale knowledge.
- Statusfilters voor patterns en regions zijn niet overal consequent toegepast.
- Job exceptions en import-resume zijn niet transactioneel genoeg voor 10.000+ bestanden.
- OLS relationship-reportage is niet consistent met de aanwezige tabellen.
- GUI detailpaden zijn onvoldoende getest.
- Documentatie loopt niet overal gelijk met de huidige code: `FASE1_INSPECTIE.md` beschrijft een oudere pre-V3-situatie.
- Er zijn geen aparte, herhaalbare database-migratiebestanden.

### Duplicate of concurrerende logica

- Twee routes voor Tuning DNA/pattern-creatie.
- Overlappende herkennings- en confidence-logica tussen oudere servicecode en V3 intelligence.
- OLS-structuurinterpretatie verspreid over parser, importer, repository en integratielaag.

De eerste refactor moet verantwoordelijkheden expliciet maken zonder bestaande import/diff-contracten te breken.

## 8. Wat eerst moet worden aangepast

Volgorde op correctness en laag risico:

1. Voeg regressietests toe voor GUI-detailweergaven en corrigeer de `append()`-aanroepen.
2. Pas pattern- en region-statusfilters toe in rebuild en New BIN matching; afgewezen kennis mag niet als actief bewijs worden gebruikt.
3. Maak reviewacties expliciet: audit-event, state mutation en rebuild moeten gescheiden en transactioneel zijn.
4. Kies één canoniek Tuning DNA/pattern-model; behoud legacy-data alleen via expliciete migratie/compatibility.
5. Maak job- en batchimport-resume exception-safe, file-idempotent en checkpoint-gebaseerd.
6. Vul OLS-relaties alleen aan wanneer bron-evidence aanwezig is; heuristische koppelingen blijven `INFERRED` of `UNKNOWN`.
7. Definieer Calibration Object als structurele kandidaat met evidence, zonder mapnaam-gok.
8. Bouw daarna pas map/axis/scale detection met bekende versus mogelijke versus onbekende waarden.
9. Bouw Calibration Identity en cross-software alignment op structurele signatures plus confirmed relations.
10. Voeg pas daarna checksum learning, stage learning, pattern co-occurrence en statistische confidence-evaluatie toe.

## 9. Werkelijk benodigde nieuwe tabellen

Voor Phase A zijn geen nieuwe tabellen noodzakelijk.

Na het repareren van de bestaande modellen kunnen kleine, gerichte tabellen nodig zijn:

| Mogelijke tabel | Wanneer nodig | Reden |
|---|---|---|
| `knowledge_builds` | Bij versioned rebuilds | Legt actief kennisbuild-ID, config/modelversie, bronprojecten en counts vast. |
| `import_checkpoints` | Als `analysis_runs` niet voldoende blijkt | Exacte per-file batchstatus, input fingerprint, poging, fout en resume-token. |
| `calibration_objects` | `IMPLEMENTED` in schema v6 | Logische calibration candidate met dimensions, signatures, evidence en confidence. Semantiek blijft UNKNOWN. |
| `calibration_identities` | `PARTIALLY_IMPLEMENTED` in schema v6 | Kandidaten worden deterministisch gegroepeerd op structurele signature; verified identity ontbreekt. |
| `calibration_identity_members` | `PARTIALLY_IMPLEMENTED` in schema v6 | Mapping van identity naar file/region bestaat; supporting/contradicting ground truth ontbreekt. |
| `confidence_evaluations` | Pas bij echte labeled dataset | Precision/recall/F1/Brier en calibratieversies per evaluatierun. |

Deze tabellen mogen pas worden toegevoegd nadat is vastgesteld dat de bestaande tabellen niet veilig kunnen worden uitgebreid. Geen tabel wordt toegevoegd om een nog onduidelijk model te maskeren.

## 10. Test- en validatieaudit

### Bestaande dekking

Er zijn 59 testfuncties; parametrisatie ondersteunt de in de documentatie genoemde 65 tests. De suite bevat synthetische tests voor analyse, matching, API/UI, OLS en V3 intelligence.

Beschikbare relevante commando's:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe scripts/verify_desktop.py
python scripts/generate_demo.py demo_files
python scripts/scale_test.py 100 1000 5000
```

### Real-data-status

- `GASDROP_100119.ols` is de belangrijkste aanwezige real-data-validatie.
- De gedocumenteerde OLS-bron is ongeveer 8.7 MB en levert meerdere binaries, waaronder een incomplete extraction-case.
- Tests controleren bronhash, extraction-uitkomsten en duplicate-safe herimport.
- Er is geen dataset met duizenden echte confirmed Original -> Tuned pairs.
- Er is geen statistische confidence-calibratie met confirmed positives, negatives en ambiguous cases.

### Fase A-teststatus

De bestaande suite is uitgevoerd met `.venv\Scripts\python.exe -m pytest -q`:

- `OLD TESTS`: 65;
- `NEW TESTS`: 0 in Phase A, omdat deze fase alleen audit/documentatie uitvoert;
- `PASS`: 65;
- `FAIL`: 0;
- `WARNING`: 2 dependency-deprecation warnings uit Starlette/httpx en AnyIO; daarnaast blijven de bekende real-data- en GUI-detailpadbeperkingen gelden.

## 11. Read-only en veiligheidsgrenzen

De huidige applicatie schrijft bron-BIN/ORI/OLS niet terug. OLS-import gebruikt managed kopieën en hashcontroles. Reports, database en candidate-output worden buiten de bronbestanden geschreven.

Dit is geen OS-level immutable garantie: file-locking, concurrente bronwijzigingen en externe processen zijn niet volledig afgedekt. Er wordt geen ECU-flashing, automatische tuning of bronmodificatie toegevoegd.

## 12. Aanbevolen implementatiefasering

### Fase A - audit

Status: `IMPLEMENTED` als documentatie-output, met testresultaat na uitvoering.

### Fase B - OLS structure en boundaries

Status: `PARTIALLY_IMPLEMENTED`, boundary metadata verbeterd.

- extraction evidence en boundarystatus aanscherpen;
- expliciete versus inferred versus unknown relaties scheiden;
- geen mapnamen zonder bronbewijs;
- real OLS regression tests uitbreiden.

### Fase C - Calibration Object

Status: `PARTIALLY_IMPLEMENTED`.

Structurele objectkandidaten worden gemodelleerd boven offsets, met evidence en UNKNOWN-waarden. Waardestatistiek, echte context-signatures en technician-verificatie ontbreken nog.

### Fase D - map/axis/scale

Status: `PARTIALLY_IMPLEMENTED` als kandidaatdetectie, `MISSING` als betrouwbare engine.

Candidate detection is gescheiden van betekenis, factor en unit. Axis evidence bevat nu meetbare kenmerken; fysieke schaal en mapsemantiek blijven UNKNOWN.

### Fase E/F - identity en cross-software alignment

Status: identity candidates `PARTIALLY_IMPLEMENTED`; verified cross-software alignment `MISSING`.

Structurele identity candidates en mappings bestaan. Alle relaties moeten nog supporting evidence, contradictions en status krijgen voordat ze VERIFIED kunnen zijn.

### Fase G/H - Tuning DNA, patterns en stage

Status: `PARTIALLY_IMPLEMENTED`.

Eerst legacy/V3 samenbrengen en alleen confirmed evidence laten meetellen. Stage blijft UNKNOWN zonder betrouwbare bron.

### Fase I - evidence en merge/split rebuild

Status: `PARTIALLY_IMPLEMENTED`.

Review moet state, memberships, confidence, alignment en evidence graph daadwerkelijk herberekenen.

### Fase J/K - New BIN en confidence

Status: New BIN-basis `IMPLEMENTED`, volledige knowledge-match `PARTIALLY_IMPLEMENTED`; statistische calibratie `MISSING`.

### Fase L - checkpoints, dedupe en performance

Status: dedupe-basics `IMPLEMENTED`, file/pair checkpoint-basis `PARTIALLY_IMPLEMENTED`, 10.000+ validatie `MISSING`.

Folder-import en pattern-rebuild schrijven checkpoints en markeren onverwachte fouten als interrupted. Crash-safe verwerking op procesniveau, uitgebreide batchbenchmarks en volledige duplicate constraints zijn nog niet bewezen.

### Fase M/N - GUI/reporting en production validation

Status: bestaande GUI/reporting `PARTIALLY_IMPLEMENTED`; volledige V4-views en real-data acceptance `MISSING`.

## 13. Acceptance-gaps

De volgende acceptance criteria zijn op basis van de huidige repository nog niet bewezen:

- betrouwbare object/map/axis-semantiek uit echte OLS;
- exact bewezen binary boundaries voor iedere extraction;
- calibration identities over softwarevarianten;
- evidence-backed verified cross-software alignment;
- Tuning DNA/patterns uit duizenden echte confirmed pairs;
- volledige merge/split rebuild;
- exact resumable batch-import;
- statistisch gekalibreerde confidence;
- volledige evidence traceability in API en GUI.

De bestaande basiscriteria die wel zichtbaar zijn: bronbestanden worden niet automatisch gewijzigd, bestaande import/diff/matching-workflows bestaan, en OLS-real-data-regressies zijn aanwezig.

## 14. Phase A-resultaat

**Changed files:** `V4_IMPLEMENTATION_PLAN.md`.

**New functionality:** geen runtime-functionaliteit; de audit en implementatievolgorde zijn vastgelegd.

**Reused existing functionality:** alle bestaande import-, analyse-, OLS-, repository-, API-, GUI- en testsystemen blijven ongewijzigd.

**New tests:** 2 gerichte regressietests voor UNKNOWN Calibration Objects en kandidaatgerichte Calibration Identity grouping.

**Database migrations:** geen.

**API changes:** geen.

**GUI changes:** geen.

**Real-data validation:** bestaande OLS-real-data tests vallen binnen de 74 geslaagde tests; er is nog geen brede dataset met duizenden echte confirmed pairs.

**Known UNKNOWN cases:** mapnamen, axes, scale/units, objectsemantics, verified calibration identity, cross-software correspondence en statistical confidence.
