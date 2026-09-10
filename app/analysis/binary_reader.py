"""Bounded binary input. Intel HEX is deliberately not treated as raw BIN."""
from pathlib import Path


def read_binary(path: str | Path, max_file_mb: int = 64) -> bytes:
    path = Path(path)
    if path.suffix.lower() not in {".bin", ".ori"}:
        raise ValueError("Alleen raw .bin en .ori worden ondersteund; converteer Intel HEX eerst.")
    with path.open("rb") as stream:
        data = stream.read(max_file_mb * 1024 * 1024 + 1)
    if not data:
        raise ValueError(f"Leeg bestand: {path.name}")
    if len(data) > max_file_mb * 1024 * 1024:
        raise ValueError(f"Bestand groter dan ingestelde limiet: {path.name}")
    return data
