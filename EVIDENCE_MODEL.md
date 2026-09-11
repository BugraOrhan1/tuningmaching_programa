# EVIDENCE_MODEL.md — scores, evidence en onzekerheid

## Principe

Geen enkele score is magisch. Elke confidence in V3 heeft een hier
gedocumenteerde formule, en de onderliggende componenten zijn in de GUI en
API altijd naast het eindcijfer zichtbaar (V3-§17, §32). Waar bewijs ontbreekt,
staat `UNKNOWN` of `INSUFFICIENT EVIDENCE` — nooit een gegokte conclusie.

## 1. V2-scores (onveranderd overgenomen)

- **match_score** (positionele gelijkheid): `100 × identieke bytes op
  dezelfde offset / grootste bestandsgrootte`.
- **compatibility_confidence**: apart veld; identieke bytes → 100;
  verder `min(70, match_score × 0,5 + 5 × metadata-overeenkomsten)`;
  size_mismatch → cap 20; metadata-conflict → cap 10; basis <60% → 0 en
  status `incompatible_base` (bekende wijzigingen worden onderdrukt).
- **overall_match_score** (matching): gewogen gemiddelde binary 0,55 /
  ecu 0,20 / hw 0,10 / sw 0,10 / cal 0,05 — alle componenten zichtbaar.

## 2. TuningRegion-confidence

```
basis                     50
dichtheidsbonus           + min(30, changed_percentage / 10)
lengtebonus               + min(20, length / 256 × 20)
padding                   = 10
checksum_candidate        cap 40
cross_pair_shared         +5 (cap 99)
```

Interpretatie: hoe zeker is dit een *echte tuningregio*? Padding is vrijwel
zeker geen tuning; checksum-kandidaten zijn bewust laag; een dichte, lange
regio is structureel duidelijk.

## 3. Region-klasse: deterministisch of UNKNOWN

- `small_parameter`: length ≤ 8 B.
- `calibration_region`: 8 < length < 512 B.
- `calibration_cluster`: length ≥ 512 B.
- `padding`: beide zijden alleen 0x00/0xFF.
- `checksum_candidate`: alléén bij gedeelde wijzigingsplaats
  (≥3 paren, ≥2 ECU-families, onderling verschillende tuned-inhoud).
- `unknown`: anders — met name code/softwaregebieden worden **nooit**
  automatisch geclassificeerd (dat zou raden zijn).

## 4. Patroon-confidence

```
confidence = clamp(50 + 15 × log2(1 + confirmed_projects), 50, 95)
             − 10 × (1 als contradicties > 0)
```

- `confirmed_projects`: aantal verschillende bevestigde paren in het patroon.
- Contradictie: een lid waarvan de delta-signatuur tegengesteld dominant is
  (omhoog vs omlaag) aan het patroongemiddelde.
- Daarnaast gerapporteerd: `structural_similarity` (paarsgewijze
  signature-gelijkenis, max. 50 leden), `typical_delta`, `stages`,
  `software_variants`.

## 5. Cross-software alignment-confidence

```
alignment_confidence = min(95,
    0,4 × 100            (bewezen exacte blok-run tussen de originals)
  + 0,3 × contextsimil.  (positionele gelijkheid van 128 B-windows rond de regio)
  + 0,3 × min(100, supporting_projects / 3 × 100)
  − 10 × min(2, contradicting_evidence))
```

- `supporting_projects`: leden van het patroon die naar een binnen-512-B
  consistente doelpositie mappen.
- `contradicting_evidence`: dezelfde bronregio mapt naar disjuncte doelen
  (>512 B uit elkaar).
- Zonder blok-run: `status=unknown`, confidence 0 — er wordt niets geclaimd.

## 6. New BIN overall-confidence

```
overall = Σ(component × gewicht) / Σ(gewichten van aanwezige componenten)

componenten:  binary_similarity (0,40)   beste original-match
              pattern_confidence (0,25)  beste patroon-confidence
              context_alignment  (0,20)  contextscore beste patroonmatch
              structural_similarity (0,15) uit de V2-analyse
```

Componenten met waarde 0 tellen niet mee in de noemer (geen valse
verlaging door afwezig bewijs); alle componenten én gewichten staan in het
rapport. `evidence_summary` vermeldt aantallen (paren, patronen,
contradicties).

## 7. Evidence-graph

Tabel `evidence` koppelt bewijsstukken aan subjecten
(`subject_type`/`subject_id`, bv. `tuning_region/17`), met type, waarde,
offset, confidence, status en bron. `evidence_relations` legt relaties tussen
bewijsstukken (bv. een DNA-regio → diff-regio → OLS-binary). De OLS-graph
(`Service.ols_graph`) legt project→versie→binary→file-bomen vast met
relation_type + confidence en een expliciete `unknown_relationships`-lijst.

Voor iedere conclusie geldt de V3-§17-vorm: het antwoord op "waarom denkt
het systeem dit?" is een som van tellbare bewijsstukken
(bevestigde paren, gelijke signatures, software-varianten, regio's,
contradicties) plus de gebruikte formule — allemaal opvraagbaar via
`region_detail`, `patterns_detail` en de API.

## 8. Statuswoorden

| Woord | Betekenis | Waar |
|---|---|---|
| `DETECTED` | expliciet in het bestand aangetroffen | recognition (V2) |
| `POSSIBLE` | patroonindicatie zonder expliciete tag | recognition (V2) |
| `candidate` | kennis voorgesteld, wacht op review | regio's/patronen/DNA |
| `verified` / `rejected` | technician-beslissing | knowledge_reviews |
| `unknown` / `UNKNOWN RELATIONSHIP` | geen bewijs | regio-klasse, map-type, OLS-graph, alignering |
| `INSUFFICIENT EVIDENCE` | te weinig steun | New BIN-rapport zonder patroonmatches |
| `CONFLICTING EVIDENCE` | tegenstrijdige signals | contradictietellers, metadata_conflicts |

## 9. Wat bewust NIET geclaimd wordt

- Mapnamen/functies (Boost e.d.) — nooit zonder bronmetadata.
- Checksumregio's zonder cross-paar-bewijs.
- Code/softwaregebieden — blijven `unknown`.
- Gelijkheid van functie uit offsetoverlap — "offsetoverlap bewijst geen
  gelijke mapfunctie" (V2-noot, overgenomen).
- Geen ML/embeddings: alle features zijn uitlegbaar en deterministisch;
  een ML-laag komt pas als de dataset dat rechtvaardigt (V3-§32, ROADMAP).


## Audit als evidence (V5, §63)

Elke technicus-actie (approve/reject/correct/merge/split/mark_* op
patronen, regio's, identiteiten; OLS-objectrollen; pair-bevestiging;
herclassificatie) schrijft naast de review-record ook een regel in
`audit_log`: actor, actie, subject, before/after-state, reden, tijdstip.
De auditlog is backupbaar en herstelbaar (onderdeel van `backup`) —
conclusies blijven zo ook na restore verifieerbaar.
