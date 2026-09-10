"""Evidence-based BIN identification with detected/probable/possible states."""
from __future__ import annotations

import re

from app.analysis.metadata import extract_metadata

_ASCII = re.compile(rb"[\x20-\x7e]{4,80}")
_ECU_PATTERN = re.compile(r"\b(?:MED|EDC|MG|MD|MEVD|SID|DENSO|DELCO)[A-Z0-9.]{1,20}\b", re.I)
_PART_PATTERN = re.compile(r"\b(?:[A-Z0-9]{3}[ .-]){2,5}[A-Z0-9]{2,8}\b")


def _item(value: str, offset: int, confidence: float, state: str, method: str) -> dict:
    return {"value": value, "offset": offset, "confidence": confidence, "state": state, "method": method}


def recognize(data: bytes) -> dict:
    """Only return strings that occur in the data; no vehicle/engine guessing."""
    tagged = extract_metadata(data)
    result = {"ecu": [], "hardware": [], "software": [], "calibration": [], "engine": []}
    fields = {"hardware_number": "hardware", "software_number": "software",
              "calibration_number": "calibration", "ecu_family": "ecu"}
    for field, group in fields.items():
        if tagged.get(field):
            raw = tagged[field].encode("ascii", errors="ignore")
            result[group].append(_item(tagged[field], data.find(raw), 98.0, "DETECTED", "explicit_tag"))
    seen = {group: {item["value"] for item in values} for group, values in result.items()}
    for match in _ASCII.finditer(data):
        text = match.group().decode("ascii", errors="ignore").strip()
        for candidate in _ECU_PATTERN.finditer(text):
            value = candidate.group().upper()
            if value not in seen["ecu"]:
                result["ecu"].append(_item(value, match.start() + candidate.start(), 70.0, "POSSIBLE", "ascii_pattern"))
                seen["ecu"].add(value)
        for candidate in _PART_PATTERN.finditer(text):
            value = re.sub(r"\s+", " ", candidate.group().upper()).strip()
            if value not in seen["hardware"]:
                result["hardware"].append(_item(value, match.start() + candidate.start(), 45.0, "POSSIBLE", "generic_part_pattern"))
                seen["hardware"].add(value)
    for group in result:
        result[group] = sorted(result[group], key=lambda item: (-item["confidence"], item["offset"]))[:20]
    result["metadata"] = tagged
    result["note"] = "Alle waarden zijn uit de BIN gelezen of uit goedgekeurde databasekennis afgeleid."
    return result
