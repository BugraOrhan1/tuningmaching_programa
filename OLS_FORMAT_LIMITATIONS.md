# OLS_FORMAT_LIMITATIONS.md — wat het gesloten WinOLS-formaat wél en niet toeStaAt (§74)

WinOLS `.ols` is een **gesloten, propriëtair formaat**. Er is geen
publieke specificatie en er bestaat geen gedocumenteerde open parser
(webresearch 2024–2026: niets vindbaars). Dit document is de eerlijke
grensbepaling van dit product.

## Wat we wél aantoonbaar kunnen (uit de bestandsinhoud zelf)

- **Containerstructuur**: record-offsets, lengtes, recordtypes, payload-
  grenzen, ouder/kind-verwijzingen zoals die letterlijk in het bestand
  staan (`ols_records`, `ols_record_references`, `ols_binaries` met
  payload_start/payload_length/end_boundary/padding — boundary-safe,
  padding wordt nooit als ECU-payload behandeld).
- **Expliciete tekst-metadata** die het bestand zelf biedt (bijv.
  versielabels zoals "Original"/"Stage 1" waar letterlijk aanwezig):
  gebruikt als **sterkste rolbewijs** (rolvolgorde: expliciete WinOLS-
  metadata > version/project-relatie > object-relatie > binary comparison
  > calibration evidence > zwakke signalen).
- **Extractie + dedup**: versie-binaries op bewezen grenzen, gehasht
  (SHA256), gededupliceerd; geëxtraheerde binaries krijgen de volledige
  analyse-keten (recognise → diff → DNA → patronen).
- **Cache per content**: OLS-analyse wordt gecacht op SHA256 + parser-
  versie; identieke OLS-inhoud wordt nooit twee keer geparsed.

## Wat NIET bewezen kan worden — en dus UNKNOWN blijft

| Verleiding | Onze beslissing |
|---|---|
| ASCII-recordnaam zoals "Kaart"/"Map" lezen als echte map | NOOIT: string ≠ objectbewijs; record blijft UNKNOWN_RECORD_TYPE |
| Numerieke/opaque objectnamen interpreteren (Boost/Torque/Ignition) | UNKNOWN tenzij bronbewijs of technicus |
| Original/Tuned-rollen raden uit volgorde/grootte | alleen uit expliciete metadata/bewijsvolgorde hierboven |
| scale/factor/unit gokken | alleen uit echte OLS-data; anders UNKNOWN |
| Objectsemantiek claimen ("dat is de KFMI") | UNKNOWN — insufficient evidence |

## Hoe het product daarmee omgaat (§74-beleid)

1. **Raw evidence first**: elk record/object wordt met offset/lengte/type/
   raw-hash/gedecodeerde velden bewaard, inclusief bewijsstatus.
2. **Candidate, never fact**: structuurkandidaten (maps/assen/objecten)
   zijn kandidaten met confidence + evidence, statussen
   VERIFIED/SUPPORTED/CANDIDATE/REJECTED/UNKNOWN.
3. **Technicus-bewijs**: review (approve/reject/correct/mark_*) is een
   first-class bewijsbron en wordt gelogd (auditlog) en meegewogen.
4. **Reproduceerbaarheid**: parser-versie wordt bij de cache bewaard;
   een nieuwere parser invalideert alléén de OLS-cachelaag (§44).

## Praktische gevolg voor de gebruiker

De applicatie zal eerder "UNKNOWN — insufficient evidence" zeggen dan een
aannemelijke naam verzinnen. Dat is een **functie**, geen beperking van
het product: elke getoonde conclusie is herleidbaar naar letterlijk
bewijs in uw eigen bestanden.
