# TuningCore — de nieuwe schone kern (v9.0)

TuningCore is de **helemaal nieuwe, van-nul-afgebouwde engine** voor heel grote
OLS-collecties (doel: **1,2 miljoen OLS-bestanden / ~8 TB**). Hij staat **naast**
de bestaande app (`app/`) — de app blijft werken zoals hij is; TuningCore is de
snelle kern waar de app later op aansluit.

## Waarom nieuw?

De oude generatie is per bestand uitgebreid en bewezen (200 tests), maar groeide
van klein naar groot. Voor miljoenen bestanden zijn vier dingen allesbepalend:
**snelheid, nooit crashen, altijd zichtbare voortgang, altijd hervatbaar**.
TuningCore is daarvanaf ontworpen:

| Principe | Hoe het hier is gebouwd |
|---|---|
| **Snel** | hashen met OpenSSL-snelheid via threads; parsen via multiprocessing (GIL-vrij); scans slaan ongewijzigde bestanden over via size+mtime; batches van 200 in één transactie; SQLite WAL |
| **Crasht niet** | élke per-file fout → `errors`-tabel, de loop loopt door; multiprocessing heeft serial-fallback; bronbestanden worden NOOIT gewijzigd |
| **Altijd zichtbaar** | élke fase print `% · snelheid · ETA · fouten` (geen GUI nodig, geen "reageert niet") |
| **Altijd hervatbaar** | checkpoint na élke batch; opnieuw starten = exact verder waar je was; tweede scan leest niets opnieuw |

## Bewijsregels (onveranderd overgenomen uit de bewezen generatie)

- Rollen (original/tuned) komen **uitsluitend** uit expliciete versienamen
  ("Origineel", "Stage 1", …). Niets gokken uit inhoud of grootte.
- Binary-grenzen alleen bij bewijs: expliciete import-header, of een
  identiteitsheader (`1/1/EDC17/…`) die op vaste afstand (≥1024) herhaalt
  direct na nul-padding, met pagina's die ≥99% identiek zijn.
- Importpad-records (`.bin`/`.ori`, stationsnotatie) zijn **geen** versienamen.
- Een bestand zonder élk bewijs (geen signatuur, geen versies, geen anchors)
  is geen OLS → foutregel, geen leeg project.
- Paren: original × tuned **binnen hetzelfde project** met gelijke binary-grootte
  → status `suggested` (de mens bevestigt; niets wordt automatisch "waar").

## Gebruik (vanaf de repo-root)

```bat
rem Windows (Python 3.11+):
set PYTHONPATH=engine

python -m tuningcore --db C:\tuning\core.db scan D:\Database\1 --preset MAX
python -m tuningcore --db C:\tuning\core.db scan D:\Database\2 --preset MAX
python -m tuningcore --db C:\tuning\core.db parse
python -m tuningcore --db C:\tuning\core.db status
python -m tuningcore --db C:\tuning\core.db pairs
python -m tuningcore --db C:\tuning\core.db bench --count 300 --size-kb 512
```

- `scan` — root scannen + hashen (herhaald aanroepen is goedkoop: cache).
- `parse` — alle nieuwe/gewijzigde OLS volledig parseren (parallel).
- `status` — tellingen: bestanden, OLS, versies per rol, paren, fouten.
- `pairs` — voorgestelde original→tuned paren tonen.
- `bench` — synthetische benchmark + extrapolatie naar 1,2M bestanden.

**Geen dependencies** — alleen Python 3.11+ standaardbibliotheek. Start in
milliseconden, ook op een kale machine.

## Gemeten op deze ontwikkelmachine (2 cores, zwakke sandbox)

- Scan: 300 bestanden / 314 MB in 0,21 s (RAM-cache; op USB wordt dit
  schijf-gebonden, ~200–500 MB/s → 8 TB ≈ 4,5–11 uur lezen, éénmalig).
- Parse: **106 OLS/s** met multiprocess-pool → **1,2M OLS ≈ 3,1 uur**.
- Op de doelmachine (meer cores) schaalt parse ~lineair mee (per-bestand werk).

## Architectuur & taalkeuze

Zie `ARCHITECTURE.md` naast dit bestand: waarom Python-nu, en het concrete
Rust-migratiepad voor de hot loop.
