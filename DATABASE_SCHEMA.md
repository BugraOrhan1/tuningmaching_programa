# DATABASE_SCHEMA.md

SQLite, `PRAGMA user_version = 4`. Schema is additief en idempotent
(`CREATE IF NOT EXISTS` + gerichte `ALTER TABLE`-kolomvulling bij oudere
databases; migratiehistorie in `schema_migrations`). Locatie: `data/database.sqlite`.

## V2-kern (onveranderd)

| Tabel | Doel | Belangrijkste velden/beperkingen |
|---|---|---|
| `files` | alle bekende BIN/ORI/OLS-binaries | UNIQUE(source_path, sha256, file_type); ECU/HW/SW/CAL/vehicle/stage/project-metadata; indexen op sha256 en (file_type,size) |
| `file_pairs` | Original→Tuned-paren | UNIQUE-paar, `confirmed`-vlag |
| `fingerprints` | block-hashes + bytehistogram per file | 1:1 met files |
| `diffs` / `diff_features` | diff-regio's + JSON-features | per pair vernieuwd bij diff() |
| `winols_projects` | OLS-projecten | UNIQUE(source_path, sha256) |
| `ols_objects` / `ols_records` / `ols_record_references` / `ols_binaries` / `ols_version_relations` / `ols_map_objects` / `ols_evidence` / `ols_object_reviews` / `ols_version_binaries` | OLS-inventaris met evidence en confidence; numerieke namen blijven `unknown` | CASCADE op project |
| `ecu_families`+`ecu_signatures`, `software_families`+`software_signatures`, `calibration_families` | families + signatures | reviewable |
| `recognition_results` | identificatiehistorie | index (file, created_at) |
| `knowledge_candidates` | V2-kennisvoorstellen | status candidate/approved/rejected |
| `calibration_alignments` | V2-blok-run-aligneringen |Bron van de V3-evidence-uitbreiding |
| `tune_candidates` | bevroren V2.7-kandidaatstroom | output onder reports/candidates |

## V3-tabellen (schema v4, additief)

### tuning_regions
Één rij per gewijzigde regio van een paar. Kolommen: `pair_id` (FK, CASCADE),
`seq`, `start_offset`/`end_offset`/`length`, `changed_byte_count`,
`changed_percentage`, `original_bytes_hash`/`tuned_bytes_hash`,
`before_context`/`after_context` (hex, 32 B),
`original_context_hash`/`original_region_context_hash`/`tuned_context_hash`,
`relative_start`/`relative_end`, `structural_signature`/`delta_signature`,
`structure_features` (JSON), `entropy_before`/`entropy_after`, `region_class`,
`cross_pair_shared`, `alignment_confidence`, `map_confidence`/`map_type`,
`stage`, `ecu_family`, `software_number`, `calibration_number`,
`hardware_number`, `project`, `evidence` (JSON), `confidence`, `status`.
UNIQUE(pair_id, start_offset, end_offset). Indexen: pair, signature,
(class,status).

### tuning_pattern_members
Koppeltabel patroon↔regio: `pattern_id`, `region_id`, `pair_id`, `similarity`.
UNIQUE(pattern_id, region_id); CASCADE beide kanten.

### software_alignments
Cross-software-mapping per patroon: `pattern_id`, `source/target_file_id`,
`source/target_software`, `source/target_start`/`end` (target NULL = niet
gemapt), `structural_similarity`, `alignment_confidence`, `evidence_count`,
`supporting_projects`, `supporting_signatures`, `contradicting_evidence`,
`method`, `evidence` (JSON), `status` (`candidate`/`unknown`).

### map_regions
Structuurkandidaten per bestand: `file_id`, `start/end_offset`, `map_type`
(`axis_candidate`/`table_candidate`/`unknown`), `map_confidence`,
`dimensions` (JSON, alleen wanneer aangetoond), `element_size`, `payload`
(JSON met criteria), `status`. UNIQUE(file_id, start, end).

### evidence / evidence_relations
Generieke bewijsopslag: `subject_type`+`subject_id`, `evidence_type`, `value`,
`offset`, `confidence`, `status`, `source`; relaties tussen bewijsstukken via
`evidence_relations(evidence_id, relation_type, target_type, target_id,
confidence)`.

### analysis_runs
Hervatbare jobs: `run_type`, `config` (JSON), `status`
(`running`/`done`/`interrupted`), `checkpoint` (JSON, o.a. `last_pair_id`),
`stats` (JSON), tijdstempels.

### knowledge_reviews
Technician-acties op V3-kennis: `subject_type` (`tuning_pattern`/
`tuning_region`/…), `subject_id`, `action` (approve, reject, correct, merge,
split, mark_unknown, mark_checksum, mark_calibration, mark_code, change_stage,
correct_relation), `payload` (JSON), `reviewer`, `note`. Approve/reject
werkt direct door in `tuning_patterns.status` resp. `tuning_regions.status`.

## Zoeken

Geen FTS-tabel: `Repository.search(term)` doorzoekt met parameterized LIKE
alle zoekvelden van `files` (filename, sha256, md5, ecu, hw, sw, cal, vehicle,
engine, transmission, stage, project), `tuning_patterns` (key+payload),
`winols_projects` en `tuning_regions` (signatures, klasse). Gemeten <10 ms op
5.000 paren.

## Migratiegedrag

`Database.__init__` maakt eerst het volledige V2+V3-schema met
`CREATE IF NOT EXISTS`, vult daarna ontbrekende kolommen van reeds bestaande
tabellen gericht aan (witlijst-gebaseerde `ALTER TABLE ADD COLUMN`) en
registreert versie 4 in `schema_migrations` + `PRAGMA user_version`. Bestaande
V2-databases blijven bruikbaar; er is geen destructieve migratie.
