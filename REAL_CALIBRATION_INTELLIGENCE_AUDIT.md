# Real Calibration Intelligence Audit

## Scope

Deze audit is Phase 1 van de opdracht `REAL CALIBRATION INTELLIGENCE`. Er is in deze audit geen nieuwe architectuur toegevoegd en geen bestaande runtime-code herschreven. De audit beschrijft de actuele repositorytoestand, inclusief de reeds aanwezige V3/V4-uitbreidingen.

Statuslabels:

- `IMPLEMENTED`: aanwezig en door code, tests of concrete data onderbouwd.
- `PARTIAL`: de basis bestaat, maar het volledige contract ontbreekt.
- `UNRELIABLE`: het gedrag bestaat, maar de conclusie kan zonder voldoende bewijs fout zijn.
- `MISSING`: niet aanwezig.
- `UNKNOWN`: niet bewezen met de huidige code/data.

## Executive summary

De applicatie is geen eenvoudige BIN-similarity finder meer. De repository bevat een substantiële analysebasis voor file identity, Original/Tuned pairs, diffs, TuningRegions, Tuning DNA, pattern clustering, OLS-import/extractie, evidence, matching, New BIN Analysis, API, GUI en background jobs.

De belangrijkste beperking blijft echter bestaan: de huidige Calibration Object- en Calibration Identity-lagen zijn structurele kandidaten. Identity review en context-alignment zijn toegevoegd, maar zij bewijzen nog niet dat twee gebieden in verschillende softwarevarianten dezelfde functionele calibration representeren.

De huidige betrouwbare grens is:

> Het systeem kan structurele overeenkomsten, candidate regions en kandidaat-identities opslaan met evidence en confidence. Het mag nog niet claimen dat zo'n kandidaat dezelfde ECU-calibrationfunctie is.

Belangrijkste resterende risico's:

1. OLS map/object-semantiek, factoren, units en waarden zijn niet betrouwbaar gedecodeerd.
2. Map/axis-detection is heuristisch en kan monotone of periodieke data als kandidaat markeren.
3. Cross-software alignment bewijst structurele correspondentie, geen functionele calibration identity.
4. Calibration Identity groepeert momenteel vooral gelijke structurele signatures.
5. Tuning DNA legacy en V3 gebruiken nog concurrerende routes en dezelfde pattern-tabel.
6. Merge/split/correct review herbouwt knowledge nog niet volledig.
7. Confidence is heuristisch, niet statistisch gekalibreerd.
8. Real-data-validatie bestaat hoofdzakelijk uit één echte OLS; echte confirmed Original/Tuned calibration pairs ontbreken als brede dataset.

## 1. Huidige code en status

### File import, identity en database

| Onderdeel | Status | Feitelijke toestand |
|---|---|---|
| BIN/ORI-import | `IMPLEMENTED` | `app/database/repository.py` leest raw files, berekent hashes en maakt managed copies. |
| Hashes | `IMPLEMENTED` | SHA256, MD5 en CRC32 worden opgeslagen. |
| File deduplication | `IMPLEMENTED` | Import is idempotent op bron/hash/type binnen de bestaande constraints. |
| Pair deduplication | `IMPLEMENTED` | `file_pairs` heeft een unieke Original/Tuned-combinatie. |
| Metadata | `IMPLEMENTED` | ECU, hardware, software, calibration, vehicle, stage en projectmetadata bestaan. |
| Folder import | `PARTIAL` | Gesorteerde paths, checkpoints en resume bestaan; wijzigingen in de folder tijdens resume worden niet fingerprint-gevalideerd. |
| Tune candidate deduplication | `PARTIAL` | Regeneration van actieve candidates wordt in code hergebruikt op target/hash/pair, maar de tabel heeft geen volledige unieke identity met strategy/knowledge build. |
| Source protection | `IMPLEMENTED` | Bron-BIN/ORI/OLS worden niet teruggeschreven; managed files worden hash-gecontroleerd. OS-level locking is `UNKNOWN`. |

Herbruikbaar: `Repository.import_file()`, `Repository.import_folder()`, `Repository.pair()`, `Database.connect()` en `Service` als orchestration-laag.

### Diff en TuningRegion

| Onderdeel | Status | Feitelijke toestand |
|---|---|---|
| Diff engine | `IMPLEMENTED` | Half-open offsets, merged blocks, changed byte counts en context bestaan. |
| Persisted diff data | `IMPLEMENTED` | `diffs` en `diff_features` slaan analysevelden op. |
| TuningRegion | `IMPLEMENTED` | Entropy, context hashes, structural/delta signatures, region class, map confidence, evidence en status bestaan. |
| Region versus map | `IMPLEMENTED` als veiligheidsgrens | Een diff region wordt niet automatisch als map gepresenteerd. |
| Checksum filtering | `PARTIAL` | Cross-pair heuristische candidate-markering bestaat; checksum-algoritme of dependency is niet bewezen. |
| Value-level delta | `MISSING` voor betrouwbare calibrations | Raw byte changes bestaan; row/column, physical values en bewezen value deltas ontbreken. |

Herbruikbaar: `app/analysis/diff_engine.py`, `app/analysis/tuning_region.py`, `build_regions()`, `structure_features()`, `delta_signature()`, `signature_similarity()`.

### Tuning DNA en patterns

| Onderdeel | Status | Feitelijke toestand |
|---|---|---|
| Legacy Tuning DNA | `PARTIAL` | `Service.generate_tuning_dna()` maakt traceable candidate records uit confirmed pairs. |
| V3 Tuning DNA | `PARTIAL` | Regions, structural signatures en V3 pattern rebuild bestaan. |
| Pattern clustering | `PARTIAL` | Deterministische clustering bestaat, maar legacy en V3 delen dezelfde knowledge-oppervlakte en zijn niet volledig geconsolideerd. |
| Stage learning | `PARTIAL` | Metadata/stage wordt meegenomen wanneer aanwezig; automatische stage inference zonder bronbewijs ontbreekt terecht. |
| Pattern evidence | `PARTIAL` | Payloads bevatten projecten, softwarevarianten en contradictions; generieke evidence graph-integratie is niet volledig. |
| Tuning DNA -> Calibration Object -> Identity | `MISSING` als complete keten | De afzonderlijke lagen bestaan, maar de koppeling wordt nog niet volledig persistenter en door New BIN gebruikt. |

Herbruikbaar: `Service.generate_tuning_dna()`, `ServiceV3Mixin.rebuild_patterns()`, `patterns_v3()`, `replace_pattern_members()`, `align_pattern_across_software()`.

### OLS parser, records en extraction

| Onderdeel | Status | Feitelijke toestand |
|---|---|---|
| Read-only OLS inspection | `IMPLEMENTED` | `ols_reader.py` leest bytes, zichtbare records en metadata zonder bronwijziging. |
| Length-prefixed records | `IMPLEMENTED` binnen geobserveerde formatgrenzen | Records hebben offset, lengte, type, raw value, confidence en evidence. |
| OLS version labels | `IMPLEMENTED` binnen parsergrenzen | Expliciete Original/Tuned/Stage-labels worden herkend. |
| Embedded binary anchors | `IMPLEMENTED/PARTIAL` | Explicit import headers en repeating identity headers worden herkend. |
| Binary boundary metadata | `PARTIAL` | Payload/source offsets, lengths, end boundary, MD5, SHA256 en complete/partial status worden opgeslagen. Exacte payloadgrens is niet voor ieder opaque record bewezen. |
| Binary status | `PARTIAL` | Complete en incomplete extraction bestaan; algemene `AMBIGUOUS`/`NOT A BINARY`-classificatie is niet volledig uniform door de gehele pipeline. |
| Version -> binary relation | `PARTIAL/UNRELIABLE` | Explicit filename relation is sterk; order-inferred relation gebruikt evidence maar is geen bewezen proprietary link. |
| OLS object model | `PARTIAL` | Visible strings/records en database-objecten bestaan; echte WinOLS objectsemantiek, parent/child links en object boundaries zijn niet algemeen bewezen. |
| OLS project graph | `PARTIAL` | Project/version/binary nodes, unknown relations en relation edges bestaan; volledige proprietary graph ontbreekt. |
| OLS map objects | `UNRELIABLE` | `Kaart`-records leveren label-, adres-, dimensie- en factor-kandidaten; dit zijn geen bewezen mapdefinities. |
| Map names | `MISSING` als bewezen betekenis | Numerical/opaque names en losse strings blijven UNKNOWN. |
| Axes/factors/units/map values | `MISSING` als betrouwbare decode | Alleen candidate evidence; geen betrouwbare scale/unit/value decode. |

Herbruikbaar: `app/winols/ols_reader.py`, `app/winols/ols_structure.py`, `app/winols/ols_importer.py`, `Repository.import_project()`, `_store_ols_structure()`.

### Calibration Object

| Onderdeel | Status | Feitelijke toestand |
|---|---|---|
| Database model | `IMPLEMENTED` | `calibration_objects` bestaat in schema v6 met dimensions, element size, endian, axis/signatures, context, statistics, evidence en statusvelden. |
| Candidate generation | `PARTIAL` | `build_calibration_objects()` bouwt kandidaten bovenop bestaande `map_regions`. |
| Structural signature | `PARTIAL` | Signature wordt deterministisch berekend uit map type, dimensions, element size en criteria. |
| Axis evidence | `PARTIAL` | Monotonicity, step range/repetition, element size en endian candidate worden vastgelegd. |
| Data semantics | `MISSING` | Data type, signedness, factor, unit, physical values en mapfunctie blijven UNKNOWN. |
| Neighbor/context evidence | `MISSING/PARTIAL` | Velden bestaan, maar worden nog niet gevuld met betrouwbare binary-neighbor/context signatures. |
| Binary identity link | `PARTIAL` | File ID en map-region ID bestaan; een OLS-proven binary object identity ontbreekt. |

Belangrijk: een Calibration Object is momenteel een structurele candidate, niet automatisch een echte calibration map.

### Map, axis en scale analysis

| Onderdeel | Status | Feitelijke toestand |
|---|---|---|
| Scalar candidate | `MISSING` als expliciete betrouwbare detector | Geen bewezen scalar-semantiek. |
| 1D/axis candidate | `PARTIAL/UNRELIABLE` | Monotone byte- en 2-byte-sequences worden als candidates gevonden. |
| 2D/repeated table candidate | `PARTIAL/UNRELIABLE` | Periodieke gelijkheid wordt gebruikt als candidate-heuristic. |
| 3D/map cluster/interpolation | `MISSING` | Geen betrouwbare implementatie. |
| Axis relation | `MISSING` | Neighboring usage en map-to-axis relation zijn niet bewezen. |
| Scale/factor/unit | `MISSING` | Geen betrouwbare bron-backed decode; geen waarden mogen worden verzonnen. |

Herbruikbaar: `ServiceV3Mixin.detect_map_structures()`, `map_regions`, `calibration_objects`, `ols_map_objects` als evidence-opslag, niet als semantische waarheid.

### Calibration Identity

| Onderdeel | Status | Feitelijke toestand |
|---|---|---|
| Identity tables | `IMPLEMENTED` | `calibration_identities` en `calibration_identity_members` bestaan in schema v6. |
| Candidate grouping | `PARTIAL` | `build_calibration_identities()` groepeert dezelfde ECU-family en structural signature. |
| Software variants | `PARTIAL` | Softwarewaarden worden als variantlijst opgeslagen wanneer file metadata beschikbaar is. |
| Offset mapping | `PARTIAL` | Per object worden source start/end offsets opgeslagen. |
| Supporting evidence | `PARTIAL` | Structurele signature-match wordt als evidence opgeslagen. |
| Contradicting evidence | `MISSING` | Er is geen volledige negatieve-evidence/contradiction engine. |
| Identity status | `PARTIAL` | `CANDIDATE` bestaat; onafhankelijke statusovergangen naar SUPPORTED/VERIFIED/REJECTED/UNKNOWN zijn niet volledig uitgewerkt. |
| Functional calibration identity | `MISSING` | Geen bewijs dat gelijkheid in signature dezelfde calibrationfunctie betekent. |
| Scope-safe rebuild | `UNRELIABLE` | Een rebuild met een subset kan bestaande identities volledig verwijderen en alleen die subset opnieuw opbouwen. |

De identity engine mag daarom alleen kandidaatresultaten rapporteren. VERIFIED is nog niet gerechtvaardigd.

### Cross-software alignment

| Onderdeel | Status | Feitelijke toestand |
|---|---|---|
| Existing alignment | `IMPLEMENTED/PARTIAL` | `align_pattern_across_software()` gebruikt block-run alignment, context en structural similarity. |
| Absolute offset independence | `PARTIAL` | Offset is output van alignment, niet de enige input. |
| Dimensions/axis/layout scoring | `MISSING` | Geen complete score over alle gevraagde Calibration Object-features. |
| OLS-backed alignment | `MISSING` | OLS evidence wordt niet volledig als relation constraint gebruikt. |
| Positive evidence | `PARTIAL` | Supporting projects/signatures/context worden opgeslagen. |
| Negative evidence | `MISSING` | Contradictions worden beperkt berekend; robuuste rejection ontbreekt. |
| VERIFIED alignment | `MISSING` | Geen onafhankelijke ground truth of threshold policy die VERIFIED rechtvaardigt. |

Conclusie: alignment is analyse/evidence collection, geen betrouwbare calibration correspondence engine.

### New BIN Analysis, API en GUI

| Onderdeel | Status | Feitelijke toestand |
|---|---|---|
| New BIN report | `PARTIAL` | Identificatie, related projects, patterns, map candidates en scorecomponenten worden gerapporteerd. |
| Score separation | `IMPLEMENTED` | Binary, structural, ECU/HW/SW/CAL, pattern, alignment, evidence en contradictionvelden worden afzonderlijk gerapporteerd. |
| Confidence label | `IMPLEMENTED` | Rapport markeert confidence als `HEURISTIC CONFIDENCE`; statistical calibration ontbreekt. |
| Identity in New BIN workflow | `PARTIAL` | Calibration Objects worden gebouwd; identity candidates worden niet volledig in het report gematcht. |
| REST API | `PARTIAL` | Bestaande V1/V2/V3-routes plus map, Calibration Object, Calibration Identity review/alignment, patterns, OLS graph, jobs, confidence evaluation, knowledge builds en search bestaan. Complete evidence traversal ontbreekt. |
| GUI | `PARTIAL` | Files, pairs, diff, DNA, patterns, regions, New BIN, OLS Explorer, review, search, jobs en Calibration Identity-view bestaan. Calibration Object- en evidence drill-down ontbreken. |
| Technician review | `PARTIAL` | Identity-statusreview en pattern merge/split membership rebuild bestaan; volledige DNA/alignment/evidence-build rebuild blijft onvolledig. |

## 2. Bestaande database-tabellen

Schema en migratiecode staan in `app/database/database.py`. De actuele code gebruikt `SCHEMA_VERSION = 6`; oudere documentatie noemt nog schema versie 4.

### Core files en recognition

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
- `tuning_patterns`
- `tuning_pattern_members`
- `calibration_alignments`
- `software_alignments`
- `map_regions`
- `calibration_objects`
- `calibration_identities`
- `calibration_identity_members`

### OLS

- `winols_projects`
- `ols_objects`
- `ols_records`
- `ols_record_references`
- `ols_binaries`
- `ols_version_relations`
- `ols_version_binaries`
- `ols_map_objects`
- `ols_evidence`
- `ols_object_reviews`

### Evidence, review, jobs en output

- `evidence`
- `evidence_relations`
- `knowledge_reviews`
- `analysis_runs`
- `tune_candidates`
- `schema_migrations`

### Ontbrekende of nog benodigde tabellen

Voor deze audit-only fase worden geen nieuwe tabellen toegevoegd. Mogelijk later nodig, na modelvalidatie:

- `knowledge_builds` voor versioned knowledge snapshots;
- `confidence_evaluations` voor labeled evaluation/calibration metrics;
- eventueel een expliciete `calibration_alignment_evidence`-laag als bestaande evidence-relations onvoldoende blijken.

## 3. Huidige API

Bestaande relevante routes in `app/api.py`:

- files/import, file metadata en recognition;
- pairs, diffs, regions en region detail;
- `/patterns`, `/patterns/{id}`, rebuild, alignment en review;
- `/files/{id}/map-structures`;
- `/files/{id}/calibration-objects`;
- `/calibration-identities` en `/calibration-identities/rebuild`;
- `/files/{id}/new-bin-report`;
- OLS project import, structure, graph en review;
- `/search`;
- `/jobs`.

API-gaps:

- geen complete Calibration Identity detail/decision API;
- geen algemene evidence graph traversal/API;
- geen confidence evaluation/report API;
- geen knowledge build/version API;
- geen echte merge/split rebuild API;
- geen folder-import resume endpoint met checkpointselectie.

## 4. Huidige GUI

De bestaande GUI heeft onder meer:

- Files;
- Original/Tuned Pairs;
- Diff/Hex;
- ECU/Software/Calibration families;
- Knowledge Review;
- Clusters, Tuning DNA en Patterns;
- Region Viewer;
- New BIN Analysis;
- OLS Explorer en OLS review;
- Search;
- Jobs, learning en settings.

GUI-gaps:

- aparte Calibration Object viewer;
- aparte Calibration Identity viewer met software mappings;
- volledige cross-software alignment viewer;
- klikbare evidence graph-bronnen;
- volledige merge/split/rebuild feedback;
- calibrated confidence report.

## 5. Betrouwbare claims

De volgende claims zijn redelijk onderbouwd door code en tests:

- raw BIN/ORI import en hash-gebaseerde managed copies;
- bronintegriteit wordt gecontroleerd;
- Original/Tuned pairs kunnen expliciet worden bevestigd;
- diff blocks en TuningRegions worden reproduceerbaar opgebouwd;
- OLS wordt read-only geïnspecteerd;
- aanwezige GASDROP OLS levert reproduceerbare complete/incomplete extraction cases;
- expliciete OLS version labels kunnen role-evidence leveren;
- OLS boundary metadata wordt opgeslagen wanneer de parser een boundary vindt;
- structurele candidates kunnen worden opgeslagen met evidence/status;
- rejected regions/patterns worden uit actieve query's gefilterd;
- New BIN confidence wordt als heuristisch gemarkeerd;
- geen automatische ECU flashing of bronmodificatie bestaat.

## 6. Onbetrouwbare of niet bewezen claims

De applicatie mag momenteel niet claimen dat:

- een Calibration Object een echte ECU-map is;
- een `Kaart`-string een echte mapdefinitie is;
- een monotone reeks een axis is;
- een table candidate een specifieke calibrationfunctie is;
- een factor, offset of unit correct is zonder bronbewijs;
- twee softwaregebieden dezelfde functionele calibration zijn;
- een Calibration Identity VERIFIED is op basis van alleen signature similarity;
- alignment confidence een statistische probability is;
- een checksum candidate een bewezen checksumgebied is;
- een stage automatisch bewezen is zonder betrouwbare metadata/review;
- een pattern automatisch veilig overdraagbare tuning is.

## 7. Herbruikbare modules en functies

### Direct herbruikbaar

- `app/service.py`: centrale orchestration en bestaande contracts.
- `app/database/database.py`: additive SQLite-schema/migratiepatroon.
- `app/database/repository.py`: files, pairs, OLS import, extraction, folder checkpoints en dedupe.
- `app/database/knowledge_repo.py`: regions, patterns, alignments, evidence, reviews, runs en Calibration Object/Identity opslag.
- `app/analysis/diff_engine.py`: diff en context.
- `app/analysis/tuning_region.py`: region features, signatures, entropy en confidence.
- `app/analysis/alignment.py`: block-run alignment als feature, niet als proof.
- `app/winols/ols_reader.py`: read-only record inspection.
- `app/winols/ols_structure.py`: OLS-specific structural/extraction evidence.
- `app/winols/ols_importer.py`: OLS facade en conservative outputs.
- `app/intelligence.py`: pattern rebuild, map candidates, Calibration Objects, identity candidates, New BIN en OLS graph.
- `app/api.py` en `app/ui/main_window.py`: bestaande surfaces uitbreiden, niet dupliceren.

### Niet opnieuw bouwen

- file import/hash engine;
- diff engine;
- bestaande TuningRegion persistence;
- bestaande OLS extraction;
- bestaande review/audit-history tabellen;
- bestaande matching en scorecomponenten;
- bestaande API/GUI-pagina's.

## 8. Tests en real-data-status

### Huidige tests

De actuele suite bevat 67 tests en is in deze audit uitgevoerd met:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Resultaat:

```text
67 passed, 2 warnings
```

De warnings zijn dependency-deprecation warnings uit Starlette/httpx en AnyIO. Er zijn geen test failures.

### Nieuwe tests sinds de oorspronkelijke V3-status

De suite bevat inmiddels extra dekking voor:

- Calibration Object UNKNOWN-semantiek;
- structurele Calibration Identity grouping als `CANDIDATE`;
- OLS boundary metadata via bestaande OLS-tests;
- statusfilters voor rejected knowledge;
- checkpoint/resume gedrag;
- heuristische New BIN scorevelden;
- GUI-detailweergaven.

De door de opdracht genoemde `65/65` is daarom historische status. Actuele status is `67/67`.

### Real-data

`tests/test_ols_real.py` gebruikt de aanwezige `data/winols_projects/GASDROP_100119.ols` wanneer deze aanwezig is en controleert onder meer:

- onveranderde bronhash;
- meerdere records;
- vijf extracted binary rows;
- vier complete en één incomplete extraction;
- expliciete Original-relatie;
- order-inferred stage-relaties;
- duplicate-safe herimport;
- map/address candidates.

Classificatie:

- OLS extraction: `REAL DATA VERIFIED` binnen de geteste formatgrenzen.
- OLS map/object semantiek: `NOT VERIFIED`.
- Calibration Object: `SYNTHETIC VERIFIED` als candidate-model, `REAL DATA VERIFIED` niet bewezen.
- Calibration Identity: `SYNTHETIC VERIFIED` als signature grouping, functionele identity `NOT VERIFIED`.
- Cross-software calibration: `SYNTHETIC VERIFIED` als alignmentanalyse, functionele correspondence `NOT VERIFIED`.
- Confidence calibration: `NOT VERIFIED`.
- 1.000/5.000/10.000 performance: `NOT VERIFIED`.

## 9. Wat moet worden aangepast na Phase 1

De volgende volgorde is aanbevolen, zonder bestaande pipelines opnieuw te bouwen:

1. OLS boundary regression uitbreiden met expliciete `COMPLETE`, `PARTIAL`, `AMBIGUOUS`, `UNKNOWN` states en echte padding/terminator cases.
2. OLS records/object-relations verder scheiden in proven, inferred en unknown; geen string-based object claims.
3. Calibration Object vullen met echte context-, neighbor-, value-statistics- en layout-evidence waar aantoonbaar.
4. Map/axis engine uitbreiden met deterministische falsification tests, niet alleen candidate-positive tests.
5. Identity rebuild scope-safe maken en supporting/contradicting evidence modelleren.
6. Cross-software alignment laten combineren met dimensions, axis, context, neighbor, OLS en confirmed-pair evidence; false positives moeten REJECTED/UNKNOWN kunnen worden.
7. Tuning DNA expliciet koppelen aan Calibration Object/Identity zonder de legacy/V3-modellen te dupliceren.
8. Checksum learning pas activeren met meerdere confirmed pairs en exclusion-tests.
9. Merge/split/correct laten leiden tot een transactionele knowledge rebuild met traceerbare knowledge build.
10. Daarna confidence evaluation bouwen met labeled positives, negatives en ambiguous cases.
11. Pas daarna GUI/reporting uitbreiden met Calibration Identity, Evidence en build/version views.

## 10. Phase 1-resultaat

- `REAL_CALIBRATION_INTELLIGENCE_AUDIT.md`: aangemaakt.
- Runtime-code gewijzigd in deze audit: nee.
- Database-migratie uitgevoerd in deze audit: nee.
- API uitgebreid na de audit met identity review/alignment, confidence evaluation en knowledge-build routes.
- GUI uitgebreid na de audit met Calibration Identity-view.
- Nieuwe tests toegevoegd voor identity review/alignment, DNA-linking, confidence, merge/rebuild, New BIN identity-flow en knowledge search.
- Schema uitgebreid naar versie 8 met knowledge builds, confidence evaluations en checksum status.
- Finale regressierun: `74 passed, 2 warnings`.
- Performance: 1.000 synthetische paren gemeten (`43.68s` import, `25.94s` rebuild, `0.008s` search); 5.000+ is `NOT VERIFIED` door de huidige per-record SQLite-workload.
- Functionele identity en verified cross-software correspondence blijven `NOT VERIFIED`.
