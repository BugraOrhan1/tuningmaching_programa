# LOCAL_LIBRARY.md — WinOLS-achtige lokale bibliotheek (V5 Phase 2)

## Principe

De productiemodus is een **lokale projectbibliotheek**: bronbestanden
(OLS/BIN/ORI) blijven op hun eigen schijf (`D:\Tuning\`, `E:\WinOLS\`, …).
De applicatie kopieert ze **niet** naar `data/`; de database bewaart alleen
pad, identiteit (SHA256/MD5/CRC32), grootte, timestamps en status.

```
Library Root (D:\Tuning\)
   └── File Location   (pad + status)         → blijft op de schijf
         └── Content Object   (SHA256)        → één keer, gedeeld
               └── (kennis: OLS-project, TuningRegion, Identity, …)
```

- **Content ≠ Location.** Identieke SHA256 = één content-object, meerdere
  locaties. Kennis wordt per content één keer opgebouwd (geen dubbele
  analyse, geen dubbele kennis).
- **Geen massa-kopie.** De bestaande managed-copy-import blijft bestaan voor
  development/demo; de productiemodus is de Library.
- **Read-only.** De scanner opent bestanden uitsluitend lezend; een
  scan wijzigt/verplaatst/hernoemt/verwijdert nooit een bronbestand
  (getest: SHA256 van bronbestanden vóór/na scan identiek).

## Database (schema v9, additief)

| Tabel | Inhoud |
|---|---|
| `library_roots` | geregistreerde roots: name, path (UNIQUE), status ONLINE/OFFLINE, file/content-tellers, health, config (resource-preset) |
| `content_objects` | sha256 (UNIQUE), md5, crc32, size, file_type, analysis_state |
| `file_locations` | root_id, content_id, path (UNIQUE per root), filename, extension, size, mtime/ctime, scan_status, analysis_state |
| `library_scans` | scan-sessies: status running/done/interrupted, checkpoint (last_path), stats |

## Scanstatussen (§8)

`NEW` · `UNCHANGED` (size+mtime ongewijzigd → **geen rehash**) · `MODIFIED`
(opnieuw gehasht) · `MOVED` (inhoud gelijk, pad weg + pad erbij → **zelfde
content-ID, kennis wordt niet herbouwd**) · `MISSING` (pad weg; wordt NIET
gezet bij een offline schijf) · `DUPLICATE` (inhoud bestaat al op een andere
locatie; eerste locatie blijft NEW) · `ERROR` (bijv. onleesbaar/corrupt — de
scan loopt door).

## Incrementeel en hervatbaar

- Eerste scan: alles ontdekken → hashen → indexeren.
- Volgende scans: alleen NEW/MODIFIED worden gehasht; ongewijzigde bestanden
  worden herkend aan size+mtime (hash-cache). Gemeten: 0 rehashes op een
  ongewijzigde 10.000-files library.
- Checkpoints: interactieve scans (met progress, bv. GUI) schrijven per
  bestand een checkpoint; niet-interactieve scans elke 500 bestanden
  (`scan_batch` instelbaar). Bij crash/onderbreking: status `interrupted`,
  hervatten zet exact voort na `last_path` en verwerkt elk bezocht bestand
  opnieuw (niets wordt blind als gelijk aangenomen).
- Een corrupt/onleesbaar bestand stopt de scan niet (ERROR-regel, scan gaat
  verder).

## Offline schijven (§37)

Bestaat de root niet tijdens een scan, dan wordt de root `OFFLINE` en blijft
de database volledig bruikbaar; locaties worden **niet** als MISSING
gemarkeerd. Als de schijf terugkomt: opnieuw scannen → status weer ONLINE,
statussen worden bijgewerkt.

## Resource presets (§32)

Root-config bevat `preset`: `LOW`/`BALANCED`/`HIGH` (worker-telling). De
scanner is single-pass I/O (1 MB-chunks, SHA256+MD5+CRC32 in één leesbeurt).
Uitbreiding naar parallelle hash-workers is voorbereid via de presets.

## OLS-first (volgende fasen)

`.ols` wordt als first-class type geïndexeerd (`file_type='ols'`). Diepere
OLS-projectverwerking (project/versions/relations/objects bovenop de index,
met `parser_version`-cache) is de volgende fase — de index houwt de plek en
identiteit al vast, zodat ongewijzigde OLS-bestanden niet opnieuw geparsed
hoeven te worden.

## Gebruik

- GUI: pagina **Library (V5)** → root toevoegen → scannen (of hervatten) →
  zoeken op naam/pad/SHA256, opslagcijfers direct zichtbaar.
- CLI: `library-add <pad> [--name]`, `library-list`, `library-scan <id>
  [--resume]`, `library-locations <id> [term]`.
- API: `GET /libraries`, `POST /libraries`, `POST /libraries/{id}/scan`,
  `GET /libraries/{id}/locations?q=`, `GET /libraries/{id}/scans`,
  `GET /contents/{id}/locations`.

## Benchmark (10.000 files, deze machine)

```
EERSTE SCAN:        10.000 files in 34,9 s  (288 files/s, 10.000 gehasht)
INCREMENTELE SCAN:  22,0 s  (455 files/s, 0 opnieuw gehasht)
NA 1 WIJZIGING:     21,5 s  (exact 1 rehash, 1 MODIFIED)
UNIEK/DUPLICAAT:    1.001 unieke contents · 9.000 duplicaat-locaties
DATABASE:           4,2 MB (metadata alleen; brondata blijft op de schijf)
BRONBESTANDEN:      ongewijzigd (SHA256-verificatie op steekproef)
```

Extrapolatie (lineair, single worker): 1 M files ≈ 1 uur initiële scan;
de incrementele doorlooptijd wordt gedomineerd door de filesystem-walk
(~450+ files/s single-threaded) en schaalt verder met worker-uitbreiding.
