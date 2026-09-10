# ARCHITECTURE.md — V3 Tuning Intelligence Engine

## Overzicht

V3 is **additief** op de V2-basis: geen rewrite, geen dubbele systemen. De
bestaande pijplijn (import → file intelligence → OLS intelligence → diff →
structural analysis → matcher → knowledge review → DNA → presentatie) is
uitgebreid met een intelligence-laag die van bevestigde paren leert.

```
Import Layer            repository.import_file / import_folder / import_project  (V2)
                          · batch, dedupe, backgroundjobs (GUI)
File Intelligence       analysis/{metadata,recognition,ecu_fingerprint,fingerprint}.py (V2)
OLS Intelligence        winols/{ols_reader,ols_structure,ols_importer}.py (V2)
                          · + Service.ols_graph (V3): projectgraph met bewezen
                            relaties en expliciete UNKNOWN RELATIONSHIP
Diff Engine             analysis/diff_engine.py (V2)
                          · + build_regions: elke diff-regio wordt een
                            TuningRegion (V3) in tuning_regions
Structural Analysis     analysis/{alignment,signatures,clustering}.py (V2)
                          · + tuning_region.py (V3): signatures, entropie,
                            regio-klassen, checksum-kandidaten
Map Detection           intelligence.detect_map_structures (V3, deterministisch,
                          structuur zonder namen; v3_interfaces-ABC's blijven
                          de extensiepunten)
Tuning DNA Engine       service.generate_tuning_dna (V2-kern) + tuning_regions
                          + region_ids-verwijzingen (V3)
Pattern Engine          intelligence.rebuild_patterns (V3): deterministische
                          clustering, tuning_patterns + tuning_pattern_members,
                          hervatbaar via analysis_runs
Cross Software          intelligence.align_pattern_across_software /
  Alignment               find_pattern_matches (V3) → software_alignments
Knowledge Graph         knowledge_repo: evidence(+relations), reviews,
                          knowledge_history; patronen/regio's reviewable
Candidate Engine        matching/matcher.py + ranking.py (V2, bevroren
                          V2.7-kandidaatstroom met bestaande guards)
Technician Review       knowledge_candidates + ols_object_reviews (V2) +
                          knowledge_reviews (V3) via GUI/API/CLI
GUI / Reports           21 GUI-pagina's, 55 API-endpoints, 30+ CLI-commando's,
                          rapportexport (V2) + new_bin_report (V3)
```

## Modulekaart (V3-nieuw)

| Module | Inhoud |
|---|---|
| `app/analysis/tuning_region.py` | build_regions, entropy, delta/structural signatures, signature_similarity, regio-klassen, confidence-formule, checksum-kandidaatmarkering |
| `app/database/knowledge_repo.py` | RepositoryV3Mixin: regio's, patronen/leden, software_alignments, map_regions, evidence(+relations), knowledge_reviews, analysis_runs, search |
| `app/database/database.py` | V3_SCHEMA (additief, schema v4) + ALTER-veiligheid |
| `app/intelligence.py` | ServiceV3Mixin: rebuild_patterns, align_pattern_across_software, find_pattern_matches, detect_map_structures, new_bin_report, ols_graph, review-wrappers, jobs, search |
| `app/service.py` | diff() persisteert TuningRegions; DNA verwijst naar region_ids |
| `app/api.py` | 13 V3-endpoints |
| `app/main.py` | 11 V3-CLI-commando's |
| `app/ui/main_window.py` | 5 V3-pagina's (Patronen, Region Viewer, New BIN, OLS Explorer, Zoeken) |
| `scripts/scale_test.py` | end-to-end schaaltest 100/1.000/5.000 paren |

## Datastroom (leerloop, V3-§16)

```
Import → Analyze (diff) → TuningRegions (candidate)
      → Technician review (optioneel, per regio/patroon)
      → rebuild_patterns (alleen bevestigde paren; checksum/padding eruit)
      → Patterns (candidate) → Technician approve/reject
      → Cross-software alignment (evidence per mapping)
      → New BIN Analysis: blok-run alignment + contextscore →
        patronen + evidence + confidence → technician review
```

Afgekeurde kennis (`rejected`) wordt niet meer als kandidaatkennis getoond;
clustering bouwt op region-status en paarbewijs, niet op afkeuringen.

## Performance-ontwerp

- SHA/fingerprint-cache: `files` + `fingerprints` (V2); regio-signatures zijn
  opgeslagen en worden nooit herberekend bij het lezen.
- Incrementeel: `rebuild_patterns` verwerkt alleen paren na het
  `last_pair_id`-checkpoint; onderbroken runs hervatten (getest).
- Batch-inserts: `executemany` voor leden/map-regio's.
- Begrensde scans: mapdetectie scant max. 1 MiB op een 64-byte grid;
  paarsgewijze signature-gelijkenis is afgekapt op 50 leden per patroon.
- Indexen op alle V3-toegangspaden (pair, signature, class/status, pattern,
  subject, file).
- Gemeten (scripts/scale_test.py, deze machine): 5.000 paren → import 92 s,
  regionextractie+rebuild 116 s, zoeken <10 ms.

## Beveiliging/integriteit

- Bronbestanden (BIN/ORI/OLS) worden nergens in V3 geschreven; elke
  schrijfactie gaat naar de eigen database of `reports/`.
- V2.7-kandidaatstroom (`generate_tune_candidate`) is bevroren: niet
  uitgebreid, bestaande guards (drempel 50–100, bevestigd paar, regionale
  similarity ≥98, target nooit gewijzigd, checksum-waarschuwing) intact.
- UNKNOWN-first overal: `unknown` regio-klasse/map-type, `unknown` status bij
  alignering zonder blok-run, UNKNOWN RELATIONSHIP in de OLS-graph.
