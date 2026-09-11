"""V5 Local Library Engine: indexeer 10+ TB bronbestanden ZONDER ze te kopiëren.

WinOLS-achtige lokale projectbibliotheek: bronbestanden blijven op hun
originele locatie; de database bewaart alleen pad, identiteit (SHA256) en
status. Content (SHA256) is los van Location (pad): identieke bestanden op
meerdere plaatsen delen één content-object, zodat kennis nooit dubbel wordt
opgebouwd. Scans zijn incrementeel (size+mtime-hashcache) en hervatbaar
(checkpoints). Offline schijven breken de database niet.
"""
from __future__ import annotations

import hashlib
import json
import zlib
from pathlib import Path

LIBRARY_EXTENSIONS = {".bin", ".ori", ".ols"}
FUTURE_EXTENSIONS = {".hex", ".s19", ".mot", ".txt", ".csv", ".zip", ".7z"}
RESOURCE_PRESETS = {"LOW": 1, "BALANCED": 2, "HIGH": 4}
SCAN_BATCH = 500
STAT_KEYS = ("discovered", "hashed", "new", "unchanged", "modified", "moved",
             "missing", "duplicate", "errors", "skipped_by_resume")


def file_type_for(extension: str) -> str:
    extension = extension.lower()
    if extension in {".bin", ".ori"}:
        return "binary"
    if extension == ".ols":
        return "ols"
    if extension in FUTURE_EXTENSIONS:
        return "future_known"
    return "unknown"


class LibraryEngine:
    """Werkt direct op de gedeelde SQLite-database van de Repository."""

    def __init__(self, repo, config: dict | None = None, service=None):
        self.repo = repo
        self.config = dict(config or {})
        self.service = service  # Knowledge-service voor deep analysis (Phase 3)

    # ------------------------------------------------------------------
    # roots en totalen
    # ------------------------------------------------------------------
    def add_root(self, path: str, name: str | None = None) -> dict:
        source = Path(path)
        if not source.exists() or not source.is_dir():
            raise ValueError("Library root moet een bestaande map zijn")
        resolved = str(source.resolve())
        if self.repo.db.rows("SELECT id FROM library_roots WHERE path=?", (resolved,)):
            raise ValueError("Deze library root is al geregistreerd")
        with self.repo.db.connect() as db:
            cursor = db.execute(
                "INSERT INTO library_roots(name,path,config) VALUES (?,?,?)",
                (name or source.name, resolved,
                 json.dumps({"preset": self.config.get("resource_preset", "BALANCED")})))
            root_id = cursor.lastrowid
        return self.root(root_id)

    def root(self, root_id: int) -> dict | None:
        rows = self.repo.db.rows("SELECT * FROM library_roots WHERE id=?", (root_id,))
        if rows:
            rows[0]["config"] = json.loads(rows[0]["config"])
        return rows[0] if rows else None

    def roots(self) -> list[dict]:
        rows = self.repo.db.rows("SELECT * FROM library_roots ORDER BY id")
        for row in rows:
            row["config"] = json.loads(row["config"])
        return rows

    def storage_summary(self) -> dict:
        totals = self.repo.db.rows(
            """SELECT COALESCE(SUM(size),0) AS indexed_bytes, COUNT(*) AS locations,
                      COUNT(DISTINCT content_id) AS unique_contents
               FROM file_locations WHERE content_id IS NOT NULL""")[0]
        duplicate_bytes = self.repo.db.rows(
            """SELECT COALESCE(SUM(l.size),0) AS duplicate_bytes FROM file_locations l
               WHERE l.content_id IN (SELECT content_id FROM file_locations
                                      WHERE content_id IS NOT NULL
                                      GROUP BY content_id HAVING COUNT(*) > 1)""")[0]
        failed = self.repo.db.rows(
            "SELECT COUNT(*) AS n FROM file_locations WHERE scan_status='ERROR'")[0]["n"]
        pending = self.repo.db.rows(
            "SELECT COUNT(*) AS n FROM file_locations WHERE analysis_state='NEW'")[0]["n"]
        db_size = self.repo.db.path.stat().st_size if self.repo.db.path.exists() else 0
        return {"indexed_bytes": totals["indexed_bytes"], "locations": totals["locations"],
                "unique_contents": totals["unique_contents"],
                "duplicate_bytes": duplicate_bytes["duplicate_bytes"],
                "failed_files": failed, "pending_analysis": pending,
                "database_bytes": db_size}

    # ------------------------------------------------------------------
    # hashing
    # ------------------------------------------------------------------
    def _hash_file(self, path: Path, max_file_mb: int) -> dict:
        size_limit = max_file_mb * 1024 * 1024
        digest = hashlib.sha256()
        md5 = hashlib.md5(usedforsecurity=False)
        crc = 0
        total = 0
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > size_limit:
                    raise ValueError(f"Bestand groter dan ingestelde limiet: {path.name}")
                digest.update(chunk)
                md5.update(chunk)
                crc = zlib.crc32(chunk, crc)
        return {"sha256": digest.hexdigest(), "md5": md5.hexdigest(), "crc32": f"{crc:08x}"}

    def _ensure_content(self, file_path: Path, stat_result, max_file_mb: int,
                        stats: dict) -> int:
        """Identiteit bepalen en content-object teruggeven (dedup op sha256)."""
        digests = self._hash_file(file_path, max_file_mb)
        stats["hashed"] += 1
        rows = self.repo.db.rows("SELECT id FROM content_objects WHERE sha256=?",
                                 (digests["sha256"],))
        if rows:
            return rows[0]["id"]
        with self.repo.db.connect() as db:
            cursor = db.execute(
                """INSERT INTO content_objects(sha256,md5,crc32,size,file_type)
                   VALUES (?,?,?,?,?)""",
                (digests["sha256"], digests["md5"], digests["crc32"],
                 stat_result.st_size, file_type_for(file_path.suffix)))
            return cursor.lastrowid

    # ------------------------------------------------------------------
    # scanning
    # ------------------------------------------------------------------
    def _discover(self, root_path: Path) -> list[dict]:
        found = []
        for path in sorted(root_path.rglob("*"), key=lambda item: str(item).casefold()):
            if not path.is_file():
                continue
            try:
                found.append({"path": path, "stat": path.stat()})
            except OSError:
                found.append({"path": path, "stat": None})
        return found

    def scan_root(self, root_id: int, resume: bool = False, progress=None) -> dict:
        """Incrementeel en hervatbaar. Ongewijzigde bestanden (zelfde
        size+mtime) worden niet opnieuw gehasht; na een onderbreking gaat de
        scan vanaf het checkpoint verder en wordt NIET aangenomen dat files
        gelijk zijn — elk bezocht bestand wordt opnieuw gecontroleerd."""
        root = self.root(root_id)
        if root is None:
            raise ValueError("Onbekende library root")
        root_path = Path(root["path"])
        preset = root["config"].get("preset", "BALANCED")
        max_file_mb = int(self.config.get("max_file_mb", 64))
        if not root_path.exists():
            with self.repo.db.connect() as db:
                db.execute("UPDATE library_roots SET status='OFFLINE' WHERE id=?", (root_id,))
            return {"scan_id": None, "status": "OFFLINE",
                    "note": "Schijf/map niet bereikbaar; database blijft bruikbaar en "
                            "bestaande locaties worden NIET als MISSING gemarkeerd."}
        batch_limit = int(self.config.get("scan_batch", SCAN_BATCH))
        previous = self.interrupted_scan(root_id) if resume else None
        with self.repo.db.connect() as db:
            cursor = db.execute(
                "INSERT INTO library_scans(root_id,config) VALUES (?,?)",
                (root_id, json.dumps({"preset": preset})))
            scan_id = cursor.lastrowid
        start_after = previous["checkpoint"].get("last_path") if previous else None
        stats = dict(previous["stats"]) if previous else {}
        for key in STAT_KEYS:
            stats.setdefault(key, 0)
        stats["skipped_by_resume"] = 0
        try:
            discovered = self._discover(root_path)
            stats["discovered"] = len(discovered)
            previous_rows = {row["normalized_path"].casefold(): row for row in
                             self.repo.db.rows(
                                 "SELECT * FROM file_locations WHERE root_id=?", (root_id,))}
            seen: set[str] = set()
            batch = 0
            for item in discovered:
                file_path, stat_result = item["path"], item["stat"]
                if start_after and str(file_path).casefold() <= str(start_after).casefold():
                    stats["skipped_by_resume"] += 1
                    continue
                if stat_result is None:
                    stats["errors"] += 1
                    continue
                normalized = str(file_path.resolve())
                seen.add(normalized.casefold())
                previous_row = previous_rows.get(normalized.casefold())
                content_id = None
                scan_status = "NEW"
                if (previous_row and previous_row["size"] == stat_result.st_size
                        and previous_row["mtime"] == stat_result.st_mtime
                        and previous_row["content_id"]):
                    # hash-cache: ongewijzigd volgens size+mtime, niet opnieuw hashen
                    content_id = previous_row["content_id"]
                    scan_status = "UNCHANGED"
                    stats["unchanged"] += 1
                else:
                    try:
                        content_id = self._ensure_content(file_path, stat_result,
                                                          max_file_mb, stats)
                    except (OSError, ValueError) as exc:
                        stats["errors"] += 1
                        self._record_location(root_id, scan_id, file_path, stat_result,
                                              None, "ERROR", {"error": str(exc)},
                                              previous_row)
                        continue
                    if previous_row is None:
                        scan_status = "NEW"
                        stats["new"] += 1
                    elif previous_row["content_id"] == content_id:
                        scan_status = "UNCHANGED"  # timestamps gewijzigd, inhoud gelijk
                        stats["unchanged"] += 1
                    else:
                        scan_status = "MODIFIED"
                        stats["modified"] += 1
                self._record_location(root_id, scan_id, file_path, stat_result,
                                      content_id, scan_status, {}, previous_row)
                batch += 1
                if progress:
                    # interactieve scan: checkpoint per bestand zodat een crash
                    # (ook van buitenaf) altijd exact kan hervatten
                    self._checkpoint(scan_id, str(file_path), stats)
                    batch = 0
                    progress(f"Scan {stats['discovered'] - stats['skipped_by_resume']}"
                             f"/{stats['discovered']}")
                elif batch >= batch_limit:
                    self._checkpoint(scan_id, str(file_path), stats)
                    batch = 0

            # MISSING: bekende paden die deze scan niet zag (en niet waren overgeslagen)
            for key, row in previous_rows.items():
                if row["scan_status"] == "MISSING":
                    continue
                if start_after and key <= str(start_after).casefold():
                    continue  # nog niet bezocht in hervatte scan: niets concluderen
                if key not in seen:
                    with self.repo.db.connect() as db:
                        db.execute("UPDATE file_locations SET scan_status='MISSING', "
                                   "last_seen_scan_id=? WHERE id=?", (scan_id, row["id"]))
                    stats["missing"] += 1

            # MOVED/DUPLICATE-nabewerking: alleen nu is het volledige beeld bekend
            with self.repo.db.connect() as db:
                db.execute("""UPDATE file_locations SET scan_status='MOVED'
                    WHERE root_id=? AND scan_status='NEW' AND content_id IN (
                        SELECT content_id FROM file_locations
                        WHERE root_id=? AND scan_status='MISSING')""", (root_id, root_id))
                db.execute("""UPDATE file_locations SET scan_status='DUPLICATE'
                    WHERE root_id=? AND scan_status='NEW' AND id > (
                        SELECT MIN(l2.id) FROM file_locations l2
                        WHERE l2.content_id=file_locations.content_id)
                    AND content_id IN (
                        SELECT content_id FROM file_locations
                        WHERE content_id IS NOT NULL GROUP BY content_id
                        HAVING COUNT(*) > 1)""", (root_id,))
                for status, key in (("MOVED", "moved"), ("DUPLICATE", "duplicate")):
                    stats[key] = db.execute(
                        "SELECT COUNT(*) FROM file_locations WHERE root_id=? AND scan_status=?",
                        (root_id, status)).fetchone()[0]
            self._checkpoint(scan_id, str(root_path), stats, final=True)
            self._refresh_search_index()
            with self.repo.db.connect() as db:
                db.execute("""UPDATE library_roots SET status='ONLINE',
                    last_scan_at=CURRENT_TIMESTAMP,
                    file_count=(SELECT COUNT(*) FROM file_locations WHERE root_id=?),
                    content_count=(SELECT COUNT(DISTINCT content_id) FROM file_locations
                                   WHERE root_id=? AND content_id IS NOT NULL)
                    WHERE id=?""", (root_id, root_id, root_id))
        except Exception:
            with self.repo.db.connect() as db:
                db.execute("""UPDATE library_scans SET status='interrupted', stats=?,
                    updated_at=CURRENT_TIMESTAMP WHERE id=?""", (json.dumps(stats), scan_id))
            raise
        return {"scan_id": scan_id, "status": "done", "root_id": root_id, **stats}

    def _record_location(self, root_id: int, scan_id: int, file_path: Path,
                         stat_result, content_id: int | None, scan_status: str,
                         metadata: dict, previous_row: dict | None) -> None:
        normalized = str(file_path.resolve())
        with self.repo.db.connect() as db:
            if previous_row:
                db.execute("""UPDATE file_locations SET content_id=?, size=?, mtime=?, ctime=?,
                    scan_status=?, analysis_state='NEW', metadata=?, last_seen_scan_id=?
                    WHERE id=?""",
                           (content_id, stat_result.st_size, stat_result.st_mtime,
                            stat_result.st_ctime, scan_status,
                            json.dumps(metadata, ensure_ascii=False), scan_id,
                            previous_row["id"]))
            else:
                db.execute("""INSERT INTO file_locations
                    (root_id, content_id, path, normalized_path, filename, extension,
                     size, mtime, ctime, scan_status, analysis_state, metadata,
                     last_seen_scan_id)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                           (root_id, content_id, str(file_path), normalized,
                            file_path.name, file_path.suffix.lower(),
                            stat_result.st_size, stat_result.st_mtime,
                            stat_result.st_ctime, scan_status, "NEW",
                            json.dumps(metadata, ensure_ascii=False), scan_id))

    def _checkpoint(self, scan_id: int, last_path: str, stats: dict,
                    final: bool = False) -> None:
        with self.repo.db.connect() as db:
            db.execute("""UPDATE library_scans SET checkpoint=?, stats=?, status=?,
                updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                       (json.dumps({"last_path": last_path}), json.dumps(stats),
                        "done" if final else "running", scan_id))

    # ------------------------------------------------------------------
    # queries
    # ------------------------------------------------------------------
    def locations(self, root_id: int, query: str = "", limit: int = 200) -> list[dict]:
        like = f"%{query}%"
        return self.repo.db.rows(
            """SELECT l.id, l.path, l.filename, l.extension, l.size, l.scan_status,
                      l.analysis_state, l.content_id, c.sha256, c.file_type
               FROM file_locations l LEFT JOIN content_objects c ON c.id=l.content_id
               WHERE l.root_id=? AND (l.filename LIKE ? OR l.path LIKE ? OR c.sha256 LIKE ?)
               ORDER BY l.path LIMIT ?""", (root_id, like, like, like, limit))

    def content_locations(self, content_id: int) -> list[dict]:
        return self.repo.db.rows(
            "SELECT * FROM file_locations WHERE content_id=? ORDER BY path", (content_id,))

    def scans(self, root_id: int | None = None) -> list[dict]:
        if root_id is None:
            return self.repo.db.rows("SELECT * FROM library_scans ORDER BY id DESC LIMIT 50")
        return self.repo.db.rows(
            "SELECT * FROM library_scans WHERE root_id=? ORDER BY id DESC LIMIT 50", (root_id,))

    def interrupted_scan(self, root_id: int) -> dict | None:
        rows = self.repo.db.rows(
            """SELECT * FROM library_scans WHERE root_id=? AND status='interrupted'
               ORDER BY id DESC LIMIT 1""", (root_id,))
        if not rows:
            return None
        rows[0]["checkpoint"] = json.loads(rows[0]["checkpoint"])
        rows[0]["stats"] = json.loads(rows[0]["stats"])
        return rows[0]

    def _refresh_search_index(self) -> None:
        """FTS5-versnellingsindex (§41) vullen; LIKE-fallback bij afwezige FTS5.

        Contentless-index: alleen tokens + rowid, geen gekopieerde tekst — de
        zoekresultaten joinen altijd live op file_locations.
        """
        try:
            with self.repo.db.connect() as db:
                db.execute("DELETE FROM library_fts")
                db.execute("""INSERT INTO library_fts(rowid, filename, path, sha256)
                              SELECT l.id, l.filename, l.normalized_path,
                                     COALESCE(c.sha256, '')
                              FROM file_locations l
                              LEFT JOIN content_objects c ON c.id = l.content_id""")
            self.fts_enabled = True
        except Exception:
            self.fts_enabled = False

    def search(self, query: str, limit: int = 50) -> dict:
        """Zoek in de bibliotheek op naam/pad/sha256 (FTS5, fallback LIKE)."""
        if getattr(self, "fts_enabled", False):
            # FTS5-syntaxis: elke term als veilige quoted-phrase (punt van 'a.bin'
            # is anders een kolomfilter)
            tokens = [token.replace('"', "") for token in query.split()
                      if token.replace('"', "")]
            safe = " ".join(f'"{token}"' for token in tokens)
            # enkele hex-achtige term (hash-prefix): FTS5-prefix-zoekopdracht
            prefix = f'"{tokens[0]}"*' if len(tokens) == 1 else ""
            if safe:
                for candidate in (safe, prefix):
                    if not candidate:
                        continue
                    try:
                        rows = self.repo.db.rows(
                            """SELECT l.id, l.path, l.filename, l.size, l.scan_status,
                                      l.content_id, c.sha256
                               FROM library_fts f JOIN file_locations l ON l.id=f.rowid
                               LEFT JOIN content_objects c ON c.id=l.content_id
                               WHERE library_fts MATCH ? LIMIT ?""",
                            (candidate, limit))
                        if rows:
                            return {"mode": "fts5", "results": rows, "count": len(rows)}
                    except Exception:
                        break
        like = f"%{query}%"
        rows = self.repo.db.rows(
            """SELECT l.id, l.path, l.filename, l.size, l.scan_status,
                      l.content_id, c.sha256
               FROM file_locations l LEFT JOIN content_objects c ON c.id=l.content_id
               WHERE l.filename LIKE ? OR l.path LIKE ? OR c.sha256 LIKE ?
               LIMIT ?""", (like, like, like, limit))
        return {"mode": "like-fallback", "results": rows, "count": len(rows)}

    # ------------------------------------------------------------------
    # Phase 3: deep analysis koppeling (content → kennis, één keer per content)
    # ------------------------------------------------------------------
    def content(self, content_id: int) -> dict:
        rows = self.repo.db.rows("SELECT * FROM content_objects WHERE id=?", (content_id,))
        if not rows:
            raise ValueError("Onbekend content-object")
        return rows[0]

    def analysis_link(self, content_id: int) -> dict | None:
        rows = self.repo.db.rows(
            "SELECT * FROM content_files WHERE content_id=? ORDER BY id LIMIT 1",
            (content_id,))
        return rows[0] if rows else None

    def _online_location(self, content_id: int) -> dict | None:
        rows = self.repo.db.rows(
            """SELECT l.* FROM file_locations l JOIN library_roots r ON r.id=l.root_id
               WHERE l.content_id=? AND r.status='ONLINE' ORDER BY l.id LIMIT 1""",
            (content_id,))
        return rows[0] if rows else None

    def analyze_content(self, content_id: int) -> dict:
        """Deep analysis voor ÉÉN content-object, precies één keer.

        - Bestaat de kennis al (link of identieke sha in de analyse-store),
          dan wordt die hergebruikt — geen dubbele analyse (§4).
        - BIN/ORI worden geïmporteerd als 'unknown' (nooit automatisch
          Original/Tuned; classificatie is bewijs- of technicuswerk).
        - OLS wordt via de OLS-first pijplijn verwerkt (project/versies/
          paren/DNA op bevestigde paren).
        - De bron op schijf wordt alleen gelezen, nooit gewijzigd.
        """
        if self.service is None:
            raise ValueError("Deep analysis vereist de knowledge-service")
        content = self.content(content_id)
        link = self.analysis_link(content_id)
        if link:
            return {"content_id": content_id, "status": "cached",
                    "file_id": link["file_id"], "project_id": link["project_id"],
                    "note": "Kennis bestond al: deep analysis is één keer per content."}
        location = self._online_location(content_id)
        if location is None:
            return {"content_id": content_id, "status": "OFFLINE",
                    "note": "Geen online locatie; inhoud blijft geïndexeerd zonder analyse."}
        sha_rows = self.repo.db.rows(
            "SELECT id FROM files WHERE sha256=? ORDER BY id LIMIT 1", (content["sha256"],))
        if sha_rows:
            file_id, project_id, kind, status = sha_rows[0]["id"], None, "existing", "linked"
        elif content["file_type"] == "ols":
            result = self.service.auto_process_ols(location["path"])
            file_id, project_id, kind, status = None, result["project_id"], "ols", "analyzed"
        else:
            file_id = self.repo.import_file(Path(location["path"]), kind="unknown")
            project_id, kind, status = None, "binary", "analyzed"
        with self.repo.db.connect() as db:
            db.execute("""INSERT OR IGNORE INTO content_files(content_id,file_id,kind,project_id)
                          VALUES (?,?,?,?)""", (content_id, file_id, kind, project_id))
            db.execute("UPDATE content_objects SET analysis_state='ANALYZED' WHERE id=?",
                       (content_id,))
            db.execute("""UPDATE file_locations SET analysis_state='ANALYZED'
                          WHERE content_id=?""", (content_id,))
        return {"content_id": content_id, "status": status, "file_id": file_id,
                "project_id": project_id, "locations_updated": True}

    def pending_contents(self, root_id: int | None = None, after_id: int = 0,
                         limit: int | None = None) -> list[dict]:
        query = """SELECT DISTINCT c.id, c.sha256, c.size, c.file_type, l.root_id
                   FROM content_objects c JOIN file_locations l ON l.content_id=c.id
                   WHERE c.analysis_state='NEW' AND c.id>? AND l.scan_status!='ERROR'"""
        params: list = [after_id]
        if root_id is not None:
            query += " AND l.root_id=?"
            params.append(root_id)
        query += " ORDER BY c.id"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        return self.repo.db.rows(query, tuple(params))

    def analyze_pending(self, root_id: int | None = None, limit: int | None = None,
                        resume: bool = True, progress=None) -> dict:
        """Hervatbare, pauzeerbare analysetaak over nieuwe content (§51).

        Checkpoint per content-object; pauze/annulering wordt per object
        gerespecteerd; fouten stoppen de taak niet (§52).
        """
        run = self.repo.resume_run("library_analysis") if resume else None
        run_id = run["id"] if run else self.repo.start_run(
            "library_analysis", {"root_id": root_id})
        if run:
            self.repo.reopen_run(run_id)  # hervat: run is weer actief
        ckpt = run["checkpoint"] if run else {}
        stats = dict(run["stats"]) if run else {"analyzed": 0, "cached": 0, "linked": 0,
                                                "offline": 0, "errors": 0}
        # per-root voortgang (disk-aware scheduling §18); oude globale
        # checkpointvorm blijft leesbaar voor compatibiliteit
        last_ids = {int(key): int(value) for key, value
                    in (ckpt.get("last_ids") or {}).items()}
        global_after = ckpt.get("last_content_id", 0) \
            if not isinstance(ckpt.get("last_content_id"), dict) else 0
        rows = [row for row in self.pending_contents(root_id, 0, limit)
                if row["id"] > last_ids.get(row["root_id"], global_after)]
        groups: dict[int, list[dict]] = {}
        for row in rows:
            groups.setdefault(row["root_id"], []).append(row)
        total = len(rows)
        state = {"paused": False, "cancelled": False}
        lock = __import__("threading").Lock()

        def should_stop() -> bool:
            status = self.repo.run_status(run_id)
            if status == "paused":
                state["paused"] = True
            elif status in ("cancelled", "cancel_requested"):
                state["cancelled"] = True
            return state["paused"] or state["cancelled"]

        def task(root_key, row):
            try:
                result = self.analyze_content(row["id"])
                key = result["status"] if result["status"] in ("cached", "offline",
                                                               "linked") else "analyzed"
                with lock:
                    stats[key] = stats.get(key, 0) + 1
            except Exception as exc:  # één slecht bestand stopt de taak niet (§52)
                with lock:
                    stats["errors"] += 1
                if progress:
                    progress(f"Fout bij content {row['id']}: {exc}")

        def checkpoint(root_key, row):
            with lock:
                last_ids[root_key] = row["id"]
                self.repo.checkpoint_run(run_id, {"last_ids": last_ids}, stats)

        from app.scheduler import DiskScheduler
        workers = int(self.config.get("analysis_workers",
                                      {"LOW": 1, "BALANCED": 2, "HIGH": 4}.get(
                                          self.config.get("resource_preset",
                                                          "BALANCED"), 1)))
        outcome = DiskScheduler(workers=workers).run(
            groups, task, should_stop=should_stop, checkpoint=checkpoint,
            progress=lambda item: progress(f"Analyse {item['id']}")
            if progress else None)
        if state["paused"]:
            self.repo.pause_run(run_id, {"last_ids": last_ids}, stats)
            return {"run_id": run_id, "status": "paused", "remaining": total, **stats}
        if state["cancelled"]:
            self.repo.cancel_run(run_id, stats)
            return {"run_id": run_id, "status": "cancelled", **stats}
        self.repo.finish_run(run_id, "done", stats)
        return {"run_id": run_id, "status": "done",
                "max_concurrent_roots": outcome["max_concurrent"], **stats}

    # ------------------------------------------------------------------
    # Watch folders (§7): optioneel, nooit automatisch Original/Tuned
    # ------------------------------------------------------------------
    def set_watch(self, root_id: int, enabled: bool, policy: dict | None = None) -> dict:
        root = self.root(root_id)
        if root is None:
            raise ValueError("Onbekende library root")
        config = dict(root["config"])
        config["watch"] = bool(enabled)
        merged = {"auto_analyze": False, "classify_exact_duplicates": False}
        merged.update(config.get("watch_policy") or {})
        merged.update(policy or {})
        config["watch_policy"] = merged
        with self.repo.db.connect() as db:
            db.execute("UPDATE library_roots SET config=? WHERE id=?",
                       (json.dumps(config), root_id))
        return self.root(root_id)

    def process_watch(self, progress=None) -> dict:
        """Scan watch-roots en verwerk nieuwe files volgens beleid.

        Beleid (bewijsregel): auto_analyze analyzeert nieuwe content; er wordt
        NOOIT automatisch Original/Tuned vastgesteld — uitsluitend de
        exact-duplicate regel (byte-identiek + getypeerd bewijs) indien
        expliciet ingeschakeld.
        """
        report = {"roots": [], "new": 0, "analyzed": 0, "classified": 0}
        for root in self.roots():
            if not root["config"].get("watch"):
                continue
            scan = self.scan_root(root["id"])
            policy = root["config"].get("watch_policy", {})
            entry = {"root_id": root["id"], "scan": scan["status"],
                     "new": scan.get("new", 0), "analyzed": 0}
            if isinstance(scan.get("new"), int):
                report["new"] += scan["new"]
            if policy.get("auto_analyze") and scan["status"] == "done":
                analysis = self.analyze_pending(root_id=root["id"], progress=progress)
                entry["analyzed"] = analysis.get("analyzed", 0) + analysis.get("linked", 0)
                report["analyzed"] += entry["analyzed"]
            if policy.get("classify_exact_duplicates"):
                result = self.repo.auto_classify_exact_duplicates()
                entry["classified"] = result.get("classified", 0)
                report["classified"] += entry["classified"]
            entry["note"] = ("Geen automatische Original/Tuned-rollen: rollen volgen "
                             "uitsluitend bewijs of technicusbeslissing.")
            report["roots"].append(entry)
        return report
