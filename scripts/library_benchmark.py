"""V5 Library-benchmark: testlibrary met 10.000+ files scannen.

Meet: eerste scan (hash + index), incrementele rescan (hash-cache), scan na
wijziging, en databasegroei. BRONBESTANDEN WORDEN NOOIT GEWIJZIGD.
Gebruik: .venv/bin/python scripts/library_benchmark.py [10000]
"""
from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.repository import Repository  # noqa: E402
from app.library import LibraryEngine  # noqa: E402


def build_library(folder: Path, count: int) -> None:
    """Synthetische bibliotheek: BMW/VAG/Mercedes-structuur, 10% duplicaten."""
    brands = ("BMW", "VAG", "Mercedes", "PSA", "Ford")
    kinds = ("bin", "ori", "ols", "txt")
    payload = {}
    for index in range(count // 10):  # 10% unieke payloads, rest duplicaten
        payload[index] = hashlib.sha256(f"payload{index}".encode()).digest() * 8
    for index in range(count):
        brand = brands[index % len(brands)]
        kind = kinds[index % len(kinds)]
        directory = folder / brand / f"sw{index % 25}"
        directory.mkdir(parents=True, exist_ok=True)
        data = payload[index % (count // 10)]
        if kind == "ols":
            data = b"WinOLS File\x00" + data
        (directory / f"file{index}.{kind}").write_bytes(data)


def main() -> None:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 10_000
    workspace = Path(tempfile.mkdtemp(prefix="v5lib_"))
    library = workspace / "Library"
    library.mkdir()
    print(f"Testlibrary bouwen: {count} files…")
    started = time.perf_counter()
    build_library(library, count)
    print(f"  gebouwd in {time.perf_counter() - started:.1f}s")

    data_dir = workspace / "data"
    data_dir.mkdir()
    repo = Repository({"data_dir": str(data_dir), "max_file_mb": 64})
    engine = LibraryEngine(repo, {"resource_preset": "BALANCED"})

    source_digests_before = {}
    sample = sorted(library.rglob("*"))[:50]
    for path in sample:
        if path.is_file():
            source_digests_before[path] = hashlib.sha256(path.read_bytes()).hexdigest()

    root = engine.add_root(str(library), "Benchmark10k")
    started = time.perf_counter()
    first = engine.scan_root(root["id"])
    first_seconds = time.perf_counter() - started
    print(f"EERSTE SCAN: {first['discovered']} files in {first_seconds:.1f}s "
          f"({first['discovered'] / max(0.1, first_seconds):.0f} files/s) "
          f"gehasht {first['hashed']} · duplicaten {first['duplicate']}")

    started = time.perf_counter()
    second = engine.scan_root(root["id"])
    second_seconds = time.perf_counter() - started
    print(f"INCREMENTELE SCAN: {second_seconds:.1f}s "
          f"({second['discovered'] / max(0.1, second_seconds):.0f} files/s), "
          f"gehasht {second['hashed']} (hash-cache werkend: {second['hashed'] == 0})")

    # één file wijzigen -> alleen die wordt gehasht
    probe = library / "BMW" / "sw0" / "file0.bin"
    data = probe.read_bytes() + b"x"
    probe.write_bytes(data)
    started = time.perf_counter()
    third = engine.scan_root(root["id"])
    third_seconds = time.perf_counter() - started
    probe.write_bytes(data[:-1])
    print(f"SCAN NA 1 WIJZIGING: {third_seconds:.1f}s, gehasht {third['hashed']} "
          f"(verwacht 1), modified {third['modified']}")

    summary = engine.storage_summary()
    print(f"OPSLAG: {summary['locations']} locaties · {summary['unique_contents']} unieke "
          f"contents · duplicaten {summary['duplicate_bytes'] / 1e6:.1f} MB · "
          f"database {summary['database_bytes'] / 1e6:.1f} MB")
    intact = all(hashlib.sha256(path.read_bytes()).hexdigest() == digest
                 for path, digest in source_digests_before.items())
    print(f"BRONBESTANDEN ONGEWIJZIGD: {'JA' if intact else 'NEE'}")
    shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    main()
