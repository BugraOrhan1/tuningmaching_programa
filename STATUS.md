# Applicatiestatus

Datum: 2026-09-10 (bijgewerkt na V3-ronde)

## V8.4-status (Tune Bouwer uitgebreid: multi-add-on, stages 1-5, 13 add-ons) — actueel

**163 passed / 1 guard-skip groen.**

- **Multi-add-on**: GUI heeft nu een aanvinklijst (meerdere add-ons tegelijk);
  `_plan_recipes()` kiest greedy het beste dekkende recept en ketent
  bevestigde recepten voor ontbrekende add-ons (`chain` toont alle stappen).
- **Overlap-veiligheid**: `_apply_pair(applied_ranges)` slaat regio's die een
  eerder recept in de keten al wijzigde netjes over ("eerder recept") — nooit
  dubbel schrijven; elke regio blijft individueel ≥98%-bewijsplichtig.
- **Stages 1-5** (was 1-3); **add-ons 7 → 13**: + decat, antilag,
  launch_control, e85, swirl_off, cold_start_off (tokens o.a. "de-cat",
  "anti-lag", "flex fuel", "kaltstart off").
- Tests: nieuwe labels, echte 2-recepten-keten (300 stage / 900 vmax /
  1500 pops, overlap-skip bewezen), overlap-skip direct op _apply_pair;
  bestaande 12 tune-tests onveranderd groen (gedrag achterwaarts-compatibel).

## V8.3-status (OLS-extracten: betekenisvolle namen + herkomst + ECU-herkenning) — actueel

**160 passed / 1 skipped (guard) groen.** Vraag: "ols_versie_101.bin — hoe komt
hij erachter welke auto het is?"

- **`ols_extract_filename()`**: extracten heten nu
  `<project>_v<index>[_<versienaam>].bin` (bv. `GASDROP_100119_v101_Stage1.bin`)
  i.p.v. de nietszeggende naam; een échte bronbestandsnaam wint altijd.
- **Herkomst in Files**: Project (= projectbestand) en Stage (= versienaam)
  worden gevuld; bij bestaande rijen alléén lege kolommen (backfill,
  gebruikersmetadata blijft heilig).
- **ECU-herkenning uit de bytes**: `recognize()` bij extractie; expliciet
  gevonden ECU-familie in de ECU-kolom; wat er niet in staat blijft onbekend.

## V8.2-status (automatisch paren na BIN-analyse) — actueel

**158/158 tests groen.**

- **`service.auto_pair_after_analysis(file_id, report)`**: na élke analyse
  wordt een unknown dat uniek en sterk matcht met één bekend original
  automatisch 'tuned' gezet en gepaard — **≥95% = bevestigd paar**,
  **90–95% = unconfirmed suggestie** (reviewwachtrij). Veiligheidsregels:
  inhoud identiek aan original → géén paar (geen tuning); tweede kandidaat
  binnen 2% → ambigu, niets; ECU-metadata-conflict → niets; bestand al
  getypeerd → niets. Audit-regel per actie.
- Ingebouwd in `service.analyze` (GUI snel-analyse, CLI en API): het
  geanalyseerde bestand wordt idempotent in de database gezet (bestaande
  rij hergebruikt, geen duplicaten) en gepaard; resultaat staat in
  `report['auto_pair']`.
- GUI: statusbalk-melding na analyse ("Auto-paar BEVESTIGD/VOORGESTELD…"),
  volledige details in het rapport-JSON.
- Tests: bevestigd-paar (+audit), 90–95-suggestieband, identiek-skip,
  ambigue-skip (bestand blijft unknown).

## V8.1-status (bugs uit de praktijk gefixt: []-telling, 'path'-KeyError, naamherkenning) — actueel

**155/155 tests groen.** Aanleiding: screenshots van de gebruiker.

- **"Automatisch geclassificeerd: []"**: de telling was de ruwe lijst — nu
  `len(updated)` (service + weergave); legacy-lijsten in de samenvatting
  worden nog steeds netjes geteld.
- **"Actie niet uitgevoerd: 'path'"**: foutregels van process_all_roots
  gebruiken sleutel 'root' (niet 'path') → KeyError in de samenvatting.
  Nu `_bulk_result_lines()` (getest, zonder dialoog):robust tegen
  path/root/filename + toont bij 0 voortgang een behulpzame tip
  (1× Original + 1× Tuned handmatig → daarna automatiseert de rest).
- **Auto-classificatie deed niets bij praktijknamen**: `classify_label`
  kende geen Nederlandse woorden en geen tuning-jargon. Uitgebreid met
  originals: origineel/originele/orgineel/factory/fabriek/standaard/standard;
  tuned: pops/pop/bang (incl. "pops and bang"), vmax/v-max, decat/de-cat,
  dpf/egr/adblue/scr + off/uit/delete, antilag, e85, chiptuning, optpower,
  stage 1-4. Volgorde: tuned eerst (conservatief); gewone namen blijven
  unknown. End-to-end getest via process_root_bulk.

## V8.0-status (volledige automatisering: bulk = hele pijplijn; ALLES-knop; slim advies)

**152/152 tests groen.**

- **process_root_bulk is nu de complete pijplijn**: scan → importeren →
  auto_classify_evidence (uniek bewijs) → suggest + auto_confirm_binary_pairs
  (label+≥90) → run_pattern_job (leren uit bevestigde paren). Elke stap
  try/except-wrapped: bulk kan nooit breken; alle sleutels in het resultaat
  (auto_classified, pairs_auto_confirmed/review, patterns_built).
- **service.process_all_roots**: élke root achter elkaar; offline schijven
  worden netjes overgeslagen (OFFLINE-status nu doorgegeven in bulk-resultaat);
  alles optellen in één samenvatting.
- **GUI**: blauwe "🤖 ALLES automatisch afhandelen"-knop op Library;
  dashboard toont "🤖 Advies: …" (belangrijkste volgende stap, uit de
  assistent); eerste-start-wizard checkbox start nu de volledige automatisering
  i.p.v. alléén een scan.
- Assistent-teksten bijgewerkt (auto-confirm + automatisch patronen leren).
- Tests: volledige-pijplijn-bulk, process_all_roots (incl. offline-root),
  bestaande bulk/wizard-tests blijven groen.

## V7.9-status (lokale Assistent + auto-confirm van sterke BIN-paren) — actueel

**150/150 tests groen.**

- **Assistent** (START, Eenvoudig-modus): lokale agent (app/assistant.py)
  die live meekijkt in de database — intents: volgende stappen, waarom
  matcht mijn BIN niet (drempel/bewijs + laatste rapport), reviewwachtrij,
  tune-recepten, snelheid; antwoordt met échte cijfers, volledig offline
  (past bij geen-cloud-eis). GUI: chatlog + 5 snelle vragen + vrije vraag.
- **auto_confirm_binary_pairs(min_score=90)**: losse BIN-paren worden
  automatisch bevestigd ALLEEN bij expliciet tuning-label (stage/pops&
  bang/vmax/dpf/…) + score ≥90 + geen tegenstrijdige metadata; de rest
  blijft bewust in review. Ingebouwd in `process_root_bulk` (suggereert
  eerst, bevestigt dan); samenvatting toont "automatisch bevestigd / voor
  review"; audit-regel per bevestiging.
- Nav: 27 pagina's / 33 nav-items; Assistent in SIMPLE_PAGES (11).
- Tests: assistent-intents + GUI-chat + auto-confirm-label/score-regel +
  bulk-auto-confirm.

## V7.8-status (Eenvoudig/Expert-modus + root-bulk-verwerking "1 knop")

**146/146 tests groen.**

- **⭐ Root volledig verwerken** (Library-pagina): één knop — scant de root en
  verwerkt daarna AUTOMATISCH élke locatie (BIN/ORI → Files met skip-existing
  zonder lezen; elk .ols volledig). Keyset-paginering (id>) schaalt naar
  miljoenen; hervatbaar via run-checkpoints (`root_bulk`), resume na crash
  getest; tweede keer ~gratis (alles overgeslagen).
- **Eenvoudig/Expert-modus** boven de navigatie: Eenvoudig = 10 dagelijkse
  pagina's + sectiekoppen alleen bij zichtbare pagina's; Expert = alles (26).
  Keuze blijft bewaard (data/ui.json); filter_nav is modus-bewust; navigate()
  werkt ook naar verborgen pagina's.
- Handleiding bijgewerkt; tests: modus-default/-wissel/-persistentie +
  bulk-volledig + bulk-resume.

## V7.7-status (10TB deel 2: her-import 20× sneller + scandir-ontdekking + scan-snelheid)

**143/143 tests groen. Benchmark:** her-import zelfde map (400×256KB) =
**29,1 s → 1,5 s (20×)** door skip-zonder-lezen; 30.000 bestanden ontdekken =
**190 ms** (os.scandir-walk, gratis stat op Windows/UNC).

- **import_folder**: al-geïmporteerde bestanden (zelfde source_path + grootte +
  aanwezige beheerkopie) worden overgeslagen ZONDER lezen (`skipped_existing`);
  resultaat-melding toont dit; crash-resume-contract (per-bestand checkpoint)
  bewaard en getest.
- **import_file**: hash + beheerkopie in één leesbeurt; duplicaat-controle via
  grootte-match i.p.v. volledige herlezing (fallback op volledige check bij
  mismatch); extensie-validatie behouden.
- **library._discover**: os.scandir-recursie i.p.v. rglob+is_file+stat
  (helft van de systeemaanroepen; gesorteerd = deterministisch resume).
- **Scan-voortgang** toont doorvoersnelheid (MB/s) voor 10TB-planning;
  stats tellen `bytes_hashed`.

## V7.6-status (10TB-snelheid: parallelle scan + chunked writes + GUI-paginering)

**139/139 tests groen. Benchmark (sandbox, 1200×256KB random):** hashen met
4 workers = **1,9× sneller**; herscan 1200 bestanden = **84 ms** (ongewijzigd-
cache, 0 hashes); 20.000 bestanden scannen = **4,8 s**; Files-query bij 21k+
locaties = **1 ms** (paginalimiet).

- **scan_root herbouwd**: hash-werk in ThreadPoolExecutor (hashlib geeft de
  GIL vrij), workers uit preset (LOW=1/BALANCED=3/HIGH=6, override
  `scan_hash_workers`); alles per CHUNK (64 bestanden): één transactie,
  één checkpoint, één progress-melding per chunk i.p.v. per bestand.
- **SQLite**: `PRAGMA synchronous=NORMAL` per connectie (bulk-commit-winst
  in WAL, bronbestanden altijd veilig).
- **repo.files(query, limit)**: paginalimiet 400 + `files_count()`; GUI-hint
  "X van Y getoond — verfijn met zoeken"; service `auto_process_ols` leest
  expliciet alles (limit=0); FTS-rebuild alleen nog bij new/modified/resume.
- Nieuwe tests: throttling, parallel==sequentieel resultaat, ongewijzigd-
  cache (herscan 0 hashes), 300-bestanden chunk-flow.

## V7.5-status (pagina-consolidatie: dubbele pagina's samengevoegd)

**136/136 tests groen. 31 → 26 pagina's (nav 37 → 32), alle functies behouden.**

- **BIN Analyseren (V3)** = oude "Analyze BIN" + "New BIN Analyse (V3)" op één
  pagina: snel-match tabel + rapport + WHY-tabel samen.
- **Diff & Regio's** = "Diff Viewer" + "Region Viewer": byteverschil + hex +
  TuningRegions met klasse/entropie/evidence op één pagina.
- **OLS Explorer & Review** = "OLS Explorer" + "OLS Object Review".
- **Families (ECU / Software / Calibratie)** = drie familiepagina's samen.
- Nav-sprongen (show_report/open_diff/dashboard-snelstart) gebruiken nu
  navigate()-op-naam i.p.v. vaste rij-indexen (robuust tegen paginavolgorde).
- Widget-attributen ongewijzigd → alle acties/refresh-methodes werken
  onveranderd; handleiding bijgewerkt; navigatie-tests dekken de nieuwe
  namen én dat de oude namen weg zijn.

## V7.4-status (Library (V5) zichtbaar op Files)

**136/136 tests groen.**

- **Files-pagina toont nu ook de Library (V5)-bestanden**: tweede tabel met
  élke `file_locations`-rij over élke root (bestand, root, type, bytes,
  SHA-8, status), gevuld bij elke refresh (met paginazoeker-filter).
- Overgang Library → Files in één klik, één voor één:
  "Selectie → Files (BIN/ORI, type hierboven)" maakt beheerkopieën met de
  gekozen type-instelling (bronbestand blijft onaangeroerd);
  "Selectie → WinOLS verwerken (.ols)" verwerkt een geselecteerd
  .ols-project volledig (versies/paren/DNA).
- Nieuw: `LibraryEngine.all_locations(query, limit)` (join met
  `library_roots` + `content_objects`); tests in `test_library.py` +
  `test_api_ui.py` (GUI-integratie).
- Handleiding (Files/Library-sectie) bijgewerkt.

## V7.3-status (wizard-crash gefixt — de echte exe-oorzaak)

**134/134 tests groen.**

- **Oorzaak van de exe-crash gevonden en gefixt**: de gebruiker stuurde de
  traceback — `AttributeError: 'QWizard' object has no attribute
  'registerField'` in `_wizard_profile`. PySide6 6.11 (in de exe via
  `PySide6>=6.8,<7`) heeft `registerField` niet meer; de eerste-start-wizard
  start alleen op een lege database, dus de tests vingen het niet.
- Fix: geen `registerField`/`field()` meer — `self._wizard_profile_combo` en
  `self._wizard_start_checkbox` worden direct uitgelezen (werkt op élke
  PySide6-versie).
- Nieuwe regressietest `test_first_run_wizard_pages` bouwt alle drie de
  wizardpagina's en leest de widgets uit (crashte situatie gedekt);
  wizard gebruikt verder geen verwijderde API's (gecheckt).
- Crash-hook (V7.2) werkte zoals bedoeld: `fout.txt` van de gebruiker maakte
  de diagnose in één keer duidelijk.

## V7.2-status (crash-handler voor de Windows-exe)

**133/133 tests groen.**

- **Crash-hook** (`app/main.py::_install_crash_hook`): een ongevangen fout
  schrijft nu **crash.log** naast de exe, toont een Qt-dialoog met de fout
  (incl. detail-tab met volledige traceback) en houdt de console open tot op
  Enter is gedrukt — geen onleesbaar verdwijnend cmd-venster meer.
- GUI-startup kreeg **log-breadcrumbs** in `data/app.log` ("Qt laden…",
  "hoofdpagina opbouwen…", "venster zichtbaar") zodat de log toont hoe ver
  de startup kwam.
- Build-artifacts (`build/`, `dist/`) staan op de ignore-lijst; de mislukte
  GUI-start van de gebruiker (lege database aanwezig, dus crash ná
  Service-init) wordt met de hook diagnosticeerbaar.

## V7.1-status (professionele import + in-app handleiding)

**133/133 tests groen.**

- **BIN/ORI 1-voor-1 import** via de Files-pagina: bestandskeuzedialoog met
  expliciete typekeuze (auto/original/tuned/unknown, met uitleg per optie);
  na import een heldere melding met bestands-ID, herkende metadata en de
  vervolgstap.
- **OLS 1-voor-1 import** via de WinOLS-pagina (bestaand, nu duidelijker
  benoemd) met volledige verwerkingsmelding (versies/rollen/paren/DNA).
- Mapimport-rapport toont nu BIN-count, OLS-count, overgeslagen en fouten
  met concrete paden.
- **Nieuwe pagina "Uitleg & Handleiding"** (START-groep): de complete
  in-app handleiding — de hoofdlijn in 5 stappen, élke pagina één voor één
  uitgelegd (31 pagina's), veiligheidsregels, en oplossingen voor bekende
  fouten (limiet, ontbrekende kopieën, taak bezig).

## V7-status (Tune Bouwer)

**133/133 tests groen** (12 nieuwe Tune Bouwer-tests). De eindstap van de
keten is er: **origineel erin → getunede KANDIDAAT terug**, met stage- en
add-onkeuze (pagina *Tune Bouwer (V7)*, `tune-build` CLI, `POST /tune-build`).

- Recepten komen uitsluitend uit **bevestigde** paren; stage/add-ons
  (pops_bang, vmax, dpf/egr/adblue-off, …) worden gelezen van expliciete
  labels (stage-metadata, WinOLS-versienaam, bestandsnaam).
- Elke toegepaste regio vereist **regionaal bewijs** (≥98% gelijk aan de
  bekende original op díe regio); afwijkende regio's worden overgeslagen
  en gerapporteerd.
- Intensiteiten (-15/-30/-45) bestaan alléén als er kennis met dat label
  is; anders expliciet UNKNOWN met lijst van wat er wél beschikbaar is —
  nooit verzinnen.
- Output = altijd een NIEUW bestand in `exports/candidates` + JSON-rapport
  (provenance, regio's, keten, 4 waarschuwingen); bronbestanden blijven
  byte-voor-byte ongewijzigd (getest); duplicate-kandidaten delen één
  candidate-ID; dry-run is de standaard.
- **Checksums worden NIET gecorrigeerd** — het bestand is pas na
  technicuscontrole in WinOLS geschikt voor gebruik; dat blijft een harde
  waarschuwing in elke output.
- Dashboard-snelstart heeft nu stap 6: kandidaat bouwen.

## V6.1-status (gebruiksvriendelijkheid + echte-PC-fixes)

**121/121 tests groen.** Gebaseerd op de echte test-log van de
Windows-productie-PC (`data/app.log`, commit `6e69a07`):

- **16× "WinOLS-project groter dan ingestelde limiet"** → `max_file_mb`
  verhoogd naar 512 MB (config.json + default) en de foutmelding noemt nu
  de oplossing i.p.v. alleen het probleem.
- **5× crash op Linux-paden** (`/home/user/...` in de meegeleverde
  database) → database niet langer meegeleverd (uit git + .gitignore);
  auto-classificatie slaat onleesbare beheerkopieën over met foutmelding
  i.p.v. te crashen; `data()` geeft een uitleggende fout met hersteladvies.
- **4× onvriendelijk "Wacht tot de huidige taak klaar is"** → melding noemt
  nu welke taak draait en waar de voortgang staat.
- **Gecomitte rommel** (`__pycache__`, app.log, database) uit git verwijderd
  en voortaan genegeerd.
- **GUI gebruiksvriendelijk gemaakt**: navigatie in 6 gegroepeerde secties
  (START · BIBLIOTHEEK · ANALYSE · KENNIS · FAMILIES & LEARNING · SYSTEEM),
  zoekvak dat de pagina's direct filtert, en een echt Dashboard met live
  status (roots online, locaties/contents, kennis, taken) en genummerde
  snelstart die naar de juiste pagina springt. 29 pagina's zijn behouden.
- Settings-pagina legt nu de belangrijkste instellingen uit.

## V6-status (FINAL PRODUCT COMPLETION)

**119/119 tests groen** (incl. 19 V6-completiontests en de Golden Dataset
met 9/9 cases, ook de echte-OLS-case). Zie
[FINAL_IMPLEMENTATION_REPORT.md](FINAL_IMPLEMENTATION_REPORT.md) en
[KNOWLEDGE_MODEL.md](KNOWLEDGE_MODEL.md).

- **WinOLS-first bevestigd uit de echte data**: de OLS-pairing gebruikte de
  geclaimde binary_length i.p.v. de werkelijke imagegrootte (855 KB-'Origineel'
  werd bevestigd gepaard met 2 MiB-tunedversies). Gefixt + zelfherstellend;
  de relatie staat nu als UNKNOWN met gemeten reden (subset-blokgelijkheid
  38%). De drie 2 MiB-versies vormen één ECU Image Identity (samen 424 bytes
  verschil); de 855 KB-versie krijgt een eigen identiteit. Handmatige
  BIN-export uit WinOLS is niet nodig: library-roots lezen OLS direct.
- Nieuw: ECU Image Identity, Project Families, Software Lineage, negatieve
  kennis (A ≠ B permanent), provenance-contract, Golden Dataset + knowledge
  regression + review-impact, Why-this-match, Comparison Workspace,
  bulk-operaties, disk-aware scheduler, parser-versioning (reparse read-only),
  evidence levels, readouts-domeinlaag (bewezen niet in matching).
- Metadata-schaal nu gemeten t/m 10.000.000 records (geïndexeerde lookups
  2,4 ms; zie SCALABILITY.md).

## V5-status (Phase 2: Local Library Engine)

**89/89 tests groen. Production Library Mode is geïmplementeerd en bewezen
op een 10.000-files testlibrary.**

- Bronbestanden blijven op hun eigen schijf (WinOLS-achtig); geen kopie naar
  `data/`. Content (SHA256) is los van Location (pad): dedup op inhoud,
  kennis kan nooit dubbel ontstaan.
- Incrementeel (size+mtime-hashcache, 0 rehashes op ongewijzigde library),
  hervatbaar (checkpoints, crash-safe), offline-schijfveilig (OFFLINE zonder
  databasebreuk), corrupte bestanden stoppen de scan niet.
- 10.000-files benchmark: eerste scan 34,9 s (288 files/s), incrementeel
  22 s/0 rehash, na 1 wijziging exact 1 rehash, 1.001 uniek/9.000 duplicaat,
  database 4,2 MB metadata, bronbestanden ongewijzigd (SHA-bewijs).
- GUI Library-pagina (25 pagina's totaal), 6 API-endpoints, 4 CLI-commando's.
- Zie [LOCAL_LIBRARY.md](LOCAL_LIBRARY.md).



## V4-status (Real Calibration Intelligence — vervolg op eigen v4/v4.1)

**80/80 tests groen.** Deze ronde bouwt voort op de eigen v4/v4.1-werk (audit,
CalibrationObject/Identity, knowledge builds, evaluations, merge/split-basis).

Nieuw in deze ronde:

- **Identity-alignment v2**: extra evidence-componenten (waardestatistiek-
  gelijkenis, bevestigde Original/Tuned-regio's), gedocumenteerde
  confidence-formule, escalatie naar REJECTED bij ≥2 tegenstrijdige zonder
  steun en SUPPORTED bij ≥3 consistente zonder contradicties; VERIFIED blijft
  uitsluitend technician-review.
- **Merge/split volledige rebuild**: confidence herberekend uit leden
  (gedocumenteerde formule), stages/software-varianten herbouwd, stale
  alignments van het bronpattern verwijderd, knowledge_build geregistreerd
  per review-actie (knowledge versioning).
- **Candidate-dedup bewezen**: identieke kandidaat-regeneratie → 1 rij
  (unieke identity-index).
- **Batch-import exact resumable bewezen**: crash → checkpoint → resume
  verwerkt de rest zonder duplicaten.
- **REAL DATA VERIFIED**: payload-boundaries (payload_offset/length,
  end_boundary, boundary_status COMPLETE/PARTIAL) van alle 5 binaries in de
  echte GASDROP_100119.ols getest; bron-SHA onveranderd.
- **GUI**: Map Structuren- en Cross Software Alignment-views (24 pagina's).
- **Schaal 10.000 paren** (synthetisch, scripts/scale_test.py): import 234 s,
  10.000 paren+bevestigen 163 s, regio-extractie+rebuild 396 s, zoeken 28 ms.

Nog steeds open (eerlijk): statistische kalibratie van confidence (blijft
HEURISTIC_CONFIDENCE tot echte gelabelde dataset bestaat), brede real-data-
validatie met duizenden echte paren, mapsemantiek/factor/unit alleen UNKNOWN
zonder bronbewijs.

## V3-status (Tuning Intelligence Engine)

**V3 intelligence/data/evidence-laag: IMPLEMENTED en getest (65/65 groen).**
**Automatische tuning/BIN-modificatie/flashing: NIET geïmplementeerd (bewust, V3-§21).**

Geleverd in deze ronde (fases 2–9, kleine commits, alle bewijs in TUNING_DNA.md,
ARCHITECTURE.md, EVIDENCE_MODEL.md, DATABASE_SCHEMA.md en ROADMAP.md):

- **TuningRegion**: elke diff-regio is een structuurobject (context-hashes,
  entropy voor/na, offset-onafhankelijke structural/delta-signatures,
  regio-klasse, checksum-kandidaatbeleid, gedocumenteerde confidence).
- **Tuning DNA**: alleen bevestigde paren, status candidate, regio-ID's en
  ECU/HW/SW/CAL/project/stage-metadata (UNKNOWN waar onbekend).
- **Pattern clustering**: deterministisch op (ecu_family, structural_signature)
  met near-merge ≥0,95, stage-verdeling, software-varianten, typical delta,
  contradictieteller; checksum-kandidaten en padding worden uitgesloten als
  tuningkennis.
- **Cross-software alignment**: blok-run-mapping tussen softwarevarianten met
  contextscore, supporting/contradicting evidence en offsets per software;
  patroonherkenning in een nieuwe BIN via dezelfde bewijsroute.
- **Map detection zonder naamgeving**: axis/table-kandidaten met criteria,
  map_type blijft unknown zonder bewijs.
- **New BIN Analysis**: gecombineerd rapport (herkenning, gerelateerde
  projecten/originals met aparte structurele en compatibiliteitsscores,
  Tuning DNA-matches, structuurkandidaten, evidence-samenvatting,
  gedocumenteerd overall-confidence met zichtbare componenten).
- **Evidence graph + technician review**: evidence/evidence_relations,
  knowledge_reviews met approve/reject/correct/merge/split/mark_*;
  approve/reject werkt door in patroon- en regio-status.
- **OLS project graph**: bewezen relaties met confidence; niet-bewezen
  relaties expliciet UNKNOWN RELATIONSHIP; malformed OLS veegt veilig leeg.
- **Performance**: hervatbare jobs (analysis_runs-checkpoints), batch-inserts,
  begrensde scans, indexen; gemeten: 5.000 paren → import 92 s, rebuild 116 s,
  zoeken <10 ms (scripts/scale_test.py, 100/1k/5k end-to-end).
- **GUI**: 5 nieuwe pagina's (Patronen, Region Viewer, New BIN Analyse,
  OLS Explorer, Zoeken) naast de 16 bestaande.

Niet gedaan/gebleven (eerlijk):

- Patroon-confidence is gedocumenteerd maar niet gekalibreerd op duizenden
  ÉCHTE paren (alleen synthetische tests + één echte OLS).
- OLS-mapinhoud (assen/factoren/units) blijft ongedecodeerd.
- Checksum-herkenning blijft kandidaatniveau zonder cross-paar-bewijs.
- Merge/split van patronen: review-actie bestaat, herberekening nog niet.
- ML/embedding-laag: bewust niet (V3-§32).

De V2.7-kandidaatstroom (`generate_tune_candidate`) is **bevroren**:
behouden met alle guards, niet uitgebreid; geen enkele BIN wordt door V3
gewijzigd.

## Nog open naar PRODUCTION READY (eerlijk, eindstand)

1. **Windows-packaging**: spec/buildscript/installer klaar en gevalideerd op
   imports + test-gate; het bouwen van de .exe en de schone-machine-test
   vergen één keer een echte Windows-machine (zie WINDOWS_INSTALL.md).
2. **Echte 10 TB inbedrijfsstelling**: alles voorbereid en op schaal bewezen;
   de bedrijfsdata zelf staan buiten deze ontwikkelomgeving.
3. **Confidence-kalibratie**: pas na >1.000 echte bevestigde paren
   (`confidence/evaluate`); tot dan HEURISTIC CONFIDENCE (bewust).
4. **ML-laag**: bewust uitgesteld (deterministisch eerst).
Zie FINAL_IMPLEMENTATION_REPORT.md voor de volledige vier-kleuren afweging.

## Eindstatus

**NOT READY als volledige V2/V2.5-productrelease.**

**V1 READY voor de lokale BIN/ORI-workflow en de automatische WinOLS-extractie. V3 intelligence-laag READY als analyse/kennislaag.**

De applicatie werkt betrouwbaar voor: import van raw `.bin`/`.ori`, het automatisch extraheren van alle embedded version-binaries uit een echte WinOLS 5 `.ols` (read-only), rolbepaling (Original/Tuned/unknown) met gescheiden role-/relation-confidence, automatische pair-voorstellen, diffanalyse, matching, kandidaat-Tuning-DNA uit bevestigde paren en kandidaat-tunebestanden met expliciete waarschuwing. Mapdefinities, assen, units en cross-software alignment zijn nog niet betrouwbaar gedecodeerd — daarom blijft de volledige V2/V2.5 NOT READY.

## Wat daadwerkelijk werkt

- Applicatie initialiseert de SQLite-database automatisch (schema v4 met `ols_version_binaries` en `tune_candidates`).
- Desktop-GUI start zonder Python- of applicatiefout; Quick Workflow heeft twee knoppen: (1) WinOLS-project volledig automatisch verwerken, (2) nieuwe BIN automatisch matchen + kandidaat-tune vanaf 70%.
- CLI (`auto-ols`, `auto-process`, `generate-candidate`, `tune-candidates`) en REST API (`/winols-projects/{id}/versions`, `/auto-process`, `/files/{id}/generate-candidate`, `/tune-candidates`) bestrijken dezelfde flow.
- Raw `.bin` en `.ori` kunnen worden geïmporteerd; beheerde kopieën worden gehasht en tegen wijziging gecontroleerd.
- **Automatische binary-extractie uit echte OLS:** embedded version-binaries worden rechtstreeks uit de `.ols` gehaald (geen handmatige WinOLS-exports meer nodig) via twee bewezen methoden: `explicit_import_header` (filenaamrecord + padrecord + vast nulveld vóór de binary) en `repeating_identity_header` (identiteitsheaders met vaste stride direct na nul-padding, ≥99% blokgelijkenis).
- Rolbepaling met prioriteit: expliciete WinOLS-metadata > version/project-relatie > object-relatie > volgorde-inferentie; `role_confidence` en `relation_confidence` zijn gescheiden velden (geverifieerd op de echte OLS: `Origineel` role_conf 100 + relation explicit, Stage-versies role_conf 95 + relation inferred 75).
- Numerieke/interne OLS-objectnamen blijven altijd `unknown`.
- Automatische pair-voorstellen bij gelijke binary-grootte; auto-bevestiging alleen bij role_confidence ≥ 95 voor beide kanten, anders blijven ze onbevestigd voor review.
- Original/Tuned-paren kunnen worden aangemaakt en bevestigd; automatische classificatie gebruikt expliciete labels, exacte hashes en zeer sterke unieke binary-evidence; ambigue bestanden blijven `unknown` + review.
- Diffanalyse, hexweergave en rapportexport werken; similarity en compatibility confidence zijn aparte velden.
- Tuning-DNA wordt alleen opgebouwd uit bevestigde paren; regio's krijgen nooit automatisch een mapnaam (Boost/Torque e.d. blijven `unknown`).
- `generate_tune_candidate` produceert een kandidaat-bestand (output `reports/candidates/<sha256>.bin`) met guards: drempel 50–100, minimaal één match ≥ drempel, bevestigd pair, regionale similarity ≥ 98%; het doelbestand wordt nooit gewijzigd en checksums worden niet gecorrigeerd (expliciete waarschuwing in GUI-dialoog).
- OLS-bestanden worden gekopieerd en nooit gewijzigd (read-only); herimport van dezelfde OLS vernieuwt records zonder duplicaten en behoudt reviews.
- Herhaalde batchimport maakt geen dubbele records voor dezelfde bron, hash en type.
- Database schema-versie en startup-validatie zijn aanwezig.

## Uitgevoerde tests

Volledige testsuite met de project-`.venv` (incl. GUI-tests in offscreen-modus):

```text
119 passed, 2 warnings
```

De warnings komen uit FastAPI/Starlette/httpx-deprecations en veroorzaken geen testfout.

Belangrijkste testdekking deze ronde:

- `tests/test_ols_structure.py` (5 synthetische OLS-fixtures): structuurparser (versies, binaries, stride, identiteit), auto-process extractie met rollen en paren, paren + DNA bij gelijke grootte, en beide candidate-guards (drempelgrenzen, geen bevestigd pair).
- `tests/test_ols_real.py` (2 tests op de echte `GASDROP_100119.ols`): aantoonbare structuur zonder verzonnen links en herimport zonder duplicaten; verifieert de confidence-split op het echte bestand (role_conf 100 / relation inferred 75).

## Verificatie op de echte OLS (GASDROP_100119.ols)

SHA256 `dcfc2d8d03b035e7d559fa6fb4c80b492c79e937cf1df0729f0912605782e3e8`, 8.738.048 bytes, header `WinOLS File`. Bewezen en getest:

- Identiteit: `53/1/MG1CS003/11/MG1CS003_BX8_R1C2J772B//R1C2J772B///`, stride 2.097.152 bytes.
- 5 binaries geëxtraheerd: Original via `explicit_import_header` (855.132 B, `f65abeea…`), 3 complete 2 MiB-pages (`d2b0cdef…`, `c195636e…` ×2 — pages 3 en 4 zijn byte-identiek), 1 onvolledige staart (1.289.608 B, `446af799…`, compleet=False).
- Versies: v1 `Origineel` → original (role_conf 100, relation `version_to_binary_explicit`), v2 `Stage1+vmax` en v3/v4 `+pops and bang` → tuned (role_conf 95, relation `version_to_binary_order_inferred` 75), vNone naamloos → unknown.
- Alle 5 binaries belanden automatisch in Files (`originals/`|`tuned/`|`unknown/<sha256>.bin`).
- Correct conservatief gedrag: Original (855.132 B) vs 2 MiB-pages → alle paren `size_mismatch_not_paired`, DNA leeg. Het programma verzint geen paren bij grootteverschil.

## Wat nog niet volledig werkt

- WinOLS-mapdefinities, assen, units en mapwaarden worden niet betrouwbaar uit `.ols` gelezen; `Kaart`-labels zijn alleen zichtbare-string inventory met adresvoorstel.
- Geen structurele mapalignment naar een nieuwe softwarevariant; Tuning-DNA is kandidaat-structuurkennis.
- Checksums/Eeprom-corrections in gegenereerde kandidaat-bestanden: niet gecorrigeerd, alleen kandidaat voor review.
- Er is geen automatische mapnaamherkenning zoals Boost, Torque Limiter of Ignition zonder echte bronmetadata.
- Binary similarity en compatibility confidence zijn geen afzonderlijke historische match-records.
- Batchimport heeft nog geen checkpoint die midden in een onderbroken import exact hervat.
- Identieke kandidaat-regeneratie maakt een tweede `tune_candidates`-rij (bestand wordt wel hergebruikt); dedupe-beleid is open.
- De binary-extractiegrens van de eerste binary loopt door tot de volgende recordgrens inclusief nul-padding; de exacte payload-lengte is niet bewezen.
- Stride < 1024 bytes (kleine synthetische projecten) wordt bewust niet als pagina-anker gedetecteerd; echte WinOLS-projecten zitten daar ruim boven.

## Placeholders of beperkte implementaties

- `extract_available_calibration_information()` rapporteert bewust `not_available` zolang betrouwbare mapinformatie ontbreekt.
- Onbekende recordtypen worden als `UNKNOWN_RECORD_TYPE` opgeslagen, nooit geraden.
- OLS-`objects` zijn zichtbare ASCII-inventory-objecten, niet gegarandeerd alle echte WinOLS-objecten.
- Tuning-DNA-regio's krijgen bewust `unknown` als label wanneer geen verifieerbare mapnaam beschikbaar is.
- Structurele alignment is een analysevoorstel en geen overdraagbare tuninginstructie.
- De nearest-neighbor-learninglaag gebruikt bytehistogrammen als baseline, geen getraind model dat tuningwaarden leert.

## Afhankelijk van echte WinOLS-data

De volgende onderdelen kunnen pas betrouwbaar worden uitgebreid met meer echte, representatieve WinOLS 5-exports:

- mapnamen, mapstructuren, assen, factoren, units en waarden;
- cross-software calibration alignment;
- Tuning-DNA-validatie over meerdere echte projecten;
- paren binnen projecten waar Original en Stage dezelfde binary-grootte hebben (verificatie of de pair-regels daar ook goed uitkomen).

De bron-`.ols` mag niet worden aangepast en moet read-only worden aangeleverd voor onderzoek.

## Applicatie starten

Open PowerShell in de projectmap:

```powershell
cd C:\tuningmaching_programa
.\start.ps1
```

Als PowerShell scripts blokkeert:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\start.ps1
```

Direct met de projectomgeving:

```powershell
.\.venv\Scripts\python.exe -m app.main gui
```

CLI-databasecontrole:

```powershell
.\.venv\Scripts\python.exe -m app.main init
```

## Echte OLS-database veilig testen

1. Maak eerst een volledige backup van de originele WinOLS-database en `.ols`-bestanden.
2. Test uitsluitend met een kopie, nooit met de actieve WinOLS-database.
3. Kies in de GUI **Quick Workflow → WinOLS-project volledig automatisch verwerken** (of CLI `auto-ols <pad>`).
4. Controleer hash, bestandsgrootte en de geëxtraheerde versies/binaries in het resultaatvenster.
5. Vergelijk daarna SHA256 van het origineel met de backup — het bronbestand wordt nooit gewijzigd.
6. Controleer in **Files** de automatisch geëxtraheerde binaries en hun rol/confidence; twijfelgevallen blijven `unknown`.
7. Bevestig een voorgesteld pair alleen na controle in WinOLS.
8. Genereer pas daarna kandidaat-Tuning-DNA en kandidaat-tunebestanden (≥ 70% drempel); kandidaten zijn nooit definitieve ECU-bestanden en checksums zijn niet gecorrigeerd.

## Conclusie

De V1-workflow — inclusief automatische extractie van alle embedded Original/Tuned-binaries uit een echte OLS, rolbepaling met evidence en confidence, paren en kandidaat-DNA — is klaar en getest (49 passed, inclusief verificatie op de echte `GASDROP_100119.ols`). De applicatie is **niet klaar als volledige V2/V2.5** zolang echte WinOLS-mapdata, assen/units, structurele alignment en hervatbare checkpoint-import niet betrouwbaar beschikbaar zijn. V2.7 (automatische ECU-file-modificatie) blijft bewust buiten scope: boven de drempel wordt uitsluitend een kandidaat getoond.

## Echte OLS-analyse (eerste forensische ronde)

Op 2026-09-10 is de aanwezige beheerde kopie `data/winols_projects/GASDROP_100119.ols` read-only onderzocht. Waargenomen zijn BMW/Bosch/MG1CS003-metadata, `Origineel`, meerdere Stage-gerelateerde projectnamen, vijf importreferenties en 265+ zichtbare `Kaart`-labels. De volledige technische bevindingen staan in [OLS_ANALYSIS_REPORT.md](OLS_ANALYSIS_REPORT.md) en de structuurdetails in [OLS_STRUCTURE_REPORT.md](OLS_STRUCTURE_REPORT.md).
