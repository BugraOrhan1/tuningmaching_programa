# ROADMAP.md

Stand: na V3-implementatieronde (2026-09-10). Statuswoorden volgens de
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
