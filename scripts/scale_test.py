"""Schaaltest V4: 1.000 / 5.000 / 10.000 synthetische paren end-to-end.

Meet import (met checkpoint), regionextractie, patroon-rebuild en zoeken.
Gebruik: .venv/bin/python scripts/scale_test.py 1000 5000 10000
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.service import Service  # noqa: E402

BASE_SIZE = 2048


def run(count: int) -> dict:
    folder = Path(tempfile.mkdtemp(prefix=f"v4scale{count}_"))
    config = {"data_dir": str(folder / "data"), "max_file_mb": 8, "top_matches": 10,
              "candidate_pool": 500, "block_size": 64, "diff_merge_gap": 2}
    service = Service(config)
    source = folder / "batch"
    source.mkdir(parents=True)
    started = time.perf_counter()
    for index in range(count):
        seed = index % 40
        data = bytearray((seed * 31 + i * 7) % 253 for i in range(BASE_SIZE))
        (source / f"o{index}.bin").write_bytes(bytes(data))
        offset = 128 + (index % 7) * 128
        for i in range(offset, offset + 64):
            data[i] = (data[i] + 1 + index % 3) % 256
        (source / f"t{index}.bin").write_bytes(bytes(data))
    staged = time.perf_counter() - started
    started = time.perf_counter()
    service.repo.import_folder(str(source), "auto")
    import_seconds = time.perf_counter() - started
    originals = [row for row in service.repo.files() if row["file_type"] == "original"]
    tuned = {row["sha256"] for row in service.repo.files() if row["file_type"] == "tuned"}
    import_pairs = 0
    for row in originals:
        if row["sha256"] in tuned:
            continue
        import_pairs += 1
    del import_pairs
    # classificatie + paren expliciet aanmaken (original i <-> tuned i)
    started = time.perf_counter()
    paired = 0
    by_name = {row["filename"]: row for row in service.repo.files()}
    for index in range(count):
        original_row = by_name.get(f"o{index}.bin")
        tuned_row = by_name.get(f"t{index}.bin")
        if original_row and tuned_row:
            if original_row["file_type"] != "original":
                service.repo.reclassify_files([original_row["id"]], "original")
                service.repo.reclassify_files([tuned_row["id"]], "tuned")
            service.repo.pair(original_row["id"], tuned_row["id"], confirmed=True)
            paired = index + 1
    pair_seconds = time.perf_counter() - started
    suggested = paired
    started = time.perf_counter()
    result = service.rebuild_patterns()
    rebuild_seconds = time.perf_counter() - started
    regions = service.repo.db.rows("SELECT COUNT(*) AS n FROM tuning_regions")[0]["n"]
    started = time.perf_counter()
    hits = service.search("SCALE_MG1CS003")
    search_seconds = time.perf_counter() - started
    stats = {"pairs": count, "staged_files_seconds": round(staged, 1),
             "import_seconds": round(import_seconds, 1), "pairs_suggested": suggested,
             "pair_seconds": round(pair_seconds, 1), "regions": regions,
             "rebuild_seconds": round(rebuild_seconds, 1), "patterns": result["patterns"],
             "search_seconds": round(search_seconds, 3)}
    shutil.rmtree(folder, ignore_errors=True)
    return stats


def main() -> None:
    sizes = [int(value) for value in sys.argv[1:]] or [1000, 5000, 10000]
    for size in sizes:
        stats = run(size)
        print(f"{stats['pairs']:>6} paren | import {stats['import_seconds']:>7}s | "
              f"paar-voorstellen {stats['pairs_suggested']:>6} ({stats['pair_seconds']}s) | "
              f"regio's {stats['regions']:>6} | rebuild {stats['rebuild_seconds']:>7}s | "
              f"patronen {stats['patterns']:>3} | zoeken {stats['search_seconds']}s")


if __name__ == "__main__":
    main()
