"""Schaaltest V3: 100 / 1.000 / 5.000 synthetische paren end-to-end.

Meet inlezing, regionextractie, patroon-rebuild en zoeken. Synthetische
paren hebben een bekende structuur (één 64-byte wijzigingsblok met
deterministische delta) zodat clustering verifieerbaar blijft.

Gebruik:
    .venv/bin/python scripts/scale_test.py [100] [1000] [5000]
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


def make_pair(folder: Path, index: int, variant: int):
    original = folder / f"o{index}.bin"
    tuned = folder / f"t{index}.bin"
    seed = index % 40
    data = bytearray((seed * 31 + i * 7) % 253 for i in range(BASE_SIZE))
    original.write_bytes(bytes(data))
    offset = 128 + (index % 7) * 128
    for i in range(offset, offset + 64):
        data[i] = (data[i] + 1 + variant) % 256
    tuned.write_bytes(bytes(data))
    return original, tuned


def run(count: int) -> dict:
    folder = Path(tempfile.mkdtemp(prefix=f"v3scale{count}_"))
    config = {"data_dir": str(folder / "data"), "max_file_mb": 8, "top_matches": 10,
              "candidate_pool": 500, "block_size": 64, "diff_merge_gap": 2}
    service = Service(config)
    variants = 3
    started = time.perf_counter()
    for index in range(count):
        original, tuned = make_pair(folder, index, index % variants)
        original_id = service.repo.import_file(original, "original")
        tuned_id = service.repo.import_file(tuned, "tuned")
        service.repo.update_metadata(original_id, {"ecu_family": "SCALE_MG1CS003",
                                                   "stage": "Stage 1" if index % 2 else "Stage 2",
                                                   "software_number": f"SW{index % 7}"})
        service.repo.pair(original_id, tuned_id, confirmed=True)
    import_seconds = time.perf_counter() - started

    started = time.perf_counter()
    result = service.rebuild_patterns()
    rebuild_seconds = time.perf_counter() - started
    regions = service.repo.db.rows("SELECT COUNT(*) AS n FROM tuning_regions")[0]["n"]

    started = time.perf_counter()
    hits = service.search("SCALE_MG1CS003")
    search_seconds = time.perf_counter() - started

    started = time.perf_counter()
    patterns = service.patterns_detail()
    members = sum(len(p["members"]) for p in patterns)
    detail_seconds = time.perf_counter() - started

    stats = {
        "pairs": count,
        "import_seconds": round(import_seconds, 2),
        "regions_extracted": regions,
        "rebuild_seconds": round(rebuild_seconds, 2),
        "patterns": result["patterns"],
        "pattern_members": members,
        "search_seconds": round(search_seconds, 3),
        "search_files": len(hits["files"]),
        "pattern_detail_seconds": round(detail_seconds, 2),
    }
    shutil.rmtree(folder, ignore_errors=True)
    return stats


def main() -> None:
    sizes = [int(value) for value in sys.argv[1:]] or [100, 1000, 5000]
    header = f"{'paren':>7} {'import(s)':>10} {'regios':>9} {'rebuild(s)':>11} " \
             f"{'patronen':>9} {'leden':>7} {'zoeken(s)':>10}"
    print(header)
    for size in sizes:
        stats = run(size)
        print(f"{stats['pairs']:>7} {stats['import_seconds']:>10} "
              f"{stats['regions_extracted']:>9} {stats['rebuild_seconds']:>11} "
              f"{stats['patterns']:>9} {stats['pattern_members']:>7} "
              f"{stats['search_seconds']:>10}")


if __name__ == "__main__":
    main()
