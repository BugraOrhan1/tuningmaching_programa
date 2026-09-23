"""Conservative original/tuned classification from explicit human labels."""
from __future__ import annotations

import re
from pathlib import Path


TUNED_TOKENS = {"mod", "modified", "tuned", "tuning", "remap", "stage", "stg",
                "pops", "pop", "bang", "vmax", "decat", "antilag", "e85",
                "chiptuning", "chiptuned", "optpower"}
ORIGINAL_TOKENS = {"ori", "orig", "original", "originals", "stock", "oem",
                   "backup", "origineel", "originele", "orgineel", "factory",
                   "fabriek", "standaard", "standard"}
# aan elkaar geschreven varianten: stage1, dpfoff, egroff, adblueoff, decat, v-max…
TUNED_PATTERNS = (
    r"(?:^|[^a-z0-9])(?:stage|stg)[ _.-]*[1-4]\+?(?:$|[^a-z0-9])",
    r"(?:^|[^a-z0-9])pop(?:s)?[ _.-]*(?:&|and|n|en)?[ _.-]*bang",
    r"(?:^|[^a-z0-9])(?:dpf|egr|adblue|scr|decat|de-cat)[ _.-]*(?:off|uit|delete|del)",
    r"(?:^|[^a-z0-9])v[ _.-]*max(?:$|[^a-z0-9])",
    r"(?:^|[^a-z0-9])decat(?:$|[^a-z0-9])",
)


def classify_label(value: str) -> tuple[str, str | None]:
    """Classify only explicit labels; numbers and ECU data remain unknown."""
    normal = value.lower()
    tokens = set(re.split(r"[^a-z0-9]+", normal))
    if (tokens & TUNED_TOKENS
            or any(re.search(pattern, normal) for pattern in TUNED_PATTERNS)):
        return "tuned", "expliciet tuninglabel gevonden"
    if tokens & ORIGINAL_TOKENS:
        return "original", "expliciet originallabel gevonden"
    return "unknown", None


def infer_path_type(path: Path) -> str:
    return classify_label(f"{path.stem} {path.parent.name}")[0]
