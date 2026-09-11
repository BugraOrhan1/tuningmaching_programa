"""Safe, read-only inspection of opaque WinOLS project files.

The OLS project format is proprietary.  This module deliberately does not
interpret project bytes as an ECU binary and never writes to the source file.
"""


from __future__ import annotations

# Parser-versie: wordt per project/record bewaard zodat her-interpretatie
# zonder data-verlies kan (§19). Verhogen = nieuwe interpretatie, raw evidence blijft.
PARSER_VERSION = "v1"

import re
import struct
from pathlib import Path

from app.analysis.fingerprint import hashes
from app.analysis.metadata import extract_metadata
from app.analysis.classification import classify_label

_PRINTABLE = re.compile(rb"[\x20-\x7e]{4,120}")
_ROLE_TEXT = re.compile(r"(?:origineel|original|modified|tuned|stage\s*[123](?:\+)?|stage[123](?:\+)?)", re.I)


def _record_type(value: str) -> str:
    lowered = value.lower()
    if value == "WinOLS File":
        return "header"
    if lowered.endswith((".bin", ".ori")) or "mporteerd uit bestand:" in lowered or lowered.startswith("c:\\"):
        return "binary_reference"
    if _ROLE_TEXT.search(value):
        return "version_or_role_label"
    if lowered.startswith("kaart"):
        return "map_label"
    if lowered in {"complete binary file", "eprom", "nocs"}:
        return "project_metadata"
    return "unknown_ascii_record"


def _extract_length_prefixed_records(data: bytes, scan_limit: int = 4 * 1024 * 1024) -> list[dict]:
    records = []
    end = min(len(data) - 4, scan_limit)
    offset = 0
    while offset < end:
        length = struct.unpack_from("<I", data, offset)[0]
        if not 1 <= length <= 512 or offset + 4 + length > len(data):
            offset += 1
            continue
        raw = data[offset + 4:offset + 4 + length]
        if not raw or not all(32 <= byte < 127 or byte in (9, 10, 13) for byte in raw):
            offset += 1
            continue
        value = raw.decode("ascii", errors="replace").strip()
        if not value:
            offset += 1
            continue
        record_type = _record_type(value)
        records.append({"record_id": f"record-{len(records) + 1}", "offset": offset,
                        "length": length, "value_raw": value,
                        "record_type": record_type,
                        "confidence": 100.0 if record_type != "unknown_ascii_record" else 70.0,
                        "evidence": "little_endian_length_prefix"})
        offset += 4 + length
    return records


def _forensic_summary(data: bytes) -> dict:
    """Summarize observed format evidence without interpreting opaque records."""
    strings = [match.group().decode("ascii", errors="replace").strip()
               for match in _PRINTABLE.finditer(data)]
    role_evidence = sorted({value for value in strings if _ROLE_TEXT.search(value)})
    import_references = sorted({value for value in strings if "mporteerd uit bestand:" in value})
    stage_references = sorted({value for value in strings if "stage" in value.lower()})
    records = _extract_length_prefixed_records(data)
    return {
        "status": "partial",
        "format_signature": "WinOLS File" if data[4:15] == b"WinOLS File" else "unknown",
        "serialization_evidence": "little_endian_length_prefixed_ascii_observed",
        "visible_ascii_string_count": len(strings),
        "length_prefixed_ascii_count": len(records),
        "records": records,
        "role_label_evidence": role_evidence,
        "stage_label_evidence": stage_references,
        "import_references": import_references,
        "map_label_count": data.lower().count("kaart".encode("ascii")),
        "binary_object_count": None,
        "binary_evidence": [{"record_id": item["record_id"], "value": item["value_raw"],
                     "status": "boundary_unknown"}
                    for item in records if item["record_type"] == "binary_reference" or item["value_raw"] == "Complete binary file"],
        "relationships": "not_decoded",
        "map_information": "visible_map_labels_only",
        "note": "Counts and labels are observed bytes; they are not proof of WinOLS object boundaries or roles.",
    }


def read_ols(path: str | Path, max_file_mb: int = 64) -> bytes:
    path = Path(path)
    if path.suffix.lower() != ".ols":
        raise ValueError("Selecteer een WinOLS .ols-projectbestand.")
    with path.open("rb") as stream:
        data = stream.read(max_file_mb * 1024 * 1024 + 1)
    if not data:
        raise ValueError(f"Leeg WinOLS-project: {path.name}")
    if len(data) > max_file_mb * 1024 * 1024:
        raise ValueError(f"WinOLS-project groter dan ingestelde limiet: {path.name}")
    return data


def inspect_ols(data: bytes, text_limit: int = 2 * 1024 * 1024) -> dict:
    """Return limited, non-authoritative observable project information."""
    inspected = data[:text_limit]
    strings = []
    objects = []
    seen = set()
    for match in _PRINTABLE.finditer(inspected):
        value = match.group().decode("ascii", errors="replace").strip()
        if value and value not in seen:
            seen.add(value)
            strings.append(value)
            label, reason = classify_label(value)
            objects.append({
                "internal_id": str(len(objects) + 1),
                "object_name_raw": value,
                "object_type": "visible_ascii_string",
                "offset": match.start(),
                "size": len(match.group()),
                "binary_available": False,
                "role": label,
                "confidence": 100.0 if reason else 0.0,
                "detection_method": "explicit_visible_label" if reason else "no_role_evidence",
                "evidence": [reason] if reason else [],
            })
        if len(strings) == 100:
            break
    tagged_text = b"\x00".join(match.group() for match in _PRINTABLE.finditer(inspected))
    records = _extract_length_prefixed_records(data)
    suggested_type, suggestion_reason = classify_label(" ".join(strings))
    return {
        "format": "WinOLS OLS project (opaque)",
        "file_size": len(data),
        "header_hex": data[:32].hex(" "),
        "inspected_bytes": len(inspected),
        "ascii_strings": strings,
        "objects": objects,
        "tagged_metadata": extract_metadata(tagged_text),
        "suggested_type": suggested_type,
        "suggestion_reason": suggestion_reason,
        "forensic": _forensic_summary(data),
        "records": records,
        "hashes": hashes(data),
        "note": "Strings en tags zijn alleen zichtbare projectinhoud. Het project is niet als ECU-BIN geanalyseerd.",
    }
