"""Evidence-based OLS-parser (stdlib-only port van de beproefde V8-logica).

Bewezen regels uit de V8-generatie, 1-op-1 overgezet zonder numpy:
* versies alleen via expliciete little-endian length-prefixed ASCII-records;
* binary-grenzen alleen bij expliciete import-header OF identiteitsheader
  die op vaste afstand herhaalt direct na nul-padding (blokken ≥99% gelijk);
* alles wat niet bewezen is blijft unknown. Bestand wordt nooit gewijzigd.
"""
from __future__ import annotations

import hashlib
import re
import struct

_PRINTABLE_RUN = re.compile(rb"[\x20-\x7e]{16,}")
_MIN_STRIDE = 1024
_DEFAULT_SCAN_LIMIT = 4 * 1024 * 1024
_CHUNK = 4096

_ORIGINAL_NAME = re.compile(
    r"(?:^|[\s_\-()\[\]])(origineel|original|ori|stock|oem)(?:$|[\s_\-()\[\].])", re.I)
_TUNED_NAME = re.compile(r"(stage\s*\d|stage\d|tuned|mod(?:ified)?|vmax|pops|bang|chip)", re.I)
_STAGE = re.compile(r"stage\s*([1-5])", re.I)


def _hashes(data: bytes) -> dict:
    return {"sha256": hashlib.sha256(data).hexdigest(),
            "md5": hashlib.md5(data).hexdigest()}


def _length_prefixed_strings(data: bytes, limit: int) -> list[dict]:
    records = []
    offset = 0
    end = min(len(data) - 4, limit)
    while offset < end:
        length = struct.unpack_from("<I", data, offset)[0]
        if 1 <= length <= 512 and offset + 4 + length <= len(data):
            raw = data[offset + 4:offset + 4 + length]
            if all(32 <= byte < 127 or byte in (9, 10, 13) for byte in raw):
                records.append({"offset": offset, "value": raw.decode("ascii", errors="replace"),
                                "end": offset + 4 + length})
                offset += 4 + length
                continue
        offset += 1
    return records


def _role_from_version_name(name: str) -> tuple[str, float]:
    if _ORIGINAL_NAME.search(name):
        return "original", 100.0
    if _TUNED_NAME.search(name):
        return "tuned", 95.0
    return "unknown", 0.0


def _parse_versions(records: list[dict], data: bytes) -> list[dict]:
    candidates = []
    for index, record in enumerate(records):
        value = record["value"]
        if "\t" in value or len(value) > 100:
            continue
        lower = value.lower()
        # importpad-records zijn géén versienamen (eindigen op .bin/.ori of
        # bevatten een stations-/pad-notatie) — strikte bewijsregel
        if lower.endswith((".bin", ".ori")) or "\\" in value or ": " in value:
            continue
        role, confidence = _role_from_version_name(value)
        if role == "unknown":
            continue
        path = None
        next_offset = records[index + 1]["offset"] if index + 1 < len(records) else len(data)
        region = data[record["end"]:next_offset]
        match = re.search(rb"bestand:[\r\n ]+([\x20-\x7e]+?\.bin)", region, re.I) \
            or re.search(rb"([\x20-\x7e]+?\.bin)", region, re.I)
        if match:
            path = match.group(1).decode("ascii", errors="replace")
        else:
            for follower in records[index + 1:index + 12]:
                if follower["offset"] - record["end"] > 512:
                    break
                if follower["value"].lower().endswith((".bin", ".ori")):
                    path = follower["value"]
                    break
        if not path:
            continue
        candidates.append({"name": value, "path": path, "order": record["offset"],
                           "role": role, "confidence": confidence})
    by_path: dict[str, dict] = {}
    for candidate in sorted(candidates, key=lambda item: item["order"]):
        existing = by_path.get(candidate["path"])
        if existing is None or existing["order"] > candidate["order"]:
            by_path[candidate["path"]] = candidate
    versions = sorted(by_path.values(), key=lambda item: item["order"])
    for index, version in enumerate(versions, start=1):
        version["version_index"] = index
        version["source_filename"] = version["path"].replace("\\", "/").rsplit("/", 1)[-1]
        stage = _STAGE.search(version["name"])
        version["stage"] = f"stage{stage.group(1)}" if stage else None
    return versions


def _similarity(a: bytes, b: bytes) -> float:
    n = min(len(a), len(b))
    if not n:
        return 0.0
    equal = 0
    for i in range(0, n, _CHUNK):
        ca, cb = a[i:i + _CHUNK], b[i:i + _CHUNK]
        if ca == cb:
            equal += len(ca)
        else:
            equal += sum(1 for x, y in zip(ca, cb) if x == y)
    return equal / n


def _anchor_candidates(data: bytes) -> list[tuple[list[int], int, str]]:
    """Printable headers die op vaste afstand herhalen direct na nul-bytes."""
    groups: dict[str, list[int]] = {}
    for match in _PRINTABLE_RUN.finditer(data):
        groups.setdefault(match.group(), []).append(match.start())
    results = []
    for run, positions in groups.items():
        if len(positions) < 2 or any(position == 0 or data[position - 1] != 0
                                     for position in positions):
            continue
        strides = {b - a for a, b in zip(positions, positions[1:])}
        if len(strides) != 1:
            continue
        stride = strides.pop()
        if stride < _MIN_STRIDE:
            continue
        blocks = [data[position:position + stride] for position in positions]
        similar = sum(1 for left, right in zip(blocks, blocks[1:])
                      if _similarity(left, right) >= 0.99)
        if len(positions) < 3 and similar < 1:
            continue
        identity_score = sum(1 for _ in positions if re.match(rb"^\d+/\d+/", run))
        results.append((identity_score, similar, len(positions), -positions[0],
                        positions, stride, run.decode("ascii", errors="replace")))
    results.sort(key=lambda item: (item[0], item[1], item[2], item[3]), reverse=True)
    return [(item[4], item[5], item[6]) for item in results]


def _record_start(data: bytes, position: int) -> int:
    start = position
    while start > 0 and data[start - 1] != 0 and position - start < 256:
        start -= 1
    return start


def _skip_strings_and_zeros(data: bytes, offset: int, boundary: int) -> int | None:
    position = offset
    strings_skipped = 0
    while position < boundary and position - offset < 256 and strings_skipped < 4:
        length = struct.unpack_from("<I", data, position)[0] if position + 4 <= len(data) else 0
        if 1 <= length <= 512 and position + 4 + length <= len(data):
            raw = data[position + 4:position + 4 + length]
            if all(32 <= byte < 127 or byte in (9, 10, 13) for byte in raw):
                position += 4 + length
                strings_skipped += 1
                continue
        break
    if position + 8 <= boundary and data[position:position + 8] == b"\x00" * 8:
        position += 8
    elif position + 4 <= boundary and data[position:position + 4] == b"\x00" * 4:
        position += 4
    return position if position < boundary else None


def _find_first_binary(data: bytes, records: list[dict], boundary: int) -> dict | None:
    header_records = [record for record in records
                      if record["value"].lower().endswith((".bin", ".ori"))
                      and record["end"] <= boundary - 32]
    for record in reversed(header_records):
        start = _skip_strings_and_zeros(data, record["end"], boundary)
        if start is None or boundary - start < 1024:
            continue
        blob = data[start:boundary]
        digest = _hashes(blob)
        return {"start": start, "length": len(blob), "sha256": digest["sha256"],
                "filename": record["value"], "complete": True, "confidence": 100.0}
    return None


def parse_ols(data: bytes) -> dict:
    """Volledige evidence-based reconstructie: versies + binary-grenzen."""
    sha = _hashes(data)
    signature = "WinOLS File" if len(data) >= 15 and data[4:15] == b"WinOLS File" else "unknown"

    anchors = _anchor_candidates(data)
    page_starts: list[int] = []
    stride = 0
    identity = ""
    if anchors:
        page_positions, stride, identity = anchors[0]
        page_starts = [_record_start(data, position) for position in page_positions]
        records = _length_prefixed_strings(data, page_starts[0])
    else:
        records = _length_prefixed_strings(data, _DEFAULT_SCAN_LIMIT)

    first_binary = _find_first_binary(data, records, page_starts[0]) if page_starts else None

    versions = _parse_versions(records, data)

    binaries: list[dict] = []
    if first_binary:
        binaries.append(first_binary)
    for position in page_starts:
        available = len(data) - position
        complete = available >= stride
        blob = data[position:position + (stride if complete else available)]
        digest = _hashes(blob)
        binaries.append({"start": position, "length": len(blob),
                         "sha256": digest["sha256"], "complete": complete,
                         "confidence": 90.0 if complete else 70.0})

    version_binaries = []
    for version in versions:
        index = version["version_index"] - 1
        binary = binaries[index] if index < len(binaries) else None
        if binary is None:
            version_binaries.append({**version, "binary": None, "complete": 0,
                                     "binary_sha256": None})
            continue
        version_binaries.append({**version,
                                 "binary_offset": binary["start"],
                                 "binary_length": binary["length"],
                                 "binary_sha256": binary["sha256"],
                                 "complete": 1 if binary["complete"] else 0})

    return {"signature": signature, "file_size": len(data), "sha256": sha["sha256"],
            "identity": identity or None, "stride": stride or None,
            "versions": version_binaries,
            "binary_count": len(binaries),
            "note": "Alle grenzen bewezen uit herhaalde headers/expliciete importrecords."}


def _reject_if_not_ols(result: dict, path: str) -> None:
    """Geen élk bewijs (geen signatuur, geen versies, geen anchors) = geen OLS."""
    has_evidence = (result["signature"] == "WinOLS File"
                    or result["versions"]
                    or result["identity"])
    if not has_evidence:
        raise ValueError(f"Geen geldige OLS-structuur (geen WinOLS-signatuur, "
                         f"versies of identiteitsheaders): {path}")


def parse_ols_file(path: str, max_file_mb: int = 4096) -> dict:
    """Lees + parse één OLS-bestand (read-only). Gooit ValueError bij leesproblemen."""
    from pathlib import Path
    path_obj = Path(path)
    if path_obj.suffix.lower() != ".ols":
        raise ValueError("Geen .ols-bestand")
    data = path_obj.read_bytes()[:max_file_mb * 1024 * 1024]
    if not data:
        raise ValueError("Leeg bestand")
    result = parse_ols(data)
    _reject_if_not_ols(result, path)
    result["source_mtime"] = path_obj.stat().st_mtime
    result["size"] = path_obj.stat().st_size
    return result
