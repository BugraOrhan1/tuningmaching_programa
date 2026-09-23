# KNOWLEDGE_MODEL.md — de éénheid-van-waarheid kennisketen (V6, §3–§8/§19/§20)

## De volledige keten (één pad voor élle importroutes)

```
Library Location  (D:\Tuning\…, blijft op schijf)
        ↓
Content Identity  (SHA256 — exact één keer geanalyseerd)
        ↓
OLS Project  (first-class: project → versies → binaries → objecten)
        ↓                                        ↘
Project Family                                    raw BIN/ORI (managed of library)
        ↓                                        ↗
Software Lineage  (SAME_CALIBRATION_FAMILY / SOFTWARE_UPDATE /
                   DERIVATIVE / HARDWARE_VARIANT / UNRELATED / UNKNOWN)
        ↓
ECU Image Identity  (hetzelfde technisch ECU-image, waar het ook staat)
        ↓
Calibration Object → Calibration Identity
        ↓
Original/Tuned Pair → Diff Region → Tuning DNA → Tuning Pattern
        ↓
Knowledge / Evidence / Technician Review (+ auditlog)
```

Library-analyse, managed-copy import en OLS-extract schrijven allemaal in
dezelfde tabellen (`files`, `winols_projects`, `content_files`); er zijn
geen aparte "OLS-kennis" versus "BIN-kennis" werelden.

## ECU Image Identity (§4) — de ontbrekende laag tussen file en calibratie

Een ECU Image Identity is **het technisch zelfde ECU-image**, ongeacht of
het als OLS-versie, losse BIN, ORI, backup of in een andere map staat.

Groeperingsregels (alleen inhoudelijk bewijs, nooit offset/filename):

| Regel | Bewijs | Status |
|---|---|---|
| R1 | byte-identiek (zelfde SHA256) | SUPPORTED, conf 100 |
| R2 | zelfde size + zelfde metadata (ECU/HW/SW/CAL) + diffratio ≤ 5% | SUPPORTED, conf 90 |
| R3 | zelfde size zonder metadata + diffratio ≤ 5% | CANDIDATE, conf 70 |

**Grootteverschil = nooit samenvoegen.** Versies binnen hetzelfde
OLS-project met verschillende werkelijke imagegrootte krijgen aparte
identiteiten én een geregistreerde relatie met `relation=UNKNOWN` en een
gemeten reden (blokgelijkheid van het kleinere image in het grotere).

### Bewezen uit de echte data (GASDROP_100119.ols)

- Drie 2MiB-tunedversies verschillen samen maar **424 bytes** → één image
  identity (SUPPORTED).
- De expliciet gelabelde 'Origineel'-versie is **855.132 B** en géén subset
  van de 2MiB-images (38% blokgelijkheid) → eigen identiteit +
  UNKNOWN-relatie: *"size mismatch 855132 vs 2097152 B; kleiner is GEEN
  subset (blokgelijkheid 38% < drempel)"*.
- De OLS-pairing gebruikt daarom de **werkelijke geëxtraheerde
  imagegrootte**, niet de geclaimde `binary_length` uit de OLS. Foutief
  bevestigde size-mismatch-paren worden bij een nieuwe suggest-run
  zelfherstellend ontkoppeld (met audit-regel). DNA op zo'n paar: nooit
  zonder technicusbeslissing.

## Project Family en Software Lineage (§5/§6)

- **Project Family**: OLS-projecten gegroepeerd op (ECU-familie,
  softwarefamilie) uit de herkende metadata van hun versie-binaries.
- **Software Lineage** tussen families van dezelfde ECU:

| Relatie | Bewijsvereiste | Confidence |
|---|---|---|
| SAME_CALIBRATION_FAMILY | ≥1 gedeelde ECU-image-identiteit | 60+10×gedeeld |
| SOFTWARE_UPDATE | numerieke softwareincrement (SW 7→8) | 55 |
| DERIVATIVE | zelfde ECU, andere SW, geen increment-bewijs | 40 (kandidaat) |
| HARDWARE_VARIANT | verschillend hardwarebewijs | 50 |
| UNKNOWN | onvoldoende bewijs | 0 — expliciete uitkomst |

## Negatieve kennis (§8) — REJECTED MATCH is ook kennis

`reject-match <subject> a_type a_id b_type b_id --reason …` registreert
**A ≠ B** permanent (`negative_relations`, uniek per paar, + auditlog).
Effecten, automatisch:

- New BIN-rapporten tonen de verworpen match niet meer
  (`suppressed_by_negative_knowledge`).
- Identity-alignment slaat negatieve paren over en rapporteert dat.
- Een rebuild verwijdert de relatie niet; alleen de technicus kan haar
  expliciet trekken.

## Provenance-contract (§7)

Elke conclusie (New BIN-rapport, why-rapport, comparison, image-identiteiten,
golden runs) draagt:

```
algorithm_version   (bv. "v6.0")
knowledge_build_id  (welke kennisversie is gebruikt)
parser_version      (welke OLS-parser — §19)
generated_at        (wanneer)
```

Daarmee is later verklaarbaar: *"op 11-09-2026 gaf de software 93%, omdat
knowledge build N met engine v6.0 deze projecten gebruikte."*

## Parser-versioning (§19)

- `PARSER_VERSION` wordt per project bewaard; OLS-records bewaren raw
  evidence (offset/lengte/raw-hash/gedecodeerde velden) los van
  interpretatie.
- `reparse-ols <project_id>` leest het bekende projectbestand opnieuw
  (read-only), verifieert de SHA, vergelijkt structuur met de opgeslagen
  evidence en registreert het drift-rapport in `project_metadata.reparse`.
  Oude records blijven bewaard: her-interpretatie zonder data-verlies.

## Evidence levels (§20)

```
TECHNICIAN_CONFIRMED  >  SOURCE_EXPLICIT  >  SOURCE_STRUCTURAL
                            >  INFERRED  >  UNKNOWN
```

Expliciete WinOLS-labels zijn SOURCE_EXPLICIT; structuur/analyse is
SOURCE_STRUCTURAL; technicus-review overrulet alles
(TECHNICIAN_CONFIRMED); afgeleide conclusies zijn INFERRED; twijfel is
UNKNOWN. Elke rol/identiteit draagt zijn niveau.

## Golden Dataset (§9) en knowledge regression (§10)

- `golden` (CLI) / `POST /golden/run` draait 9 deterministische cases:
  KNOWN SAME · KNOWN DIFFERENT · KNOWN ORIGINAL/TUNED · KNOWN SAME CAL
  ACROSS SW · KNOWN DIFFERENT CAL · KNOWN CHECKSUM · KNOWN MAP · UNKNOWN
  (geen geforceerde match) · REAL-OLS image-identiteit. Resultaten worden
  opgeslagen (`golden_runs`) per engine-versie — "tests groen" zonder
  intelligence-claim is voortaan onmogelijk.
- `snapshot` + `diff_knowledge_snapshots` leggen vast welke conclusies
  verdwenen/verschenen/veranderden bij een engine-wijziging — inclusief
  *rejected matches die zijn teruggekomen*.
- `measure_review_impact` meet golden before/after rond een review-actie
  (§11: de complete human-in-the-loop-lus, gemeten).
