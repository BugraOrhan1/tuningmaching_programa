"""Conservative original/tuned classification from explicit human labels."""
from __future__ import annotations

import re
from pathlib import Path


def classify_label(value: str) -> tuple[str, str | None]:
    """Classify only explicit labels; numbers and ECU data remain unknown."""
    normal = value.lower()
    tokens = set(re.split(r"[^a-z0-9]+", normal))
    if (tokens & {"mod", "modified", "tuned", "tuning", "remap", "stage", "stg"}
            or re.search(r"(?:^|[^a-z0-9])(?:stage|stg)[ _.-]*[123](?:\+)?(?:$|[^a-z0-9])", normal)):
        return "tuned", "expliciet tuninglabel gevonden"
    if tokens & {"ori", "orig", "original", "originals", "stock", "oem", "backup"}:
        return "original", "expliciet originallabel gevonden"
    return "unknown", None


def infer_path_type(path: Path) -> str:
    return classify_label(f"{path.stem} {path.parent.name}")[0]
