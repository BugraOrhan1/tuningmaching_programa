# TUNING_DNA.md — Tuning DNA in de V3 Tuning Intelligence Engine

Status: geïmplementeerd zoals hier beschreven. Alle beweringen zijn gedekt
door tests (`tests/test_v3_intelligence.py`, `tests/test_workflow.py`,
`tests/test_ols_structure.py`).

## Wat Tuning DNA hier IS

Een Tuning DNA-record is de vastgelegde, traceerbare wijzigingskennis van
één **bevestigd** `Original → Tuned`-paar. Het bestaat uit:

1. **TuningRegions** (tabel `tuning_regions`) — elke gewijzigde regio als
   structuurobject (zie hieronder).
2. **DNA-payload** (tabel `tuning_dna`) — bronverwijzingen
   (original/tuned file-ID + SHA256), ECU/HW/SW/CAL/project/stage van het
   bronbestand (UNKNOWN wanneer onbekend), en de `region_ids` die naar de
   opgeslagen regio's verwijzen.

Regels:

- **Alleen bevestigde paren.** `generate_tuning_dna` weigert onbevestigde
  paren (getest).
- **Status `candidate`.** DNA is kandidaat-kennis tot een technician
  approve/reject doet (`knowledge_reviews`); afgekeurde kennis wordt niet
  weer als bewezen gebruikt bij clustering (statusfilter).
- **Nooit mapnamen.** `map_type` blijft `unknown` zonder bewijs. Er is geen
  codepad dat Boost/Torque/e.d. invult.
- **Read-only.** DNA-creatie schrijft alleen in de eigen database; de
  bron-BINs worden nooit gewijzigd.

## TuningRegion — velden per regio

| Veld | Betekenis |
|---|---|
| `start_offset` / `end_offset` / `length` | half-open bereik `[start, end)` |
| `changed_byte_count` / `changed_percentage` | gewijzigde bytes en dichtheid |
| `original_bytes_hash` / `tuned_bytes_hash` | SHA256 van het regiofragment |
| `before_context` / `after_context` | 32 bytes hex aan weerszijden (original-kant) |
| `original_context_hash` / `tuned_context_hash` / `original_region_context_hash` | context-hashes (32 B ervoor; 32 B ervoor + regio + 32 B erna) |
| `relative_start` / `relative_end` | positie als fractie van de bestandsgrootte |
| `structural_signature` | SHA256 over offset-onafhankelijke structuurkenmerken |
| `delta_signature` | SHA256 over de gekwantiseerde deltareeks (max. 256 samples) |
| `structure_features` | uitlegbare kenmerken (JSON): lengtebucket, dichtheidsbucket, veranderingspatroon op een 1/32-grid, transities, entropiebuckets, deltasamenvatting |
| `entropy_before` / `entropy_after` | Shannon-entropie in bits/byte |
| `region_class` | `small_parameter` (≤8 B), `calibration_region`, `calibration_cluster` (≥512 B), `padding`, `checksum_candidate`, `unknown` |
| `cross_pair_shared` | zelfde relatieve plaats verandert in ≥3 paren uit ≥2 ECU-families |
| `alignment_confidence` | binnen het paar 100 (offset is exact); cross-software in `software_alignments` |
| `map_confidence` / `map_type` | standaard `unknown`/0; alleen door mapdetectie of handmatige review gevuld |
| `stage`, `ecu_family`, `software_number`, `hardware_number`, `calibration_number`, `project` | overgenomen uit `files`-metadata, UNKNOWN wanneer onbekend |
| `confidence` | gedocumenteerde formule, zie EVIDENCE_MODEL.md |
| `status` | `candidate` → `verified`/`rejected` via review |

## Waarom signatures offset-onafhankelijk zijn

Softwarevarianten plaatsen dezelfde calibratie op andere absolute offsets
(V3-§5). Daarom beschrijft `structural_signature` de regio met **relatieve**
posities (veranderingspatroon op een 1/32-grid binnen de regio), gekwantiseerde
buckets en deltasamenvatting — nooit absolute offsets. Getest: dezelfde
64-byte-wijziging op offset 200 en 900 levert **dezelfde** signature
(`test_structural_signature_is_offset_independent`).

## Checksumbeleid

Checksumgebieden worden **niet automatisch** als zodanig herkend — dat zou
gokken zijn. De enige automatische markering is `checksum_candidate`, en
alleen wanneer aan álles is voldaan:

- dezelfde relatieve plaats verandert in **≥3 paren**,
- uit **≥2 verschillende ECU-families**,
- met onderling verschillende tuned-inhoud.

Zo'n regio krijgt confidence-cap 40 en wordt **uitgesloten** van
patroonclustering (getest: `test_checksum_candidate_marking_and_exclusion`).
Een technician kan een regio handmatig markeren
(`review-knowledge region <id> mark_checksum`).

## Pattern clustering

`rebuild_patterns` (hervatbaar, checkpoints in `analysis_runs`):

1. Genereert regio's voor alle bevestigde paren (incrementeel, resume via
   `last_pair_id`-checkpoint).
2. Markeert checksum-kandidaten (zie boven).
3. Clustert over `(ecu_family, structural_signature)`; groepen met
   signature-gelijkenis ≥ 0,95 worden deterministisch samengevoegd
   (near-merge) binnen dezelfde ECU-family.
4. Elk patroon krijgt: ECU-family, signature + variants, aantal bevestigde
   projecten, aantal waargenomen regio's, software-varianten, stage-verdeling,
   structurele gelijkenis (paarsgewijs over max. 50 leden), typical delta,
   contradictieteller en een **gedocumenteerde** confidence
   (EVIDENCE_MODEL.md).
5. Leden worden opgeslagen in `tuning_pattern_members` (region_id + pair_id +
   similarity); patronen zijn `candidate` tot review.

Stage learning: de stage-verdeling per patroon volgt direct uit de bevestigde
paren (`stages`-veld); er worden geen stages geïnterpoleerd of gegokt.

## Cross-software alignment

`align_pattern_across_software(pattern_id)`:

- Paart de bron-originals van verschillende softwarevarianten en gebruikt de
  bestaande exacte blok-run-alignment (`align_regions`) om regio-offsets te
  mappen.
- Per mapping: `structural_similarity` (signature-leden), contextvergelijking
  (128 B-windows rond de regio, positionele byte-gelijkheid),
  `supporting_projects`, `supporting_signatures`, `contradicting_evidence`
  (zelfde bronregio mapt naar ≥2 disjuncte doelen >512 B uit elkaar).
- `alignment_confidence`-formule: `0,4·100 (bewezen blok-run) + 0,3·context + 0,3·min(100, projecten/3·100) − 10·min(2, contradicties)`, cap 95 — gedocumenteerd in EVIDENCE_MODEL.md.
- Zonder blok-run: status `unknown`, confidence 0, expliciete evidence-regel.
- Resultaat: `software_alignments` + `offsets_by_software` per patroon
  (Logical Tuning Pattern X → offsets per software, absolute offsets als
  uitkomst).

`find_pattern_matches(query, threshold)`: zoekt bekende patronen in een
**nieuwe original-BIN** door dezelfde blok-run-alignment + contextscore;
levert per patroon de beste match met `query_offset`, stage-verdeling,
patroon-confidence en projecten-aantal. Dit voedt de New BIN Analysis.

## Wat Tuning DNA NIET is

- Geen mapnamen, geen functielabels, geen tuninginstructies.
- Geen automatische BIN-modificatie (de aparte V2.7-kandidaatstroom is
  bevroren en behoudt alle guards).
- Geen zwart-boxscore: elke confidence heeft een gedocumenteerde formule en
  de onderliggende componenten zijn in GUI/API altijd zichtbaar.
