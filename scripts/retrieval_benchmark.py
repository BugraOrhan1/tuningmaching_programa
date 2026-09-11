"""V5 retrieval-benchmark (§40/§71): New BIN multi-stage over een echte
geïndexeerde library. Meet scan-, analyse- en retrievtijden incl. stage-trace.
Gebruik: .venv/bin/python scripts/retrieval_benchmark.py [5000]
"""
from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.service import Service  # noqa: E402


def main() -> None:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 5_000
    workspace = Path(tempfile.mkdtemp(prefix="retrieval_"))
    library = workspace / "Library"
    (library / "BMW").mkdir(parents=True)
    print(f"Library bouwen: {count} files…")
    for index in range(count):
        payload = hashlib.sha256(f"payload{index}".encode()).digest() * 32  # 256 B
        (library / "BMW" / f"file{index}.bin").write_bytes(payload)
    service = Service({"data_dir": str(workspace / "data"), "max_file_mb": 16,
                       "top_matches": 10, "candidate_pool": 250, "block_size": 64,
                       "diff_merge_gap": 2})
    root = service.library.add_root(str(library), "RetrievalBenchmark")
    started = time.perf_counter()
    scan = service.library.scan_root(root["id"])
    scan_seconds = time.perf_counter() - started
    print(f"SCAN: {scan['discovered']} files in {scan_seconds:.1f}s "
          f"({scan['discovered'] / max(0.1, scan_seconds):.0f} files/s)")

    started = time.perf_counter()
    analysis = service.library.analyze_pending(resume=False)
    analysis_seconds = time.perf_counter() - started
    print(f"ANALYSE: {analysis['analyzed'] + analysis['linked']} contents in "
          f"{analysis_seconds:.1f}s "
          f"({(analysis['analyzed'] + analysis['linked']) / max(0.1, analysis_seconds):.0f}/s)")

    # case 1: exacte content-hit (stage 1)
    known = library / "BMW" / "file123.bin"
    started = time.perf_counter()
    exact = service.new_bin_library_report(str(known))
    exact_ms = (time.perf_counter() - started) * 1000
    print(f"NEW BIN exact-hit: {exact_ms:.0f} ms, stage1 hits="
          f"{exact['stages'][0]['hits']} (kennis hergebruikt, geen deep analysis)")

    # case 2: onbekend bestand → volledige multi-stage pijplijn
    unknown = workspace / "unknown.bin"
    unknown.write_bytes(hashlib.sha256(b"niet bekend").digest() * 32)
    started = time.perf_counter()
    report = service.new_bin_library_report(str(unknown))
    unknown_seconds = time.perf_counter() - started
    stages = {stage["name"]: stage["hits"] for stage in report.get("stages", [])}
    print(f"NEW BIN unknown: {unknown_seconds:.1f}s totaal, stages={stages}, "
          f"gerelateerde originals={len(report.get('related_originals', []))}, "
          f"overall={report.get('overall_confidence')}")
    print(f"ZOEKINDEX: {service.library.search('file123')['count']} hit(s) via "
          f"{service.library.search('file123')['mode']}")
    health = service.health_check()
    print(f"HEALTH: {health['status']}, database "
          f"{health['database_bytes'] / 1e6:.1f} MB")
    shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    main()
