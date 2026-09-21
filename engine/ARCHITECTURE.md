# TuningCore-architectuur — taalkeuze, ontwerp en Rust-pad

Opdracht: *"zoek op wat je nodig hebt en welke codeertaal de beste is; het gaat
om 1,2 miljoen ols-files (~8 TB)"*. Dit document legt de keuzes vast, met de
onderbouwing.

## 1. Wat de taak werkelijk is (belangrijk voor taalkeuze)

Per bestand doen we precies twee CPU-dingen:

1. **SHA-256 hashen** — de dominante kost bij 8 TB.
2. **OLS parsen** — length-prefixed records zoeken, versienamen/rollen bepalen,
   binary-grenzen bewijzen. Puur per-bestand, perfect parallelleel.

En twee I/O-dingen: **bestandssysteem wandelen** (1,2M entries) en
**resultaten wegschrijven** (SQLite). De rest is niets.

## 2. Taalonderzoek (internet, 2025-bronnen)

| Kandidaat | Ruwe CPU-snelheid | Geheugen | Praktisch nadeel vandaag |
|---|---|---|---|
| **Rust** | 2× sneller dan Go; ~26–60× dan Python | ~18 MB RSS (beste) | geen compiler in deze build-omgeving (geen cargo/rustc); trager ontwikkelen |
| **Go** | 2× langzamer dan Rust, nog steeds snel | prima | idem: geen toolchain hier |
| **C++** | gelijk aan Rust | prima | handmatig geheugenbeheer = crash-risico, tegenstrijdig met "crasht niet" |
| **Python + OpenSSL + multiprocessing** | hashing = C-snelheid (hashlib → OpenSSL); parse ~26–60× langzamer per kern, maar perfect parallel en de essentie is I/O | ~zwaarder | GIL → multiprocess nodig (opgelost in ontwerp) |

Kerninzichten uit het onderzoek:

- **SHA-256 gaat via OpenSSL in élke taal.** Go, Rust en Python-hashlib roepen
  uiteindelijk dezelfde geoptimaliseerde C-code aan (of hardware-SHA-NI).
  Gemeten in een 2015-ADFSL-vergelijking en later bevestigd: goed geschreven
  Python-hashen is C-snel; **de taal zegt daar vrijwel niets over uit**.
- **I/O-buffering weegt zwaarder dan taalkeuze.** Bij een hash-loop die de
  schijf voedt, bepalen leesbuffergroottes en volgorde het verschil tussen
  implementaties meer dan Rust vs. Go vs. Python.
- **De eindfles is de schijf.** 8 TB via USB-3 (~400 MB/s praktisch) ≈
  **5,5 uur minimaal lezen**, welke taal je ook kiest. Een snellere taal kan
  dat nooit onderbieden; een tragere die blokkeert wel.
- **CPU-bound parse paralleliseert in Python alleen met processen** (GIL) —
  daarom doet TuningCore dat ook (per-bestand worker, serial-fallback).
- Rust: rayon schaalt lineair; geheugen 10× lager; geen crashes uit
  geheugenfouten.

## 3. Besluit: Python-kern nú, Rust-hot-loop later

**Nú Python** omdat:

1. De twee echte kosten (SHA-256 en schijf-I/O) in Python **al C-snel** zijn.
2. Parse via multiprocessing op N kernen ~lineair schaalt; gemeten **106 OLS/s
   op 2 zwakke sandbox-cores** → 1,2M ≈ 3,1 uur; op de doelmachine korter.
3. **Geen compiler in deze omgeving**: Rust kan hier niet eens gebouwd worden —
   een Rust-kern nu leveren is een belofte, geen product.
4. Bewezen parserregels (V8) konden 1-op-1 overgezet én getest worden; in een
   nieuwe taal was elke regel opnieuw risico.
5. Stdlib-only: start in milliseconden, geen dependency-hel voor de gebruiker.

**Later Rust** via een strak afgebakend pad (zie §5): de hot loop (hash + parse)
wordt een Rust-bibliotheek achter dezelfde functies; Python blijft de
schil. De parser-API is bewust al geïsoleerd (`olsparse`) zodat dat een
vervanging-is, geen herbouw.

**Trigger voor de Rust-stap** (anders niet doen): parse < 40 OLS/s/kern in de
praktijk, of RAM-gebruik > 2 GB, of de gebruiker wil < 1 uur voor 1,2M.

## 4. Ontwerp in één oogopslag

```
engine/tuningcore/
  db.py         SQLite WAL, 9 tabellen, batch-transacties, errors-tabel
  scan.py       scandir-walk → size+mtime-cache → threads+OpenSSL-hash → batches van 200
  olsparse.py   bewezen parser (stdlib-only port): records, rollen, anchors, grenzen
  sample.py     synthetische OLS-builder (tests + bench) in echte WinOLS-structuur
  process.py    multiprocessing-parse: per-bestand isolatie, serial-fallback, checkpoints
  labels.py     rol/stage/add-on alleen uit expliciete namen
  cli.py        tc: scan / parse / status / pairs / bench met voortgang op elke fase
```

Dataflow: `scan` vult `files` (met sha) → `parse` leest alleen `.ols` zonder
vers project, parseert in workers, schrijft per batch `ols_projects`,
`ols_versions` en `pairs(suggested)` → checkpoints in `meta`.

Schaalbaarheidsfeiten:

- Onveranderde bestanden worden bij her-scan **gelezen op size+mtime alleen** —
  8 TB opnieuw scannen kost dan seconden, geen uren.
- Élke batch = één transactie + checkpoint: stroomuitval → exact hervatten.
- Parse-workers krijgen één pad per keer: één rottend bestand kost één
  foutregel, nooit de run. De multiprocess-pool heeft bovendien serial-fallback.

## 5. Rust-migratiepad (concreet, wanneer de trigger komt)

1. **Fase R1 — hash-loop**: Rust-lib (`tuningcore_hash`) met `sha256_file(path)`,
   via PyO3 bindings; vervangt `scan._hash_file`. Opbrengst beperkt (OpenSSL is
   al C), maar single-allocation en minder thread-overhead.
2. **Fase R2 — record-scanner**: `olsparse._length_prefixed_strings` +
   `_anchor_candidates` in Rust (SIMD-vriendelijk); Python roept aan en blijft
   de rollen/regels bepalen. Opbrengst: 10–50× op parse.
3. **Fase R3 — volledige parser in Rust**, Python alleen nog `db/scan/cli`.
4. Elke fase: zelfde pytest-suite als acceptatie (gedrag byte-voor-byte gelijk),
   bench-regressie in CI.

De API-vorm (`parse_ols(data) -> dict`) verandert niet — de GUI/app merkt er
niets van.
