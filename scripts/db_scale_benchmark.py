"""V5 schaalbenchmark (§45/§71): metadata-schaling 100k → 5m records.

Meet insert-, zoek- en jointijden op de library-tabellen plus databasegroei.
Gebruik: .venv/bin/python scripts/db_scale_benchmark.py [100000 500000 1000000 5000000]
"""
from __future__ import annotations

import hashlib
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.database import Database  # noqa: E402


def run_scale(total: int) -> dict:
    workspace = Path(tempfile.mkdtemp(prefix=f"scale{total}_"))
    db = Database(workspace / "database.sqlite")
    batch = 50_000
    started = time.perf_counter()
    with db.connect() as conn:
        conn.execute("INSERT INTO library_roots(id,name,path) VALUES (1,'Benchmark','D:\\\\Tuning')")
        for base in range(0, total, batch):
            rows = []
            for index in range(base, min(base + batch, total)):
                sha = hashlib.sha256(f"content{index}".encode()).hexdigest()
                rows.append((index, sha, f"crc{index:08x}", 4096, "binary"))
            conn.executemany(
                "INSERT OR IGNORE INTO content_objects(id,sha256,crc32,size,file_type) "
                "VALUES (?,?,?,?,?)", rows)
            locations = [(index, 1, f"D:\\Tuning\\sw{index % 97}\\file{index}.bin",
                          f"D:\\Tuning\\sw{index % 97}\\file{index}.bin",
                          f"file{index}.bin", ".bin", 4096)
                         for index in range(base, min(base + batch, total))]
            conn.executemany(
                "INSERT OR IGNORE INTO file_locations(id,root_id,path,normalized_path,"
                "filename,extension,size) VALUES (?,?,?,?,?,?,?)", locations)
    insert_seconds = time.perf_counter() - started
    started = time.perf_counter()
    with db.connect() as conn:
        conn.execute("SELECT id FROM content_objects WHERE sha256=?",
                     (hashlib.sha256(b"content123456").hexdigest(),)).fetchone()
    sha_seconds = time.perf_counter() - started
    started = time.perf_counter()
    with db.connect() as conn:
        conn.execute("SELECT COUNT(*) FROM file_locations WHERE filename LIKE 'file123%'").fetchone()
    like_seconds = time.perf_counter() - started
    started = time.perf_counter()
    with db.connect() as conn:
        conn.execute("""SELECT c.file_type, COUNT(*) FROM content_objects c
                        JOIN file_locations l ON l.content_id=c.id
                        GROUP BY c.file_type""").fetchone()
    join_seconds = time.perf_counter() - started
    started = time.perf_counter()
    with db.connect() as conn:
        conn.execute("""SELECT l.path FROM file_locations l
                        WHERE l.filename='file4999999.bin'""").fetchone()
    indexed_name_seconds = time.perf_counter() - started
    db_bytes = (workspace / "database.sqlite").stat().st_size
    del db
    shutil.rmtree(workspace, ignore_errors=True)
    return {"records": total, "insert_seconds": round(insert_seconds, 2),
            "sha_lookup_ms": round(sha_seconds * 1000, 2),
            "like_filter_ms": round(like_seconds * 1000, 2),
            "join_ms": round(join_seconds * 1000, 2),
            "indexed_name_ms": round(indexed_name_seconds * 1000, 2),
            "database_mb": round(db_bytes / 1e6, 1)}


def main() -> None:
    scales = [int(value) for value in sys.argv[1:]] or [100_000, 500_000, 1_000_000, 5_000_000]
    print(f"{'records':>9} | {'insert s':>9} | {'sha ms':>8} | {'like ms':>8} | "
          f"{'join ms':>8} | {'idx ms':>7} | {'db MB':>8}")
    for total in scales:
        row = run_scale(total)
        print(f"{row['records']:>9} | {row['insert_seconds']:>9} | "
              f"{row['sha_lookup_ms']:>8} | {row['like_filter_ms']:>8} | "
              f"{row['join_ms']:>8} | {row['indexed_name_ms']:>7} | {row['database_mb']:>8}")


if __name__ == "__main__":
    main()
