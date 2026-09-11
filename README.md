# Tuning File AI Assistant — V2 + V3 Tuning Intelligence Engine

## V5: lokale bibliotheek (10 TB blijft staan)

**Library Mode**: registreer bronmappen (`D:\Tuning\`, `E:\WinOLS\`) en
indexeer ze zonder te kopiëren. Content (SHA256) is los van Location (pad):
duplicaten delen één content-object. Scans zijn incrementeel (hash-cache) en
hervatbaar; offline schijven breken niets. GUI-pagina **Library (V5)**,
CLI `library-add/library-list/library-scan/library-locations`, API
`/libraries*`. Zie [LOCAL_LIBRARY.md](LOCAL_LIBRARY.md).

## V3: leert van bevestigde Original → Tuned-paren

V3 voegt een intelligence-laag toe: **TuningRegions** (rijke wijzigingsregio's
met signatures en entropie), **Tuning DNA** (kandidaatkennis uit bevestigde
paren), **patroonclustering** (deterministisch, met stages en
software-varianten), **cross-software alignment** (patronen terugvinden op
andere offsets in andere software), **map-structuurdetectie zonder namen**,
**New BIN Analysis** (patronen + evidence + alle scorecomponenten),
**technician review** (approve/reject/correct/mark per regio en patroon),
hervatbare analyse-jobs en globaal zoeken. Alles UNKNOWN-first: zonder bewijs
geen conclusie, nooit mapnamen, nooit automatische BIN-modificatie.

Nieuwe GUI-pagina's: Patronen (V3), Region Viewer, New BIN Analyse (V3),
OLS Explorer, Zoeken. Nieuwe CLI: `rebuild-patterns`, `patterns`,
`align-pattern`, `regions`, `region`, `new-bin`, `map-structures`, `search`,
`ols-graph`, `jobs`, `review-knowledge`. Nieuwe API: `/patterns*`,
`/pairs/{id}/regions`, `/regions/{id}`, `/files/{id}/new-bin-report`,
`/files/{id}/map-structures`, `/search`, `/winols-projects/{id}/graph`,
`/jobs`.

Documentatie: [TUNING_DNA.md](TUNING_DNA.md) · [ARCHITECTURE.md](ARCHITECTURE.md)
· [EVIDENCE_MODEL.md](EVIDENCE_MODEL.md) · [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md)
· [ROADMAP.md](ROADMAP.md) · [STATUS.md](STATUS.md).

## V2 (basis)

Lokale Windows-desktopapp naast WinOLS 5. Importeer een BIN-bibliotheek en WinOLS `.ols`-projecten, controleer Original/Tuned-paren, vind overeenkomende originals en inspecteer daadwerkelijke wijzigingen. Er worden geen ECU-binaries aangepast of geflasht. Internet is alleen nodig voor de installatie van dependencies.

## V2: herkenning en softwarefamilies

V2 voegt reproduceerbare ECU-family fingerprints toe: entropie per segment, bytefrequentie, nul/`FF`-gebieden, segmenthashes en herhaalde segmenten. Bij import wordt daarnaast zichtbaar ASCII-bewijs geanalyseerd voor ECU-, hardware-, software- en calibration-identifiers. Resultaten gebruiken altijd `DETECTED`, `POSSIBLE` of `UNKNOWN` met confidence en offset; voertuig- of motorgegevens worden niet geraden.

In **ECU Families** maak je voorstellen uit herhaald BIN-bewijs. In **Knowledge Review** keurt een technicus voorstellen goed of af. Alleen goedgekeurde ECU-families worden gebruikt om de hierarchische matcher te filteren. Met drie of meer bestanden binnen een goedgekeurde ECU-family kun je signature-candidates ontdekken; na goedkeuring worden zij verified signatures. **Software Families**, **Calibration Families** en **Signatures** tonen de opgeslagen V2-kennis.

De analyzer rapporteert `Overall Match Score` met zichtbare componenten voor binary, ECU, hardware, software en calibration-bewijs. Bij meer dan `candidate_pool` bestanden worden kandidaten eerst op bestandsomvang en opgeslagen bytefrequentie gerangschikt; alleen de beste pool krijgt een volledige bytevergelijking. Standaard is de pool 250 en configureerbaar in `config.json`.

```powershell
python -m app.main identify "D:\ECU\unknown.bin"
python -m app.main propose-families
python -m app.main candidates
python -m app.main approve 1
python -m app.main reject 2
```

`python -m app` is equivalent to `python -m app.main`.

Een softwareversie-overstijgende regio-uitlijning is alleen analyse: exacte structurele blokreeksen kunnen corresponderende offsets tonen, maar V2 schrijft of genereert nooit een aangepaste BIN. Voor vergelijkbare tuninganalyse zijn altijd bevestigde original → tuned paren per softwareversie nodig.

## Starten op deze computer

Een lokale Python-runtime met dependencies staat in `.runtime/python` (niet opgenomen in Git). Start vanuit deze projectmap:

```powershell
.\start.ps1
```

Of rechtstreeks, als PowerShell scripts blokkeert:

```powershell
.\.runtime\python\python.exe -m app.main
```

## Installatie op een andere computer

Installeer Python 3.12+ voor Windows x64. Open PowerShell in de projectmap:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.main
```

SQLite wordt automatisch geïnitialiseerd. `python -m app.main init` initialiseert zonder venster. Gebruik `python -m app.main reset --confirm` om de huidige `data`-map veilig te verplaatsen naar een timestamped backup en met een lege database te starten. De reset verwijdert de backup niet. Gebruik in onderstaande voorbeelden het pad naar jouw Python in plaats van `python` als Python niet op PATH staat. `requirements-tested.txt` legt de tijdens ontwikkeling geteste dependencyversies vast.

## 1.000+ bestanden importeren

1. Ga naar **Files**. Kies `original`, `tuned` of `auto` en klik **Map importeren**.
2. Kies een bronmap; alle submappen worden doorzocht op `.bin`, `.ori` en `.ols`.
3. Importeer aparte original/tuned-mappen bij voorkeur met een expliciet type. `auto` herkent naamonderdelen zoals `original`, `ORI`, `tuned`, `MOD`, `stage1` en de directe bovenliggende map `originals`/`tuned`.
4. Onherkenbare namen krijgen `unknown`. Importeer die bron opnieuw met het juiste type om een getypeerd record aan te maken. De onbekende registratie blijft bestaan.
5. Importeer dezelfde bron opnieuw zonder dubbele records voor ongewijzigde inhoud en type. Een gewijzigde bron krijgt een nieuwe versie op basis van SHA256.

Import werkt op een achtergrondthread en rapporteert voortgang en fouten per bestand. De app bewaart inhoudsgeadresseerde kopieën in `data/originals`, `data/tuned`, `data/unknown` en `data/winols_projects`. Identieke inhoud binnen hetzelfde type deelt een kopie; namen, bronlocaties en metadata blijven afzonderlijke records. Beheerde data wordt overgeslagen bij mapimport.

Als bestanden als `unknown` verschijnen, klik **Unknown automatisch classificeren op evidence**. De app gebruikt expliciete labels, exacte SHA256-overeenkomsten en alleen een unieke binary-match van minimaal 99,5%. Wanneer Original en Tuned bijna even goed passen, blijft het bestand `unknown` en verschijnt het in `review`; zo wordt een verkeerde automatische classificatie voorkomen. Een andere numerieke bestandsnaam maakt bij exacte inhoud niet uit. De bron blijft onaangeraakt. Gekoppelde bestanden worden bewust geblokkeerd totdat het paar is gecorrigeerd. De herkenning kent onder andere `ori`, `orig`, `original`, `stock`, `oem`, `backup`, `mod`, `modified`, `tuned`, `remap`, `stage 1` en `stg2`.

```powershell
python -m app.main import "D:\ECU\originals" --kind original
python -m app.main import "D:\ECU\tuned" --kind tuned
python -m app.main import-ols "D:\WinOLS\Golf_stage1.ols"
python -m app.main classify 12 13 14 --kind original
python -m app.main auto-classify
```

Per bestand: grootte, SHA256, MD5, CRC32, SHA256-blokfingerprints en genormaliseerde byteverdeling. Alleen expliciete ASCII-tags `ECU:`, `HW:`, `SW:`, `CAL:` worden herkend. Dit is **geen algemene ECU-identificatiedatabase**. Conflicterende tags worden niet ingevuld. Voeg voertuig, motor, transmissie, stage, klant en project toe via **Metadata wijzigen**. Zoek op al deze velden in Files.

Intel HEX (`.hex`) is bewust niet ondersteund in V1: het heeft adressering/records en is niet gelijk aan een raw BIN. De standaardlimiet is 64 MiB per bestand en kan worden aangepast.

## Original/Tuned-paren

In **Original/Tuned Pairs**:

- **Automatische voorstellen zoeken** herkent bijvoorbeeld `original_001.bin` ↔ `tuned_001.bin`, `ABC123_original.bin` ↔ `ABC123_stage1.bin`, `ORI_ABC123.bin` ↔ `MOD_ABC123.bin`.
- Alleen één eenduidige original met dezelfde genormaliseerde naam en grootte levert een voorstel op. Dubbele originele namen worden niet automatisch opgelost. De naamzekerheid van 60 is een vaste heuristiek.
- Selecteer een voorstel, inspecteer **Diff**, en bevestig pas na controle.
- Of kies een original en tuned in de keuzelijsten en maak handmatig een bevestigd paar. Een original mag meerdere tuned varianten hebben.
- Selecteer meerdere paren met Ctrl+klik om hun wijzigingsgebieden te vergelijken. Het rapport toont overlap, de volledige gebieden aan beide kanten en of de original-SHA256 gelijk is.

```powershell
python -m app.main suggest-pairs
python -m app.main pair 1 2 --confirm
python -m app.main diff 1
```

Zonder `--confirm` blijft een CLI-paar onbevestigd. Pair-ID's en file-ID's zijn verschillende nummers; bekijk ze in de tabellen. Onbevestigde paren staan bij matches maar leveren nog geen bekende wijzigingsanalyse op.

## Nieuwe BIN analyseren

**Analyze BIN → Nieuwe BIN kiezen** doorzoekt alle geregistreerde originals, en toont de beste tien met redenen en bekende wijzigingen uit bevestigde paren. Het tekstpaneel bevat de volledige analyse, inputhash, metadata, fouten en diffs.

```powershell
python -m app.main analyze "D:\ECU\nieuwe_file.bin"
```

**Matchscore** = 100 × identieke bytes op dezelfde offset / grootste bestandsgrootte. Lengteverschillen tellen als verschillen. Er vindt geen herschikking of uitlijning van verschoven segmenten plaats. Aanvullende signalen: langste identieke reeks, identieke offsetblokken, gelijke grootte en overeenkomende/conflicterende metadata.

**Compatibility confidence** is apart: bij niet-identieke bytes `min(70, matchscore × 0.5 + 5 × aantal metadata-overeenkomsten)`. Verschillende grootte begrenst de score tot 20; een metadata-conflict tot 10. Identieke bytes krijgen 100, behalve bij metadata-conflicten. Niet-identieke bestanden blijven `unverified`. Deze waarden zijn niet statistisch gekalibreerd en zijn nooit toestemming om wijzigingen over te nemen of te flashen. Het dashboard telt scores ≥90 uit de laatste analyse, niet uit historische analyses.

Een match onder 60% krijgt `incompatible_base` en compatibiliteit 0. De app onderdrukt dan bekende wijzigingsgebieden, ook als een los bytegebied toevallig 100% gelijk is. Voor een versieverschil zijn minimaal beide bevestigde paren nodig: **A4 original → A4 tuned** en **A5 original → A5 tuned**. Met alleen een A5-tuned bestand kan de app niet bepalen welke bytes A5-basissoftware zijn en welke tuningwijzigingen; er wordt daarom geen aanpasbare of flashbare BIN gegenereerd.

De ranking gebruikt exacte byteovereenkomst, vervolgens compatibiliteitsindicatie, vervolgens ID. De scanner houdt slechts één kandidaat tegelijk in het geheugen plus de topresultaten. De rekentijd is lineair in de totale bibliotheekgrootte: 1.000 bestanden van 4 MiB betekent ongeveer 4 GiB lezen per analyse. Er is geen claim dat duizenden echte ECU-files al zijn gebenchmarkt. Het aparte Learning-scherm verandert de exacte ranking niet.

## Diff, clusters en learning

De diff-engine groepeert aangrenzende wijzigingen en maximaal `diff_merge_gap` ongewijzigde tussenbytes. Een bloklengte kan dus groter zijn dan het aantal gewijzigde bytes. Offsets zijn altijd **[start, einde)**: het einde telt niet mee. Toegevoegde/verwijderde bytes tellen ook mee.

In **Diff Viewer** klik je een gebied om een hexpagina te zien. Oranje markeert verschillen; `--` betekent ontbrekend. Je kunt naar elke offset springen (bijvoorbeeld `0x1200`) en 256 bytes tegelijk bekijken.

**Change Clusters** berekent DBSCAN-clusters over bevestigde paren op relatieve offset, logaritmische lengte en wijzigingsdichtheid. Alle leden met pair-ID en bytebereik staan in het rapport. De labels geven geen mapfunctie aan: verschillende ECU-families kunnen in hetzelfde structurele cluster zitten.

**Learning** bouwt bij iedere query een nearest-neighbor-index over opgeslagen bytehistogrammen. Nieuwe imports zijn direct beschikbaar. Dit is een uitbreidbare baseline, geen model dat tuningwaarden leert. Diff-features worden in SQLite opgeslagen; er zijn nog geen gevalideerde maplabels, predictiemodellen of tuningvoorstellen.

### Tuning DNA

Na controle van een Original → Tuned-paar kun je kandidaatkennis maken:

```powershell
python -m app.main generate-tuning-dna 12
python -m app.main tuning-dna
```

Tuning DNA bevat alleen traceerbare diff-regio's, relatieve offsets, context-hashes, gewijzigde bytes en bronhashes. Regio's krijgen geen automatische naam zoals `Boost` of `Torque Limiter`; zonder echte WinOLS-mapmetadata blijven ze `unknown`. Herhaalde structurele patronen worden als `candidate` verzameld. Er wordt geen BIN geschreven of aangepast.

## WinOLS `.ols`-projecten

`.ols` wordt als een **WinOLS-project** gelezen en veilig gekopieerd, gehasht en geïndexeerd. In **WinOLS** kun je een los project importeren, een geïmporteerde projectmap openen en een project inspecteren. De inspectie toont bestandsgrootte, SHA256/MD5/CRC32, de eerste 32 bytes als hex en maximaal 100 zichtbare ASCII-strings uit de eerste 2 MiB. Eventuele expliciete `ECU:`, `HW:`, `SW:` en `CAL:`-tags worden alleen als zichtbare tags getoond. Het bronbestand wordt nooit gewijzigd.

De projectlijst toont ook **Voorgesteld**: `original`, `tuned` of `unknown`. Dit wordt uitsluitend bepaald uit expliciete labels die in de zichtbare WinOLS-projecttekst staan, zoals `Original`, `OEM`, `Stage 1` of `Tuned`; de eigen projectnaam van WinOLS kan daardoor worden gebruikt als die als leesbare tekst in het `.ols`-bestand staat. Een nummer zonder label blijft `unknown`.

OLS is een propriëtair projectformaat en is geen raw ECU-BIN. De app slaat het OLS-project en de gevonden records/evidence op, maar zet embedded binary-objecten nog niet automatisch om naar `files`: onbekende bytes mogen niet zonder bewezen grenzen als Original of Tuned worden geïmporteerd. Exporteer de relevante original/tuned data in WinOLS naar raw `.bin` of `.ori`, en importeer die bestanden voor bytevergelijking. Dit voorkomt dat projectmetadata ten onrechte als ECU-data wordt geïnterpreteerd.

### V2 in drie delen

1. **Inventory:** zichtbare OLS-objecten worden read-only geregistreerd met interne naam, offset, grootte, ruwe label-evidence en status. Numerieke namen blijven `unknown`; opaque binary-objecten en WinOLS-mapdata krijgen `unsupported`/`not_available`.
2. **Relaties:** voor geëxporteerde raw `.bin`/`.ori`-bestanden maakt `pairs/suggest-binary` voorstellen op basis van byte-overeenkomst, metadata en gewijzigde regio's. Voorstellen blijven onbevestigd en zijn geen toestemming om tuning over te dragen.
3. **Review:** via **Unknown Objects** of de API/CLI kan een technicus een OLS-object expliciet markeren als `original`, `tuned`, `other` of `unknown`, met notitie en reviewer. De bron-`.ols` blijft ongewijzigd.

Handige CLI-commando's:

```powershell
python -m app.main ols-objects 1
python -m app.main review-ols-object 1 --role original --note "Gecontroleerd in WinOLS"
```

API-routes zijn `GET /winols-projects/{id}/objects`, `GET /winols-projects/{id}/structure`, `GET /ols-objects/unknown`, `POST /ols-objects/{id}/review` en `POST /pairs/suggest-binary`.

## Rapporten en WinOLS 5

1. Importeer de `.ols`-projectmap; de projecten zijn daarna doorzoekbaar in **WinOLS**.
2. Exporteer de relevante bestanden uit WinOLS als raw original/tuned BIN en importeer die.
3. Controleer paren en analyseer een nieuwe original.
4. Exporteer een analyse- of diffrapport naar een gekozen map.
5. Open de projectmap via **WinOLS → WinOLS-projectmap openen**.
6. Open de originele BIN handmatig in WinOLS 5 en controleer de gerapporteerde offsets.
7. De technicus identificeert maps en maakt eventuele aanpassingen uitsluitend in WinOLS.
8. Importeer de resulterende BIN als tuned voor een nieuwe vergelijking.

Elk exportbestand krijgt een UUID-naam en wordt exclusief aangemaakt: JSON met volledige analyse, CSV met diffgebieden en pair-ID's, en een SHA256-manifest van beide rapporten. Input-SHA256's staan in de JSON. Er wordt geen gewijzigde BIN gegenereerd. Een analyzerexport bevat ook de bekende diffs in CSV. Rapporten zonder diffgebieden leveren alleen een CSV-header. CSV is een leesbaar controlerapport, geen beloofd WinOLS-importformaat. De app leest geen `.ols`-projecten en bestuurt geen WinOLS-executable.

## V5-productlaag (jobs, audit, backup, rapporten)

- **Library analyseren**: `library-analyze` (hervatbaar/pauzeerbaar),
  GUI-knop op de Library-pagina; content wordt per SHA256 precies één keer
  diep geanalyseerd.
- **New BIN tegen de library**: `new-bin-library <pad>` — multi-stage
  (exacte SHA256 → grootte → fingerprint → shortlist → kennis); een exacte
  hit hergebruikt bestaande kennis zonder heranalyse.
- **Watch folders**: `library-watch <root_id> --on [--auto-analyze]` —
  NOOIT automatische Original/Tuned-rollen (alleen exact-duplicate
  bewijsregel, expliciet aan te zetten).
- **Job-manager**: `job pause|resume|cancel|show <id>` + GUI Jobs & Audit.
- **Auditlog**: elke review/correctie/bevestiging wordt gelogd (§63) en
  meegebacket.
- **Backup/restore/health**: `backup --dir D`, `restore <map>` (met
  SHA256-manifestverificatie + veiligheidsbackup), `health`.
- **Rapportexport**: `report new_bin <id> --format md` (json/csv/md/html).
- **Zoeken**: `library-search <term>` (FTS5, hash-prefix wordt ondersteund).

## API

De desktop gebruikt de servicelaag rechtstreeks; een API-server is optioneel:

```powershell
python -m app.main api
```

Bindt alleen op `127.0.0.1:8765`. Het startscherm toont een willekeurige API-key; stuur die als `X-API-Key`. Met `TUNING_API_TOKEN` kun je een eigen key van minimaal 24 tekens instellen. Deel deze niet: de API mag lokale bestanden importeren en metadata wijzigen. CORS wordt niet ingeschakeld. Routes staan op `http://127.0.0.1:8765/docs`; gebruik een API-client met de header. Import, metadata, pairs, diff/hex, analyzer, clusters, strategievergelijking en diffrapportexport zijn beschikbaar.

## Configuratie en data

`config.json`: `data_dir`, `max_file_mb`, `top_matches`, `block_size`, `diff_merge_gap`. Met `TUNING_CONFIG` kies je een ander configuratiebestand; relatieve datapaden worden ten opzichte van dat bestand opgelost. Herstart na wijzigen. Verander de blokgrootte bij voorkeur niet midden in een bestaande bibliotheek; historische fingerprints bewaren hun eigen blokgrootte.

SQLite-tabellen: `files`, `winols_projects`, `file_pairs`, `fingerprints`, `diffs`, `diff_features`. Foreign keys en WAL zijn ingeschakeld. Fouten en imports/metadatawijzigingen worden gelogd in `data/app.log` met rotatie. Hashes van beheerde inputs worden vóór analyse opnieuw gecontroleerd. Een importfout laat andere imports doorgaan; een mislukte import kan een ongebruikte kopie achterlaten maar overschrijft geen bestaande bron.

Maak back-ups van de volledige `data`-map **nadat de app en API zijn afgesloten**. Verplaats een bestaande bibliotheek niet los van de database: V1 bewaart absolute paden naar de kopieën. Geen verwijder- of automatische migratiefunctie in deze versie.

## Testen en synthetische data

```powershell
python scripts/generate_demo.py demo_files
python -m app.main import demo_files
python -m app.main suggest-pairs
python -m pytest -q
```

De demo bevat uitsluitend willekeurige testdata met `DEMO_ONLY`-metadata: 64 KiB, drie bekende gewijzigde gebieden (128 + 80 + 42 = 250 bytes), plus een Stage 2-variant met 32 extra gewijzigde bytes. De generator weigert bestanden te overschrijven. `new_demo.bin` krijgt bij automatische import `unknown`; gebruik hem als analyzerinput. De tests werken in tijdelijke mappen en gebruiken geen echte ECU-files.

De suite controleert hashes, metadata, random diffs tegen een onafhankelijke byte-oracle, toevoegingen/verwijderingen, pairing, herhaalde import, ranking, integriteitsfouten, clusters, nearest neighbors, export, strategieën, API-authenticatie en een offscreen Qt-venster.

## Projectindeling en vervolgstappen

`app/analysis` bevat readers, fingerprints, metadata, similarity, diff en clustering. `app/database` beheert schema en repository. `app/matching` bevat de volledige scan; `app/learning` de nearest-neighbor-baseline. `app/service.py` verbindt ze voor `app/ui`, CLI en `app/api.py`. `app/winols` verzorgt mapnavigatie en rapportexport. `scripts` bevat de demo-generator en `tests` de verificatie.

V1 omvat deze lokale workflow. V2 vraagt een betrouwbare ECU/SW/HW-identificatiedatabase met herkomst en validatie op echte files. V3 kan gevalideerde mapdetectie toevoegen. Geavanceerde classificatie, tuningvoorstellen en toepassing van wijzigingen zijn nog niet geïmplementeerd. Klant/project zijn nu doorzoekbare metadata, geen afzonderlijk CRM.

Gebruikte officiële API-documentatie: [Qt threads/signals](https://doc.qt.io/qtforpython-6/examples/example_widgets_thread_signals.html) en [FastAPI](https://fastapi.tiangolo.com/tutorial/first-steps/).
