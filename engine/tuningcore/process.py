"""OLS-parse piplijn: multiprocessing (GIL-vrij), batches, resume, no-crash.

Elke OLS wordt in een worker-proces volledig geïsoleerd geparseerd: een
slecht bestand kost één werkresultaat met een foutmelding, nooit de run.
Parent schrijft per batch (één transactie) en zet een checkpoint.
"""
from __future__ import annotations

import time
from pathlib import Path

import traceback as _tb

from .db import bump_meta, connect, get_meta, log_error
from . import logsetup
from .olsparse import parse_ols_file

_PENDING_PAGE_SIZE = 256


def _parse_worker(args: tuple) -> dict:
    """Worker (module-niveau = picklable op Windows): parse één OLS.

    Fouten worden NIET in de worker gelogd (multiprocess-roteer-conflicten)
    maar volledig — inclusief traceback — teruggestuurd naar de parent.
    """
    file_id, path, size, mtime, sha = args
    try:
        result = parse_ols_file(path)
        return {"file_id": file_id, "path": path, "size": size, "mtime": mtime,
                "sha": sha, "result": result, "error": None, "traceback": None}
    except Exception as exc:  # bewust breed: één slecht bestand stopt nooit de run
        return {"file_id": file_id, "path": path, "size": size, "mtime": mtime,
                "sha": sha, "result": None, "error": str(exc),
                "traceback": _tb.format_exc()}


def parse_pending(db, workers: int = None, limit: int = None, progress=None) -> dict:
    """Parse alle nog-niet-geparse (of gewijzigde) OLS-bestanden."""
    import os
    from multiprocessing import get_context

    started = time.monotonic()
    workers = workers or min(8, max(2, (os.cpu_count() or 2)))
    pending = db.execute(
        """SELECT COUNT(*)
           FROM files f LEFT JOIN ols_projects p ON p.path = f.path
           WHERE f.ext='.ols' AND f.sha256 IS NOT NULL
             AND (p.id IS NULL OR p.source_mtime != f.mtime)""").fetchone()[0]
    if limit:
        pending = min(pending, limit) if limit > 0 else max(0, pending + limit)
    stats = {"pending": pending, "parsed": 0, "versions": 0, "pairs": 0, "errors": 0}
    log = logsetup.get()
    log.info("PARSE start: %d bestanden te doen, workers=%d, limit=%s",
             pending, workers, limit)

    batch: list[dict] = []

    def flush(batch_results: list[dict]):
        if not batch_results:
            return
        t_batch = time.monotonic()
        with db:
            for item in batch_results:
                if item["error"] or item["result"] is None:
                    stats["errors"] += 1
                    message = (item["error"] or "onbekend")
                    tb = item.get("traceback")
                    if tb:
                        message = f"{message}\n{tb}"
                    log_error(db, item["path"], "ols_parse", message)
                    continue
                result = item["result"]
                _roles = {}
                for _v in result["versions"]:
                    _roles[_v["role"]] = _roles.get(_v["role"], 0) + 1
                log.info("PARSE %s: %d versies (%s), %d compleet, "
                         "identity=%s stride=%s",
                         item["path"], len(result["versions"]),
                         ", ".join(f"{k}={n}" for k, n in sorted(_roles.items()))
                         or "geen",
                         sum(1 for _v in result["versions"]
                             if _v.get("complete")),
                         result.get("identity"), result.get("stride"))
                existing = db.execute(
                    "SELECT source_mtime FROM ols_projects WHERE path=?",
                    (item["path"],)).fetchone()
                if existing and existing["source_mtime"] == item["mtime"] \
                        and result["sha256"] == _project_sha(db, item["path"]):
                    continue  # skip-cache: ongewijzigd en al primed
                if existing:
                    db.execute("DELETE FROM ols_versions WHERE project_id="
                               "(SELECT id FROM ols_projects WHERE path=?)",
                               (item["path"],))
                    db.execute("DELETE FROM pairs WHERE project_id="
                               "(SELECT id FROM ols_projects WHERE path=?)",
                               (item["path"],))
                    db.execute("DELETE FROM ols_projects WHERE path=?", (item["path"],))
                cursor = db.execute(
                    """INSERT INTO ols_projects(file_id, path, sha256, size, source_mtime,
                                               signature, identity, stride)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (item.get("file_id"), item["path"], result["sha256"], result["file_size"],
                     item["mtime"], result["signature"], result["identity"], result["stride"]))
                project_id = cursor.lastrowid
                version_ids: dict[int, int] = {}
                for version in result["versions"]:
                    vcursor = db.execute(
                        """INSERT INTO ols_versions(project_id, vindex, name, path, role,
                                                    confidence, stage, complete,
                                                    binary_offset, binary_length, binary_sha256)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (project_id, version["version_index"], version["name"],
                         version["path"], version["role"], version["confidence"],
                         version.get("stage"), version.get("complete", 0),
                         version.get("binary_offset"), version.get("binary_length"),
                         version.get("binary_sha256")))
                    version_ids[version["version_index"]] = vcursor.lastrowid
                    stats["versions"] += 1
                # auto-paren binnen het project: original × tuned, gelijke grootte,
                # beide compleet — state 'suggested' (mens bevestigt; bewijsregel)
                originals = [v for v in result["versions"]
                             if v["role"] == "original" and v.get("complete")]
                tuned = [v for v in result["versions"]
                         if v["role"] == "tuned" and v.get("complete")]
                for original in originals:
                    for t in tuned:
                        if original.get("binary_length") != t.get("binary_length"):
                            continue
                        db.execute(
                            """INSERT OR IGNORE INTO pairs(project_id,
                                 original_version_id, tuned_version_id, basis, confidence)
                               VALUES (?,?,?,?,95.0)""",
                            (project_id, version_ids[original["version_index"]],
                             version_ids[t["version_index"]],
                             "same_project_original_tuned_size_match"))
                        stats["pairs"] += 1
                stats["parsed"] += 1
        bump_meta(db, "parse_checkpoint", batch_results[-1]["path"])
        db.commit()
        log.info("PARSE batch: parsed=%d/%d versies=%d paren=%d fouten=%d "
                 "in %.2fs t/m=%s",
                 stats["parsed"], stats["pending"], stats["versions"],
                 stats["pairs"], stats["errors"], time.monotonic() - t_batch,
                 batch_results[-1]["path"])
        batch_results.clear()

    def _project_sha(database, path: str) -> str | None:
        row = database.execute("SELECT sha256 FROM ols_projects WHERE path=?",
                               (path,)).fetchone()
        return row["sha256"] if row else None

    context = get_context("spawn" if os.name == "nt" else "fork")
    chunk_size = max(workers * 2, 4)
    pool = None
    if stats["pending"]:
        try:
            pool = context.Pool(processes=workers)
        except Exception as exc:
            log.warning(
                "PARSE pool niet beschikbaar (%s: %s) — verder in SERIALE modus",
                type(exc).__name__, exc)

    def run_chunk(chunk_rows: list[tuple]) -> list[dict]:
        """Reuse one bounded pool per job; fall back to serial on pool errors."""
        nonlocal pool
        if pool is not None:
            try:
                return pool.map(_parse_worker, chunk_rows)
            except Exception as exc:
                broken_pool, pool = pool, None
                broken_pool.terminate()
                broken_pool.join()
                log.warning(
                    "PARSE pool niet beschikbaar (%s: %s) — verder in SERIALE modus",
                    type(exc).__name__, exc)
        return [_parse_worker(item) for item in chunk_rows]

    def process_chunk(chunk_rows: list[tuple]) -> None:
        results = run_chunk(chunk_rows)
        flush(results)
        if progress:
            elapsed = max(time.monotonic() - started, 0.001)
            rate = stats["parsed"] / elapsed
            remaining = stats["pending"] - stats["parsed"] - stats["errors"]
            eta_min = remaining / rate / 60 if rate else 0
            progress(f"OLS {stats['parsed']}/{stats['pending']} "
                     f"({100 * stats['parsed'] / max(stats['pending'], 1):.0f}%) · "
                     f"{rate:.1f} bestanden/s · {stats['versions']} versies · "
                     f"{stats['pairs']} paren · ETA {eta_min:.0f} min · "
                     f"fouten {stats['errors']}")

    last_file_id = None
    fetched = 0
    pending_chunk: list[tuple] = []
    completed = False
    try:
        while fetched < stats["pending"]:
            page_limit = min(_PENDING_PAGE_SIZE, stats["pending"] - fetched)
            page_query = """SELECT f.id AS file_id, f.path, f.size, f.mtime, f.sha256
                            FROM files f LEFT JOIN ols_projects p ON p.path = f.path
                            WHERE f.ext='.ols' AND f.sha256 IS NOT NULL
                              AND (p.id IS NULL OR p.source_mtime != f.mtime)"""
            parameters = ()
            if last_file_id is not None:
                page_query += " AND f.id > ?"
                parameters = (last_file_id,)
            page_query += " ORDER BY f.id LIMIT ?"
            page = db.execute(page_query, (*parameters, page_limit)).fetchall()
            if not page:
                break
            fetched += len(page)
            last_file_id = page[-1]["file_id"]
            for row in page:
                pending_chunk.append(tuple(row))
                if len(pending_chunk) == chunk_size:
                    process_chunk(pending_chunk)
                    pending_chunk = []
        if pending_chunk:
            process_chunk(pending_chunk)
        completed = True
    finally:
        if pool is not None:
            if completed:
                pool.close()
            else:
                pool.terminate()
            pool.join()
    flush([])
    db.commit()
    stats["seconds"] = round(time.monotonic() - started, 2)
    stats["per_second"] = round(stats["parsed"] / max(stats["seconds"], 0.001), 2)
    log.info("PARSE klaar: %s", stats)
    return stats
