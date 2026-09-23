# DEPLOYMENT.md — van repository naar productiemachine

## Doelarchitectuur

- **Local-first desktop**: alles draait op de tuning-PC; geen cloud, geen
  externe AI-API (§47). Netwerk is nooit nodig voor kernfunctionaliteit.
- **SQLite** is de operationele database (metadata/kennis/evidence/jobs/
  indexen). De 10+ TB brondata blijft op de eigen schijven (§46).
- **PySide6-GUI + FastAPI/uvicorn lokale API + CLI** delen één `Service`.

## Omgevingen

| Omgeving | Doel | Data |
|---|---|---|
| Development (repo) | tests, benchmarks | `data/` managed-copy import |
| Productie (Windows) | dagelijks gebruik | Library-roots op eigen schijven |

Beide gebruiken hetzelfde schema (additief gemigreerd, nu `user_version=10`)
en dezelfde code; alleen de databron verschilt (kopie vs. in-place index).

## Stappen productie (Windows)

1. Build volgens [WINDOWS_INSTALL.md](WINDOWS_INSTALL.md).
2. Eerste start → wizard: roots + resourceprofiel + eerste scan.
3. Na de eerste volledige scan: `library-analyze` draaien voor deep
   analysis van gewenste content (of per bestand via GUI/API).
4. Bevestigde Original/Tuned-paren markeren (technicusbeslissing) →
   `rebuild-patterns` → knowledge build ontstaat automatisch.
5. Elke nieuwe BIN: **New BIN Analyse (V3)**-pagina of `new-bin-library`.

## Beheer

- **Backup**: GUI Backup & Health of `TuningMatching.exe backup [--dir D]`.
  Inhoud: database (online-consistent), configuratie, reviews, auditlog,
  kennis + manifest met SHA256-verificatie. NOOIT de bronbibliotheek (§64).
- **Restore**: `TuningMatching.exe restore <backupmap>` — verifieert het
  manifest, maakt eerst een veiligheidsbackup van de huidige staat.
- **Health**: `TuningMatching.exe health` — integrity_check,
  foreign_key_check, orphan-tellingen, offline roots, databasegrootte.
- **Migratie**: schema-upgrades zijn additief en idempotent; een oudere
  database wordt bij de eerste start automatisch bijgewerkt
  (`schema_migrations` + `PRAGMA user_version`). Reset alleen via
  `TuningMatching.exe reset --confirm` (verplaatst data eerst naar backup).

## Resource-beheer (§50)

- Resourceprofiel per root: LOW/BALANCED/HIGH (worker-telling voor
  hash/analyse-taken).
- Scanner leest in 1 MB-chunks; hash-cache voorkomt herlezen (§6).
- Taken zijn pauzeerbaar tussen batches (checkpoints blijven geldig); de
  scan gaat door bij corrupte bestanden en logt die (§52).
- RAM-gebruik wordt gedomineerd door de diff/analyse-stap per bestand
  (gemeten in STATUS-benchmarks); er worden nooit meerdere 2 MB+-binaries
  tegelijk volledig in geheugen genomen in de library-taken.

## Monitoring

- `jobs`-endpoint/-pagina: status QUEUED-equivalenten (running/paused/
  cancelled/interrupted/done) met checkpoints en stats.
- `audit`-endpoint: elke technicus-actie (wie/wanneer/wat/voor/na/reden).
- `health`-endpoint voor geplande controles (bijv. dagelijks via Taakplanner).
