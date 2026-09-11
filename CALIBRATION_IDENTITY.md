# CALIBRATION_IDENTITY.md — logische kalibratie-identiteit (§24–28)

## Probleem

Dezelfde logische kalibratie (bijv. "Ladedruckbegrenzung", "EGR-Menge")
staat in verschillende softwarevarianten op **verschillende offsets**.
Offset-gelijkenis is dus geen identiteitsbewijs; hij is hoogstens een
zwak signaal.

## Model

```
calibration_identities            één logische kalibratie
   id, structural_signature, status, confidence
   └── calibration_identity_members
         file_id, source_start, source_end, relation_confidence
         (zelfde identity, verschillende offsets per software)
```

Identiteitskenmerken (gewogen, alles zichtbaar in de score):
dimensies · as-signatuur · elementgrootte/endianness · layout ·
context/neighbour-signatuur · valuedistributie · structuursignatuur ·
OLS-relatie · Original/Tuned-bewijs · cross-software-bewijs.

**V4-scoreformule** (gemiddelde over members, zichtbaar per component):
`identity_align_conf = 0,45·signatuur + 0,25·context + 0,15·value-stats +
0,15·min(100, 50·OT-bewijs)`.

## Statussen (§25)

| Status | Betekenis | Voorwaarde (bewezen regels) |
|---|---|---|
| CANDIDATE | structuur lijkt overeen | structuursignatuur only |
| SUPPORTED | meerdere onafhankelijke signalen | ≥2 bewijsbronnen, 0 contradiccies |
| VERIFIED | technicus + bewijs | review door technicus; NOOIT automatisch |
| REJECTED | sterke contradictions | ≥2 contradicties & 0 support → automatisch |
| UNKNOWN | onvoldoende bewijs | expliciete uitkomst, geen gedwongen match |

## Negatief bewijs (§26)

Bewaard en meegewogen: andere as / andere dimensies / andere omliggende
structuur / tegensprekelijke OLS-relatie / andere valuesemantiek.
Sterke contradictions verlagen de score en kunnen REJECTED veroorzaken;
ambigu wordt NOOIT geforceerd naar match.

## Cross-software alignment (§27/§28)

`align_calibration_identity` zoekt per identity de regio in elke
softwarevariant; `align_pattern_across_software` doet dit op patroonniveau.
OLS-relaties zijn **constraints** als ze bewezen zijn (rol uit expliciete
WinOLS-metadata verslaat altijd inferentie); heuristische matches worden
als `inferred` gemarkeerd en worden nooit fact.

## Regels die altijd gelden (V4-bewijsregels)

- NOOIT identity op offset alleen.
- Zelfde tabeltype ≠ zelfde calibratie.
- scale/factor/unit uitsluitend uit echte OLS-data (geen defaults
  0,01/0,1/1); anders UNKNOWN.
- BYTE CHANGE ≠ CALIBRATION CHANGE; checksumgebieden leren nooit mee.
- VERIFIED blijft review-only; statistische claims pas na calibratie.
