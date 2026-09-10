# OLS Forensic Analysis Report

Datum: 2026-09-10

## Bron

- Bestand: `data/winols_projects/GASDROP_100119.ols`
- Analyse uitgevoerd op een beheerde read-only kopie.
- De originele bytes zijn niet gewijzigd.
- Grootte: `8,738,048` bytes
- SHA256: `dcfc2d8d03b035e7d559fa6fb4c80b492c79e937cf1df0729f0912605782e3e8`
- Header: `WinOLS File`
- Waargenomen softwaretekst: `OLS 5.0 (Windows)`

## Structuur

De eerste bytes en herhaalde records tonen een binary container met little-endian length-prefixed ASCII-records. Dit is waargenomen format-evidence, geen volledige formele WinOLS-parser.

- Zichtbare ASCII-segmenten over het volledige bestand: `8,719`
- Herkende length-prefixed ASCII-records volgens een conservatieve probe: `202`
- Volledige interne objectgrenzen: **niet bewezen**
- Binary-objecten: **UNKNOWN**
- Project-/version-tree: **NOT DECODED**
- Pointers/links tussen objecten: **NOT DECODED**

De bestaande importer beperkte zich eerder tot de eerste 100 unieke zichtbare strings. De observatielaag rapporteert nu aanvullende volledige-bestand-statistieken, maar maakt daar nog geen objecten of relaties van.

## Waargenomen projectmetadata

In zichtbare projecttekst komen onder andere voor:

- Voertuig: `BMW 4 Serie - Coupe`
- Motorvariant: `20i (2.0T) EU6d`
- Bouwjaar: `2014`
- Brandstof: `Turbo-Petrol`
- Cilinderinhoud: `1.998`
- Vermogen: `184.0PS / 135.3kW`
- ECU-type/benaming: `MG1CS003`
- ECU-context: `DME8.4.1-B48-LK-B20-M0-F032...`
- ECU/softwarereferentie: `R1C9J772BAJDX8`
- Engine code: `B48B20M0`
- Hardware/softwaregerelateerde tekst: `F032`, `Autotuner OBD`, `Eprom`, `Bosch`
- Binarybeschrijving: `Complete binary file`

De huidige generieke `ECU:`, `HW:`, `SW:`-tagreader vindt in dit bestand geen tags. Dat betekent niet dat metadata ontbreekt; de metadata heeft hier een andere, length-prefixed WinOLS-representatie.

## Waargenomen versies en rollen

De tekst bevat expliciete role/version-evidence:

- `Origineel`: 2 tekstvoorkomens
- Stage-gerelateerde tekst: 9 voorkomens
- Projectnaam met `Stage1+vmax`
- Projectnaam met `Stage1 + vmax + pops and bang`
- Projectnaam met `Stage1 + vmax + pops and bang` en suffix `(1)`
- `NOCS`: 7 voorkomens
- Gevonden importreferenties: 5

Dit is sterke aanwijzing dat het project één originele versie en meerdere gewijzigde/projectversies bevat. De exacte koppeling van ieder intern binary-object aan `Origineel`, `Stage1`, `Stage1+` of een andere versie is met deze analyse nog niet bewezen. Daarom worden deze teksten niet automatisch als objectrelatie opgeslagen.

## Importreferenties

Zichtbare bronreferenties bevatten onder andere:

- Een BMW MG1CS003 OBD VR raw BIN-pad uit `C:\Users\TCP\Desktop`
- Een Stage1+ raw BIN-pad uit `C:\Users\TCP\Desktop`
- Een Stage1 + vmax + pops and bang raw BIN-pad uit `C:\Users\TCP\Downloads`
- Een tweede versie met suffix `(1)` uit `C:\Users\TCP\Downloads`

De referenties zijn zichtbaar in de OLS-bytes. De huidige importer koppelt deze paden nog niet veilig aan afzonderlijke binary-objectrecords.

## Mapinformatie

- Zichtbare maplabels: `265` voorkomens van `Kaart`
- Voorbeelden: `Kaart "Bosch III 8"`, `Kaart "Bosch III 16/8`, `Kaart "Bosch II 8"`, `Kaart "Bosch 16"`
- Status: **VISIBLE LABELS ONLY**
- Mapnamen, adressen, dimensies, assen, units, factoren en waarden: **niet betrouwbaar geëxtraheerd**
- Maprelatie Original versus Stage: **niet bewezen**

De aanwezigheid van maplabels bewijst dat het project mapinformatie bevat, maar niet dat de huidige byteprobe de mapstructuur veilig kan reconstrueren.

## Binary-objecten en relaties

Waargenomen herhaalde ECU-/softwaregerelateerde tekst bevindt zich op meerdere offsets, waaronder rond afzonderlijke grote binaryregio's. Dit wijst op meerdere opgeslagen projectonderdelen, maar de grenzen en serialisatievelden zijn niet formeel gedecodeerd.

- Binary object count: **UNKNOWN**
- Object IDs: **UNKNOWN**
- Object sizes: **UNKNOWN**
- Original-to-Modified links: **UNKNOWN**
- Version-tree: **UNKNOWN**
- Pointer/reference graph: **UNKNOWN**
- Checksums/hashvelden per embedded binary: **UNKNOWN**

## Wat de huidige importer betrouwbaar doet

- Leest het OLS-bestand read-only.
- Slaat het volledige project op met SHA256/MD5/CRC32.
- Herkent de `WinOLS File`-signature.
- Rapporteert zichtbare ASCII-evidence over het volledige bestand.
- Rapporteert length-prefixed ASCII-evidence als format-observatie.
- Rapporteert zichtbare role/version-labels zonder objectrollen te verzinnen.
- Rapporteert zichtbare maplabel-aantallen zonder mapdata te gokken.
- Bewaart het project en zichtbare inventory traceerbaar via `winols_projects` en `ols_objects`.

## Wat nog niet betrouwbaar beschikbaar is

- Volledige WinOLS-objectextractie.
- Embedded raw BIN-extractie.
- Exacte Original/Stage-relaties per object.
- Volledige mapdefinities en waarden.
- Version-tree en pointer-relaties.
- Automatische koppeling van geëxporteerde BIN-bestanden aan hun OLS-object.

## Importerwijziging

De importer is alleen uitgebreid met een conservatieve forensic summary. Er is geen hypothetische `.ols`-parser toegevoegd en er wordt geen Original/Tuned-relatie uit alleen bestandsnamen of losse zichtbare strings geconstrueerd.

## Conclusie

Dit echte bestand bevat aantoonbaar projectmetadata, meerdere Original/Stage-gerelateerde projectteksten, meerdere raw BIN-importreferenties en honderden zichtbare maplabels. De huidige applicatie kan deze evidence veilig rapporteren, maar kan nog niet beweren dat alle WinOLS-objecten of relaties volledig zijn uitgelezen.

De volgende noodzakelijke stap voor betrouwbare Tuning DNA-opbouw is een ondersteunde WinOLS-export of een gecontroleerd voorbeeld waarvan bekend is welke object-ID, binary, version en maprelatie bij elkaar horen. Zonder die ground truth blijft de object- en relatieparser bewust `UNKNOWN`.
