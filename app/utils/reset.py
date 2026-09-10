"""Safe application-data reset with a recoverable backup."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path


def reset_data_dir(data_dir: str | Path) -> Path:
    source = Path(data_dir).resolve()
    if source.name.lower() in {"", ".", ".."}:
        raise ValueError("Ongeldige data-map voor reset")
    if not source.exists():
        source.mkdir(parents=True, exist_ok=True)
        return source
    backup = source.with_name(f"{source.name}_backup_{datetime.now():%Y%m%d_%H%M%S}")
    source.rename(backup)
    source.mkdir(parents=True, exist_ok=True)
    return backup