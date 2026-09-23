"""Parallelle scanner: walk + hash met size+mtime-cache en checkpoints.

Hashen via hashlib = OpenSSL (C, hardware-versneld); de GIL wordt vrijgegeven
tijdens het hashen, dus threads schalen écht. Batches van 200 in één
transactie; checkpoint na elke batch → hervatten is exact.
"""
from __future__ import annotations

import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .db import bump_meta, connect, log_error
from . import logsetup

_BATCH = 200
_HASH_WORKERS = {"LOW": 2, "BALANCED": max(4, (os.cpu_count() or 4) // 2),
                 "MAX": min(16, max(8, (os.cpu_count() or 4) - 1))}
_EXTENSIONS = {".ols", ".bin", ".ori"}


def _hash_file(path: str, limit_mb: int = 4096) -> str:
    digest = hashlib.sha256()
    read = 0
    with open(path, "rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            digest.update(chunk)
            read += len(chunk)
            if read >= limit_mb * 1024 * 1024:
                break
    return digest.hexdigest()


def discover(root: Path) -> list[tuple[str, int, float]]:
    """Alle doel-bestanden onder een root (os.scandir = snelste walk)."""
    found = []
    stack = [str(root)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False) and \
                                entry.name.lower().endswith(tuple(_EXTENSIONS)):
                            stat = entry.stat(follow_symlinks=False)
                            found.append((entry.path, stat.st_size, stat.st_mtime))
                    except OSError:
                        continue
        except OSError:
            continue
    return found


def scan(db, root_path: str, preset: str = "MAX", progress=None) -> dict:
    """Scan één root: nieuw/gewijzigd hashen, ongewijzigd skippen (geen lezen)."""
    started = time.monotonic()
    root_path = str(Path(root_path).resolve())
    row = db.execute("SELECT id FROM roots WHERE path=?", (root_path,)).fetchone()
    if row:
        root_id = row["id"]
    else:
        cursor = db.execute("INSERT INTO roots(path) VALUES (?)", (root_path,))
        root_id = cursor.lastrowid
        db.commit()

    found = discover(Path(root_path))
    total_bytes = sum(size for _, size, _ in found)
    workers = _HASH_WORKERS.get(preset.upper(), _HASH_WORKERS["BALANCED"])
    stats = {"discovered": len(found), "new": 0, "unchanged": 0, "modified": 0,
             "errors": 0, "bytes_hashed": 0}
    log = logsetup.get()
    log.info("SCAN start root=%s gevonden=%d totaal_MB=%.1f preset=%s workers=%d",
             root_path, len(found), total_bytes / (1024 * 1024), preset.upper(),
             workers)

    previous = {row["path"]: row for row in db.execute(
        "SELECT path, size, mtime, sha256 FROM files WHERE root_id=?", (root_id,))}

    batch: list[tuple] = []

    def flush():
        if not batch:
            return
        t_batch = time.monotonic()
        with db:
            db.executemany(
                """INSERT INTO files(root_id, path, name, ext, size, mtime, sha256, state)
                   VALUES (?,?,?,?,?,?,?, 'SCANNED')
                   ON CONFLICT(path) DO UPDATE SET size=excluded.size,
                     mtime=excluded.mtime, sha256=excluded.sha256,
                     state='SCANNED', scanned_at=CURRENT_TIMESTAMP""",
                batch)
        bump_meta(db, f"scan_checkpoint_{root_id}", batch[-1][1])
        db.commit()
        log.info("SCAN batch: +nieuw=%d onveranderd=%d gewijzigd=%d fouten=%d "
                 "%.1f MB gehasht in %.2fs t/m=%s",
                 stats["new"], stats["unchanged"], stats["modified"],
                 stats["errors"], stats["bytes_hashed"] / (1024 * 1024),
                 time.monotonic() - t_batch, batch[-1][1])
        batch.clear()

    def handle(item):
        path, size, mtime = item
        old = previous.get(path)
        if old and old["size"] == size and old["mtime"] == mtime and old["sha256"]:
            return path, size, old["sha256"], "unchanged"
        try:
            return path, size, _hash_file(path), "new"
        except OSError as exc:
            logsetup.get().error("SCAN leesfout %s: %s", path, exc)
            return path, 0, None, f"error: {exc}"

    for index in range(0, len(found), max(workers * 25, 50)):
        chunk = found[index:index + max(workers * 25, 50)]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for path, size, sha, outcome in pool.map(handle, chunk):
                if outcome.startswith("error"):
                    stats["errors"] += 1
                    log_error(db, path, "scan", outcome)
                    continue
                if outcome == "unchanged":
                    stats["unchanged"] += 1
                else:
                    stats["new" if outcome == "new" else "modified"] += 1
                    stats["bytes_hashed"] += size
                name = Path(path).name
                ext = Path(path).suffix.lower()
                mtime_by_path = {item[0]: item[2] for item in chunk}
                batch.append((root_id, path, name, ext, size,
                              mtime_by_path.get(path, 0), sha))
        flush()
        if progress:
            elapsed = max(time.monotonic() - started, 0.001)
            speed = stats["bytes_hashed"] / elapsed / (1024 * 1024)
            done = stats["new"] + stats["unchanged"] + stats["modified"] + stats["errors"]
            percent = 100 * done / max(stats["discovered"], 1)
            eta = (total_bytes / (stats["bytes_hashed"] / elapsed)
                   - elapsed) if stats["bytes_hashed"] and total_bytes else 0
            progress(f"Scan {done}/{stats['discovered']} ({percent:.0f}%) · "
                     f"{speed:.0f} MB/s · nieuw {stats['new']} · "
                     f"ETA {max(eta, 0) / 60:.0f} min · fouten {stats['errors']}")
    flush()
    db.commit()
    stats["seconds"] = round(time.monotonic() - started, 2)
    log.info("SCAN klaar root=%s %s", root_path, stats)
    return stats
