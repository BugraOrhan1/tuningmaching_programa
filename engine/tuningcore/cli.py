"""TuningCore CLI: tc — scan/parse/status/pairs/bench/log.

Gebruik (vanaf de repo-root; --db vóór het subcommando):
    PYTHONPATH=engine python -m tuningcore --db core.db scan D:\\Database\\1
    PYTHONPATH=engine python -m tuningcore --db core.db parse
    PYTHONPATH=engine python -m tuningcore --db core.db status
    PYTHONPATH=engine python -m tuningcore --db core.db log --tail 50

Alles wordt gelogd in `<databank>.log` (roteert bij 5 MB, max 3 oudere).
Crasht of lijkt vast te zitten?  `log --tail 50` zegt altijd waar hij was
en bij fouten staat de volledige traceback in het log.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

from . import logsetup
from .db import connect
from .process import parse_pending
from .scan import scan


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)
    logsetup.get().info("%s", message)


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
    checkpoints = db.execute(
        "SELECT key, value FROM meta WHERE key LIKE 'scan_checkpoint_%' "
        "OR key='parse_checkpoint'").fetchall()
    for row in checkpoints:
        print(f"checkpoint {row['key']}: {row['value']}")
    last_errors = db.execute(
        "SELECT at, phase, path, message FROM errors ORDER BY id DESC LIMIT 5"
    ).fetchall()
    if last_errors:
        print("— laatste fouten:")
        for row in last_errors:
            first = (row["message"] or "").splitlines()[0][:120]
            print(f"  {row['at']} [{row['phase']}] {Path(row['path']).name}: {first}")
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


def cmd_log(args) -> int:
    """Laatste regels van het logbestand — diagnose bij crash/vastgelopen."""
    lines = logsetup.tail(args.db, args.tail)
    if not lines:
        print("(geen log gevonden bij deze database)")
        return 0
    print("\n".join(lines))
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


HANDLERS = {"scan": cmd_scan, "parse": cmd_parse, "status": cmd_status,
            "pairs": cmd_pairs, "bench": cmd_bench, "log": cmd_log}


def build_parser() -> argparse.ArgumentParser:
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

    sub.add_parser("status", help="tellingen + checkpoints + laatste fouten")
    pairs_p = sub.add_parser("pairs", help="gevonden paren tonen")
    pairs_p.add_argument("--state", default="suggested")

    log_p = sub.add_parser("log", help="laatste logregels tonen (diagnose)")
    log_p.add_argument("--tail", type=int, default=50)

    bench_p = sub.add_parser("bench", help="synthetische benchmark")
    bench_p.add_argument("--count", type=int, default=200)
    bench_p.add_argument("--size-kb", type=int, default=512)
    bench_p.add_argument("--workers", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logsetup.setup(args.db)
    logsetup.get().info("CLI commando=%s opties=%s", args.command,
                        {k: v for k, v in vars(args).items()
                         if k not in ("command", "db")})
    try:
        return HANDLERS[args.command](args)
    except KeyboardInterrupt:
        logsetup.get().warning("CLI afgebroken door gebruiker (Ctrl+C) — "
                               "checkpoints staan veilig in de database")
        print("Afgebroken. Voortgang is veilig — gewoon opnieuw starten.",
              file=sys.stderr)
        return 130
    except Exception as exc:  # crash-guard: traceback in log, nooit kale crash
        tb_text = logsetup.log_exception(args.command, exc)
        db_for_errors = None
        try:
            db_for_errors = connect(args.db)
            from .db import log_error
            log_error(db_for_errors, args.command, "cli", f"{exc}\n{tb_text}")
            db_for_errors.commit()
        except Exception:
            pass
        print(f"FOUT: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(f"Volledige traceback staat in het log:  "
              f"python -m tuningcore --db {args.db} log --tail 50",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
