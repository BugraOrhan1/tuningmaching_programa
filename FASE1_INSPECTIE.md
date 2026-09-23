# V3 FASE 1 — Inspectie bestaande codebase

Datum: 2026-09-10 · Branch: `arena/01a08bb3-tuningmaching-programa` · HEAD: `685c725`
Status: **inspectierapport — er is nog geen V3-code geschreven.**

Dit rapport antwoordt op de 7 verplichte FASE 1-vragen en sluit af met de
verplichte statusverdeling IMPLEMENTED / PARTIALLY IMPLEMENTED / NOT
IMPLEMENTED / UNKNOWN per V3-concept, met bewijs (bestand + functie/tabel).

---

## 1. Bestaande architectuur

Modulair, ~4.250 regels Python, 43 testfuncties (49 pytest-uitkomsten) groen.
De pijplijn uit V3-§33 bestaat al grotendeels als losse modules:

```
Import Layer        repository.import_file / import_folder / import_project
                    batch, dedupe op (source_path, sha256, file_type),
                    GUI-backgroundjobs (QThread-worker: run_job/safe)
File Intelligence   analysis/metadata.py (ECU:/HW:/SW:/CAL:-tags),
                    analysis/recognition.py (DETECTED/POSSIBLE/UNKNOWN),
                    analysis/ecu_fingerprint.py, analysis/fingerprint.py
                    (sha256/md5/crc32 + block-hashes + bytehistogram)
OLS Intelligence    winols/ols_reader.py, ols_structure.py, ols_importer.py,
                    project_export.py (JSON/CSV/HTML + sha-manifest)
Diff Engine         analysis/diff_engine.py (numpy, merge_gap, half-open)
Structural Analysis analysis/alignment.py (SequenceMatcher over block-hash-
                    reeksen), analysis/clustering.py (DBSCAN), signatures.py
Matcher             matching/matcher.py (prefilter → bounded heap top-N),
                    matching/ranking.py (gewogen, uitlegbare componentscore)
Learning            learning/model.py (NearestNeighbors, cosine, histogrammen)
Knowledge/Review    knowledge_candidates + approve/reject + families/signatures
Tuning DNA          service.generate_tuning_dna (alleen bevestigde paren)
Tune candidate      service.generate_tune_candidate (bewaakt; zie §21-noot)
Presentatie         api.py (42 endpoints, X-API-Key), main.py (20+ CLI),
                    ui/main_window.py (16 pagina's + Quick Workflow)
```

Dwangende sporen die overal doorlopen: **read-only** (bronbestanden worden
nooit gewijzigd), **UNKNOWN-first** (`DETECTED/POSSIBLE/UNKNOWN`,
`UNKNOWN_RECORD_TYPE`, `label_only`), **evidence + confidence per bewering**,
**aparte scores** (similarity vs compatibility zijn overal twee velden).

## 2. Bestaande database

SQLite, `PRAGMA user_version = 3`, schema additief/idempotent
(`database.py`: CREATE IF NOT EXISTS + schema_migrations). **25 tabellen**:

- **Files**: `files` (UNIQUE(source_path,sha256,file_type); indexen op sha256
  en (file_type,file_size); metadata ECU/HW/SW/CAL/vehicle/stage/project),
  `fingerprints` (1:1), `recognition_results`.
- **Paren & diffs**: `file_pairs` (UNIQUE-paar, `confirmed`-vlag), `diffs`,
  `diff_features` (JSON-features per diff-regio).
- **OLS**: `winols_projects`, `ols_objects`, `ols_records`,
  `ols_record_references`, `ols_binaries`, `ols_version_relations`,
  `ols_map_objects`, `ols_evidence`, `ols_object_reviews`,
  `ols_version_binaries` (role/role_confidence/relation_type/
  relation_confidence/file_id), `ols_evidence`.
- **Families/kennis**: `ecu_families`+`ecu_signatures`,
  `software_families`+`software_signatures`, `calibration_families`,
  `knowledge_candidates` (status candidate/approved/rejected + review_note).
- **Learning**: `calibration_alignments`, `tuning_dna` (UNIQUE(pair_id),
  status candidate/verified/rejected), `tuning_patterns`
  (UNIQUE pattern_key, frequency, confidence), `tune_candidates`.
- **Systeem**: `schema_migrations`.

V3-gaten in het schema: geen `tuning_regions`-tabel (regio's zitten nu als
JSON in `tuning_dna.payload` en `diff_features`), geen
`tuning_pattern_members`, geen `software_alignments` met evidence-velden
(`calibration_alignments` heeft alleen offsets+confidence+method), geen
`map_signatures`/`map_regions`, geen generieke `evidence`/`evidence_relations`
(evidence is per-tabel JSON-kolom), geen `analysis_runs` (checkpoints), geen
FTS-index voor doorzoeken.

## 3. Bestaande OLS-functionaliteit

`winols/ols_structure.py` (`parse_ols_structure`):

- Bewezen binary-extractie op twee gronden: `explicit_import_header`
  (filenaamrecord + padrecord + vast nulveld) en
  `repeating_identity_header` (identiteitsheader met vaste stride, direct na
  nul-padding, ≥99% blokgelijkenis, identiteitsstructuurscore op
  slashes-ID `getal/getal/…`); minimaal stride 1024 B.
- Gescheiden `role_confidence`/`relation_confidence`; rolvolgorde: expliciete
  WinOLS-labels > versie/volgorde-relatie (`version_to_binary_order_inferred`
  75) > binary-zonder-versie (`binary_without_version`).
- `ols_reader._extract_length_prefixed_records`: byte-georiënteerde recordscan
  (≥200 map-records op de echte OLS), `UNKNOWN_RECORD_TYPE` voor onbekend.
- `repository.import_project`: één parse, DELETE+reinsert bij herimport
  (reviews behouden), mapverrijking via `maps_by_offset` (fallback
  `label_only`), `upsert_ols_file` schrijft originals|tuned|unknown/<sha>.bin,
  `suggest_ols_project_pairs` (gelijke grootte; auto-confirm pas bij
  role_confidence ≥ 95 aan beide kanten).

Geverifieerd op de echte `GASDROP_100119.ols`: identiteit
`53/1/MG1CS003/…`, stride 2.097.152, 5 binaries (o.a. original 855.132 B),
Origineel→original (100/explicit), 3 stage-versies→tuned (95/inferred 75),
1 onvolledige staart → unknown. Geen paren bij grootteverschil (correct).

**Nog niet** (bewust, UNKNOWN): mapdefinities/assen/factoren/units worden
niet betrouwbaar gedecodeerd; `Kaart`-labels zijn kandidaten
(`label_only`/`address_candidate`); record-graph (parent/child) alleen
beperkt gevuld; geen volledige record-type-inventaris van het formaat.

## 4. Bestaande diff-engine

`diff_engine.diff_blocks(original, tuned, merge_gap)`:

- numpy-masker → gewijzigde indices → samenvoegen met `merge_gap` →
  regio's `[start, end)` met `length`, `changed_bytes`,
  `change_percentage`, `original_hash`, `tuned_hash` (sha256 van het
  regio-fragment). `hex_rows` voor de hex-weergave.
- `Service.diff()` persisteert blokken in `diffs` + features
  (`relative-region-v1`: relatieve start, log-lengte, dichtheid) in
  `diff_features`; offsetconventie gedocumenteerd in de output.
- `Service.analyze()` verrijkt matches al met `known_changes` incl.
  per-regio similarity (query ↔ bekende original-regio) en onderdrukt
  bekende wijzigingen bij `incompatible_base` (< 60% basisovereenkomst).

**Ontbreekt** t.o.v. V3-§3: context-hashes (before/after 32 B — bestaan al
in DNA-payload, niet in `diffs`), entropy voor/na, structural/delta
signatures, regio-classificatie (parameter/cluster/checksum/code/padding),
alignment_confidence en map_confidence per regio. Checksumgebieden worden
nog niet herkend en uitgesloten.

## 5. Bestaande matcher

`matcher.find_matches`:

- Prefilter via `repo.prefilter_originals` (hiërarchie ECU→SW→CAL +
  histogramafstand, `candidate_pool`), daarna bounded heap (top-N).
- `similarity.compare`: positionele byte-gelijkheid (`match_score`),
  langste identieke reeks, identieke block-hashes; **aparte**
  `compatibility_confidence` met status
  identical_bytes/near_identical_unverified/size_mismatch/
  metadata_conflict/incompatible_base.
- `ranking.overall_score`: gewogen componenten (binary 0.55, ecu 0.20,
  hw 0.10, sw 0.10, cal 0.05) met zichtbare redenen/waarschuwingen;
  outlier-waarschuwing bij geen enkele high-confidence match.

**Ontbreekt** t.o.v. V3: structurele (niet-positionele) similarity,
tuning-pattern-confidence als component, cross-software-alignment in het
rapport, gerelateerde-originals-ranglijst met aparte
structurele/compatibiliteitsscores per regel (de data is er al per match).

## 6. Wat hergebruikt kan worden (concreet)

| V3-bouwsteen | Bestaande basis | Actie in FASE 2+ |
|---|---|---|
| TuningRegion | `diff_blocks` + `Service.diff` + `diff_features` | uitbreiden met context/entropy/signature/classificatie; nieuwe tabel |
| Tuning DNA | `generate_tuning_dna` (alleen confirmed, context-hashes, relative offsets) | regio's uit de JSON halen → `tuning_regions`; DNA verwijst door |
| Patterns | `tuning_patterns` + `clustering.cluster_changes` | clustering uitbreiden met signature-gelijkenis + ECU-scoping; `tuning_pattern_members` |
| Cross-software | `alignment.align_regions` + `calibration_alignments` | evidence-velden + supporting/contradicting optellen; `software_alignments` |
| Score-model | `ranking.overall_score` (componenten al zichtbaar in UI/API) | nieuwe componenten (pattern, alignment) additief toevoegen |
| New BIN analyse | `Service.analyze` (known_changes met regionale similarity) | patroon-matches + evidence-rapport toevoegen |
| Review-loop | `knowledge_candidates` approve/reject + `ols_object_reviews` | hergebruiken voor regio/patroon-reviews |
| Evidence | per-tabel evidence-kolommen + `ols_evidence` | generieke `evidence`/`evidence_relations` additief |
| Mapdetection | `v3_interfaces.py`-ABC's (MapDetector, AxisDetector, …) | deterministische 1D/2D/3D-detectie als eerste implementatie |
| GUI/API/CLI | 16 pagina's, 42 endpoints, 20+ commando's, rapportexport | pagina's Region/Pattern/OLS-Explorer + endpoints additief |
| Performance | fingerprints gecached in `fingerprints`; dedupe bij import | `analysis_runs` + incrementele analyse + batch-inserts |

## 7. Wat ontbreekt (V3-gaten, gerangschikt per fase)

1. **FASE 2 — TuningRegion**: entropy voor/na, context before/after,
   structural_signature, delta_signature, regio-class (parameterw/ijziging,
   calibratieregio, cluster, checksum, code, padding, onbekend),
   checksum-detectie zodat checksumwijzigingen nooit als tuninggebied gelden,
   alignment_confidence, map_confidence (default UNKNOWN).
2. **FASE 3 — Tuning DNA**: `tuning_regions`-tabel; DNA-record per paar met
   alle V3-§2-verplichte velden (ECU/HW/SW/CAL/project/stage afkomstig uit
   `files`-metadata; alles UNKNOWN wanneer onbekend).
3. **FASE 4 — Pattern clustering**: clustering over structurele signatures
   (niet alleen locatie/lengte/dichtheid), ECU-family-scoping,
   `tuning_pattern_members`, stage-koppeling, confidence uit
   support/aantal projecten.
4. **FASE 5 — Cross-software alignment**: alignment-engine met
   supporting_projects/signatures, contradictions, alignment_confidence;
   patterns herkend op andere offsets/software via context + signature
   (absolute offsets secundair).
5. **FASE 6 — OLS**: record-inventaris uitbreiden (alleen op bewezen
   structuur), record-referenties voller vullen, project-graphweergave met
   `UNKNOWN RELATIONSHIP` waar niet bewezen.
6. **FASE 7 — New BIN Analysis**: gecombineerd rapport (ECU/SW/CAL-confidence
   + related projects + DNA/pattern-matches + regio's + evidence +
   contradiction-penalty), overal aparte scores.
7. **FASE 8 — GUI**: Dashboard-uitbreiding, Region Viewer, Pattern Viewer,
   OLS Explorer, doorzoekbaar alles (FTS), Analysis Jobs-overzicht.
8. **FASE 9 — Performance**: `analysis_runs` met checkpoints/resume,
   incrementele analyse (skip ongewijzigde sha's), batch-inserts,
   multiprocessing waar veilig, scaling-tests 100/1.000/5.000.

## Statusverdeling per V3-concept (met bewijs)

| V3-concept | Status | Bewijs |
|---|---|---|
| BIN/ORI/OLS-import, hashes, fingerprints | **IMPLEMENTED** | `fingerprint.py`, `repository.import_file/import_project`, 49 tests groen |
| Original/Tuned pairing + review | **IMPLEMENTED** | `file_pairs`, `suggest_pairs`/`suggest_binary_relationships`/`suggest_ols_project_pairs`, confirm-API |
| Diff-analyse (basis) | **IMPLEMENTED** | `diff_engine.diff_blocks`, `diffs`/`diff_features`, hexweergave |
| Aparte similarity/compatibility-scores | **IMPLEMENTED** | `similarity.compare`, `ranking.overall_score` |
| UNKNOWN-first + evidence per tabel | **IMPLEMENTED** | `recognition.py`, `classification.py`, evidence-kolommen, UNKNOWN_RECORD_TYPE |
| Read-only data-integriteit | **IMPLEMENTED** | sha-checks in elke testronde; geen schrijfpad naar bronbestanden |
| Families/kennisreview/signatures | **IMPLEMENTED** (kleinschalig) | `propose_families`, approve/reject, `*_signatures` |
| OLS binary-extractie + rolverdeling | **IMPLEMENTED** (bewezen gedeelte) | `ols_structure.py`, echte-OLS-tests (role 100/explicit, tuned 95/75) |
| OLS map-inhoud (assen/units/waarden) | **NOT IMPLEMENTED** | alleen `label_only`/adreskandidaten; bewust geen decodering |
| TuningRegion (rijk regio-object) | **PARTIALLY IMPLEMENTED** | basis in `diffs`; entropy/signature/classificatie ontbreken |
| Tuning DNA | **PARTIALLY IMPLEMENTED** | `generate_tuning_dna` (candidate, alleen confirmed); mist aparte regio-tabel, stage/ECU-velden |
| Pattern clustering | **PARTIALLY IMPLEMENTED** | `tuning_patterns` + DBSCAN op locatie/lengte/dichtheid; geen signature-clustering/ECU-scoping |
| Cross-software alignment | **PARTIALLY IMPLEMENTED** | `align_regions` (exacte blokruns) opgeslagen in `calibration_alignments`; geen evidence-engine/patronen over software heen |
| Map detection (1D/2D/3D, structuur) | **NOT IMPLEMENTED** | alleen ABC's in `v3_interfaces.py` |
| Stage learning | **NOT IMPLEMENTED** | `stage`-kolom bestaat, geen koppeling naar patterns |
| Evidence graph | **PARTIALLY IMPLEMENTED** | evidence per tabel + `ols_record_references`/`ols_version_relations`; geen generieke graph |
| New BIN Analysis-rapport met patronen | **PARTIALLY IMPLEMENTED** | `analyze()` met known_changes; geen patroon-matches/evidence-samenvatting |
| Region/Pattern Viewer, OLS Explorer | **NOT IMPLEMENTED** | hexweergave per paar bestaat; viewers niet |
| Zoeken over alle velden | **PARTIALLY IMPLEMENTED** | `files(query)`-LIKE + dashboard; geen FTS/patronen |
| Performance/checkpoints/schaaltests | **NOT IMPLEMENTED** | fingerprints-cache + dedupe bestaan; geen `analysis_runs`, geen 1k/5k-tests |
| Kandidaat-tune-generatie (V2.7) | **IMPLEMENTED (eerdere fase)** | `generate_tune_candidate` + guards; target nooit gewijzigd, checksums niet gecorrigeerd |

### Open punt voor de opdrachtgever (V3-§21 spanning)

V3 zegt: *"Eventuele automatische BIN-generatie behoort pas tot een
toekomstige fase en mag nu niet worden geïmplementeerd."* De bestaande
V2.7-functie `generate_tune_candidate` (Quick Workflow-stap 2, CLI
`generate-candidate`, API `/files/{id}/generate-candidate`) schrijft al een
**kandidaatbestand** (nooit het doelbestand, met expliciete
checksum-waarschuwing). Voorstel: in V3 **bevriezen** — niet uitbreiden,
alleen behouden met de bestaande guards — tot de technician-review-keten
(FASE 7) bewezen patronen oplevert. Decisie aan de opdrachtgever.

## Conclusie

De V2-basis is geschikt als fundament: import, diffs, paren, review, DNA-kern,
matching en OLS-extractie zijn echt aanwezig en getest. V3 vereist géén
rewrite maar **additieve uitbreiding**: rijkere regio-objecten, aparte
tabellen voor regio's/patronen/leden/alignments, signature-clustering,
evidence-graph, viewers en schaalbaarheid. Volgorde volgt FASE 2–9. Eerste
concrete FASE 2-stap: checksum-herkenning + TuningRegion-uitbreiding van
`diff_blocks`/`Service.diff` + `tuning_regions`-tabel, met tests voor
identiek/klein/groot/checksum-only/verschillende software.
