# OLS Structure Report V2.7

Datum: 2026-09-10
Bron: `data/winols_projects/GASDROP_100119.ols`

## Bestand

| Eigenschap | Waarde |
|---|---|
| Header | `WinOLS File` |
| WinOLS tekst | `OLS 5.0 (Windows)` |
| Grootte | `8,738,048` bytes |
| SHA256 | `dcfc2d8d03b035e7d559fa6fb4c80b492c79e937cf1df0729f0912605782e3e8` |
| Mutatie bronbestand | Geen |

## Herkende records

De huidige veilige probe herkent little-endian length-prefixed ASCII-records. Hij claimt niet dat ieder record een volledig WinOLS-object is.

- Length-prefixed records: `110`
- Recordtypen:
  - `header`
  - `project_metadata`
  - `version_or_role_label`
  - `binary_reference`
  - `map_label`
  - `unknown_ascii_record`
- `Kaart`-records binnen de herkende recordstructuur: `21`
- Ruwe zichtbare `Kaart`-tekstvoorkomens in het volledige bestand: `265`

## Projectmetadata

Waargenomen waarden zijn onder andere:

- BMW 4 Serie - Coupe
- 20i (2.0T) EU6d
- 2014
- B48B20M0
- Bosch
- MG1CS003
- DME8.4.1-B48-LK-B20-M0-F032...
- R1C9J772BAJDX8
- Complete binary file
- Autotuner OBD

De metadata wordt als waargenomen tekst opgeslagen. De generieke `ECU:`/`SW:`-tagextractor is niet voldoende voor dit OLS-formaat.

## Versions en rollen

De volgende labels zijn aangetroffen:

- `Origineel`
- `Stage1+vmax`
- `Stage1 + vmax + pops and bang`
- een tweede Stage-record met suffix `(1)`

De labels zijn betrouwbaar waargenomen als records, maar de koppeling naar binary-objecten is niet bewezen. Daarom worden version-relaties opgeslagen als:

```text
relation_type = target_unknown
confidence = 0
```

Er wordt dus niet beweerd:

```text
Original -> Binary X
Stage 1 -> Binary Y
```

## Binary evidence

Er is ten minste één record met `Complete binary file`/binary-reference-evidence aangetroffen. De huidige parser kan de embedded binarygrenzen, startoffset, lengte, checksum en object-ID niet betrouwbaar bepalen.

| Veld | Status |
|---|---|
| Binary record evidence | AVAILABLE |
| Binary object count | UNKNOWN |
| Binary start/offset | UNKNOWN |
| Binary length | UNKNOWN |
| Binary content extraction | NOT AVAILABLE |
| Binary SHA256 per object | NOT AVAILABLE |
| Version -> binary link | UNKNOWN |

De database maakt hiervoor een `ols_binaries`-record met `status=boundary_unknown`, `content_available=0` en confidence `0`.

### Externe raw-referenties

Wanneer een OLS-record een bestaand lokaal `.bin`- of `.ori`-pad bevat, indexeert de app dat bestand automatisch in `files` als `unknown` en koppelt het via `ols_binaries` aan het project. De bestandsnaam wordt niet gebruikt om Original/Tuned te gokken. In deze workspace verwijzen de aangetroffen paden naar `C:\Users\TCP\...` en bestaan ze niet, waardoor ze hier `external_reference_missing` blijven.

## Map evidence

Er zijn zichtbare maplabels gevonden, waaronder `Kaart "Bosch III 8"` en `Kaart "Bosch II 8"`.

De database slaat de 21 structureel herkende maplabels op als `ols_map_objects` met:

- ruwe mapnaam;
- bron-record en offset;
- `status=label_only`;
- geen verzonnen address, size, dimensions, axis, factor, unit of mapwaarden.

Mapobjecten zijn dus nog niet gekoppeld aan een binary, version of calibration region.

## References en evidence

Binary-reference records worden opgeslagen in `ols_record_references` met:

- bronrecord;
- `reference_type=binary_target_unknown`;
- confidence `0`;
- evidence dat de tekstreferentie is gezien, maar het doel niet is gedecodeerd.

Version-labelrecords worden opgeslagen in `ols_version_relations` met:

- bronrecord;
- `relation_type=target_unknown`;
- confidence `0`;
- evidence dat alleen het label is gezien.

## Object graph status

```text
OLS
  -> project: OBSERVED
      -> records: PARTIAL, 110 records
          -> version labels: OBSERVED
          -> binary references: OBSERVED, target UNKNOWN
          -> map labels: OBSERVED, object semantics UNKNOWN
          -> binaries: UNKNOWN boundaries
          -> version tree: NOT DECODED
          -> pointers/references: NOT DECODED
```

## Evidence tabel

| Evidence | Betekenis | Confidence |
|---|---|---:|
| `WinOLS File` op offset 4 | Bekende headertekst waargenomen | 100% |
| Little-endian lengte + ASCII-record | Recordformaat-probe past op bytes | 70-100% |
| `Origineel` record | Original-label is aanwezig | 100% voor label, 0% voor binary-link |
| Stage-projectnaam | Stage-label is aanwezig | 100% voor label, 0% voor binary-link |
| `Complete binary file` | Binary-gerelateerde metadata waargenomen | 100% voor tekst, 0% voor boundary |
| `Kaart ...` record | Maplabel is aanwezig | 100% voor label, 0% voor mapobject-link |
| Geïmporteerd BIN-pad | Bronreferentie als tekst waargenomen | 100% voor tekst, 0% voor target-link |

## V2.7 status

**NOT READY** voor volledige OLS-structuurreconstructie.

V2.7 heeft nu een veilige, traceerbare record/evidence-laag. De ontbrekende stap is het betrouwbaar decoderen van WinOLS-objectgrenzen, embedded binaries, IDs, pointers en maprelaties. Daarvoor is aanvullende ground truth nodig: een ondersteunde WinOLS-export of een gecontroleerd project waarvan in WinOLS bekend is welk object/binary/version bij elkaar hoort.

Er is geen automatische tuning en er wordt geen BIN gewijzigd.
