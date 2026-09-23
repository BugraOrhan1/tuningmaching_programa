"""Rol/stage-herkenning uit expliciete labels — bewezen regels, nooit gokken.

Overgezet uit de beproefde V8-generatie: alléén expliciete tekst telt als
bewijs ('orig', 'Stage 1', …). Niets afleiden uit grootte of inhoud.
"""
from __future__ import annotations

import re

_ORIGINAL_NAME = re.compile(
    r"(?:^|[\s_\-()\[\]])(origineel|original|ori|stock|oem)(?:$|[\s_\-()\[\].])", re.I)
_TUNED_NAME = re.compile(
    r"(stage\s*\d|stage\d|tuned|mod(?:ified)?|vmax|pops|bang|chip|dpf|egr|adblue|decat|antilag)", re.I)
_STAGE = re.compile(r"stage\s*([1-5])", re.I)

_ADDON_TOKENS = {
    "vmax": ("vmax", "v-max"),
    "pops": ("pops", "bang", "crackle"),
    "dpf": ("dpf", "roetfilter"),
    "egr": ("egr",),
    "adblue": ("adblue", "scr ", "nox"),
    "decat": ("decat", "de-cat", "kat off"),
    "antilag": ("antilag", "anti-lag"),
}


def role_from_name(name: str) -> tuple[str, float]:
    """Rol alléén uit expliciete versie-/bestandsnaam (never container-guess)."""
    text = name or ""
    if _ORIGINAL_NAME.search(text):
        return "original", 100.0
    if _TUNED_NAME.search(text):
        return "tuned", 95.0
    return "unknown", 0.0


def stage_from_name(name: str) -> str | None:
    match = _STAGE.search(name or "")
    return f"stage{match.group(1)}" if match else None


def addons_from_name(name: str) -> list[str]:
    text = (name or "").lower()
    return [addon for addon, tokens in _ADDON_TOKENS.items()
            if any(token in text for token in tokens)]
