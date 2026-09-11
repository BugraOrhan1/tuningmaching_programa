# SCALABILITY.md — gemeten schaalgedrag (§40/§45/§71)

Alle cijfers hieronder zijn **gemeten** op de ontwikkelmachine
(Linux-sandbox, SQLite 3.40.1, single-process) met de scripts
`scripts/db_scale_benchmark.py`, `scripts/library_benchmark.py` en
`scripts/retrieval_benchmark.py`. Extrapolaties zijn expliciet gemarkeerd.

## Metadata-schaal (content_objects + file_locations)

| Records | Insert (s) | SHA-lookup (ms) | LIKE-filter (ms) | Join (ms) | Geïnd. naam (ms) | DB (MB) |
|---:|---:|---:|---:|---:|---:|---:|
| 100.000 | 1,96 | 1,1 | 8,3 | 6,7 | 0,9 | 53,7 |
| 500.000 | 12,3 | 1,2 | 38,3 | 29,6 | 1,1 | 268,8 |
| 1.000.000 | 26,1 | 1,2 | 77,5 | 59,2 | 1,1 | 537,5 |
| 5.000.000 | 244,1 | 10,1 | 2.256 | 1.657 | 1,4 | 2.713 |

Conclusies:
- **Geïndexeerde lookups blijven ~1 ms tot 5 m records** (sha256-index,
  filename-index): retrieval-filterstadia zijn O(index), niet O(n).
- Insert schaalt lineair (batched executemany in één transactie).
- Naakte LIKE-scans worden traag bij 5 m (2,3 s) — daarom gaat zoeken via
  de FTS5-index en gaan New BIN-matches via de multi-stage pijplijn.
- Geen N+1-patronen: alle library-operaties gebruiken set-gebaseerde SQL
  met indexen op `content_objects(sha256)`, `content_objects(file_type,
  size)`, `file_locations(content_id)`, `file_locations(root_id,
  scan_status)`, `file_locations(filename)` (+ bestaande kennis-indexen).

## 10.000-files library (fysieke bestanden, §71)

Zie [LOCAL_LIBRARY.md](LOCAL_LIBRARY.md): eerste scan 34,9 s (288 files/s),
incrementeel 22 s met **0 rehashes**, na 1 wijziging exact 1 rehash,
database 4,2 MB metadata.

## New BIN retrieval (multi-stage, §40) — 5.000 contents

| Stap | Gemeten |
|---|---|
| Library scan (5.000 files) | 29,5 s (169 files/s) |
| Deep analysis (5.000 contents, eerste keer) | 82,5 s (61/s) |
| New BIN, exacte content-hit (stage 1) | **3 ms** — kennis hergebruikt |
| New BIN, onbekend bestand (alle stadia) | 0,1 s; outlierCorrect = UNKNOWN-waarschuwing |
| Bibliotheekzoekopdracht (FTS5) | milliseconden |

## Extrapolatie naar 10+ TB (gemarkeerd als extrapolatie)

- ~2,5 KB database-metadata per bestand ⇒ 1 m files ≈ 2,5 GB SQLite:
  comfortabel; 5 m ≈ 13 GB: nog bruikbaar, aan te raden om per root te
  archiveren (offline roots blijven doorzochtbaar).
- Initiële scan is I/O-gebonden: ~290 files/s single-worker ⇒ 1 m files
  ≈ 1 uur; parallelle hash-workers (HIGH-profiel, 4×) zijn voorbereid
  via de resource-presets.
- Deep analysis is bewust **per content één keer** en op verzoek: de
  bulk van de bibliotheek blijft ongeanalyseerd (analysis_state NEW)
  zonder dat dit retrieval belemmert — exacte hits en multi-stage
  filters werken op metadata.
- DuckDB/Parquet is bewust níet geïntroduceerd: de gemeten
  queryprestaties geven daar geen aanleiding toe (§46: geen complexiteit
  zonder reden).

## Database-schaalregels (vastlegging)

1. Elke nieuwe filter First een index; benchmarks draaien bij elke
   schema-wijziging.
2. Library-taken schrijven checkpoints per object; herstel kost nooit
   een volledige herscan.
3. Kennistabellen (patterns/identities/regio's) groeien met bevestigde
   paren, niet met bestanden — de 10k-parenbenchmark (STATUS.md) toonde
   lineair schalende rebuild-tijden.
