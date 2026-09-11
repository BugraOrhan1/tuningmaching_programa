"""V5 Local Library Engine: indexeer 10+ TB bronbestanden ZEER ze te kopiëren.

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

    def __init__(self, repo, config: dict | None = None):
        self.repo = repo
        self.config = dict(config or {})

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
