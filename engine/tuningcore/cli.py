"""TuningCore CLI: tc — init/scan/parse/status/pairs/bench.

Gebruik (vanaf de repo-root; --db vóór het subcommando):
    PYTHONPATH=engine python -m tuningcore --db core.db scan D:\\Database\\1
    PYTHONPATH=engine python -m tuningcore --db core.db parse
    PYTHONPATH=engine python -m tuningcore --db core.db status
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

from .db import connect
from .process import parse_pending
from .scan import scan


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def cmd_scan(args) -> int:
    db = connect(args.db)
    stats = scan(db, args.root, preset=args.preset, progress=_progress)
    print(f"Scan klaar: {stats}")
    return 0


def cmd_parse(args) -> int:
    db = connect(args.db)
    stats = parse_pending(db, workers=args.workers, limit=args.limit,
                          progress=_progress)
    print(f"Parse klaar: {stats}")
    return 0


def cmd_status(args) -> int:
    db = connect(args.db)
    def one(sql: str) -> int:
        return db.execute(sql).fetchone()[0]
    scanned = "SELECT COUNT(*) FROM files WHERE state='SCANNED'"
    count_ols = "SELECT COUNT(*) FROM files WHERE ext='.ols'"
    role_sql = lambda r: "SELECT COUNT(*) FROM ols_versions WHERE role='%s'" % r
    pairs_sql = "SELECT COUNT(*) FROM pairs WHERE state='suggested'"
    lines = [
        "roots:            %d" % one("SELECT COUNT(*) FROM roots"),
        "files gescand:    %d" % one(scanned),
        "  .ols:           %d" % one(count_ols),
        "ols geparsed:     %d" % one("SELECT COUNT(*) FROM ols_projects"),
        "versies:          %d" % one("SELECT COUNT(*) FROM ols_versions"),
        "  original:       %d" % one(role_sql("original")),
        "  tuned:          %d" % one(role_sql("tuned")),
        "  unknown:        %d" % one(role_sql("unknown")),
        "paren (suggest):  %d" % one(pairs_sql),
        "fouten:           %d" % one("SELECT COUNT(*) FROM errors"),
    ]
    print("\n".join(lines))
    return 0


def cmd_pairs(args) -> int:
    db = connect(args.db)
    rows = db.execute(
        """SELECT p.id, op.path AS project, ov.name AS original, tv.name AS tuned,
                  tv.stage, p.confidence, p.state
           FROM pairs p
           JOIN ols_projects op ON op.id = p.project_id
           JOIN ols_versions ov ON ov.id = p.original_version_id
           JOIN ols_versions tv ON tv.id = p.tuned_version_id
           WHERE p.state = ? ORDER BY p.id""", (args.state,)).fetchall()
    for row in rows:
        stage = row["stage"] or "—"
        print(f"#{row['id']} {Path(row['project']).name} · "
              f"{row['original']} → {row['tuned']} ({stage}, {row['confidence']:.0f}%)")
    print(f"— {len(rows)} paren met state={args.state}")
    return 0


def cmd_bench(args) -> int:
    """Synthetische benchmark: N OLS genereren + volledige scan+parse meten."""
    from .sample import build_ols
    tmp = Path(tempfile.mkdtemp(prefix="tc_bench_"))
    print(f"Benchmark: {args.count} OLS x {args.size_kb} KB in {tmp}", file=sys.stderr)
    base_binary = bytes(args.size_kb * 1024)
    for index in range(args.count):
        binary_tuned = base_binary[:-1] + bytes([index % 256])  # 1 byte anders
        versions = [("origineel v1", base_binary),
                    (f"stage 1 tune {index}", binary_tuned)]
        (tmp / f"proj_{index:05d}.ols").write_bytes(
            build_ols(f"1/1/EDC17/C64/BOSCH/{index:05d}", versions))
    db = connect(args.db)
    t0 = time.monotonic()
    scan_stats = scan(db, str(tmp), preset="MAX", progress=_progress)
    t1 = time.monotonic()
    parse_stats = parse_pending(db, workers=args.workers, progress=_progress)
    t2 = time.monotonic()
    print(f"scan : {scan_stats} in {t1 - t0:.1f}s")
    print(f"parse: {parse_stats} in {t2 - t1:.1f}s")
    rate = parse_stats.get("per_second", 0)
    if rate:
        print(f"extrapolatie 1.2M OLS: parse = {1_200_000 / rate / 3600:.1f} uur "
              f"met {parse_stats.get('per_second', 0)} bestanden/s (dit systeem)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tuningcore",
                                     description="TuningCore — snelle OLS-kern")
    parser.add_argument("--db", default="tuningcore.db", help="database-bestand")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser("scan", help="root scannen + hashen")
    scan_p.add_argument("root")
    scan_p.add_argument("--preset", default="MAX", choices=["LOW", "BALANCED", "MAX"])

    parse_p = sub.add_parser("parse", help="OLS-bestanden parsen (parallel)")
    parse_p.add_argument("--workers", type=int, default=None)
    parse_p.add_argument("--limit", type=int, default=None)

    sub.add_parser("status", help="tellingen tonen")
    pairs_p = sub.add_parser("pairs", help="gevonden paren tonen")
    pairs_p.add_argument("--state", default="suggested")

    bench_p = sub.add_parser("bench", help="synthetische benchmark")
    bench_p.add_argument("--count", type=int, default=200)
    bench_p.add_argument("--size-kb", type=int, default=512)
    bench_p.add_argument("--workers", type=int, default=None)

    args = parser.parse_args(argv)
    handlers = {"scan": cmd_scan, "parse": cmd_parse, "status": cmd_status,
                "pairs": cmd_pairs, "bench": cmd_bench}
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
