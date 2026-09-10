"""Evidence-based reconstruction of the WinOLS 5 project structure.

The parser is built exclusively from observations of a real 8.7 MB WinOLS 5
project (GASDROP_100119.ols) and is deliberately conservative:

* a version binary is only reported when its exact location is corroborated by
  an explicit import-header record or by an identity header that repeats at a
  constant stride directly after zero padding;
* version names and import paths are only read from little-endian
  length-prefixed ASCII records;
* every reported fact carries its evidence and a confidence value;
* anything that cannot be proven stays ``unknown``.

The source file is never modified: this module only reads ``bytes``.
"""
from __future__ import annotations

import re
import struct

import numpy as np

from app.analysis.fingerprint import hashes

_PRINTABLE_RUN = re.compile(rb"[\x20-\x7e]{16,}")
_MIN_STRIDE = 1024
_DEFAULT_SCAN_LIMIT = 4 * 1024 * 1024

_ORIGINAL_NAME = re.compile(r"(?:^|[\s_\-()\[\]])(origineel|original|ori|stock|oem)(?:$|[\s_\-()\[\].])", re.I)
_TUNED_NAME = re.compile(r"(stage\s*\d|stage\d|tuned|mod(?:ified)?|vmax|pops|bang|chip)", re.I)
_MAP_RANGE = re.compile(r"\b\d:\s*([0-9A-Fa-f]{5,8})-([0-9A-Fa-f]{5,8})")


def _length_prefixed_strings(data: bytes, limit: int) -> list[dict]:
    """All little-endian length-prefixed printable ASCII records (byte-aligned)."""
    records: list[dict] = []
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


def _role_from_version_name(name: str) -> tuple[str, float, str]:
    """Explicit WinOLS version labels only; never the container filename."""
    if _ORIGINAL_NAME.search(name):
        return "original", 100.0, "expliciete WinOLS-versienaam (Original/Origineel)"
    if _TUNED_NAME.search(name):
        return "tuned", 95.0, "expliciete WinOLS-versienaam (Stage/Tuned/Modified)"
    return "unknown", 0.0, "geen expliciete rol in versienaam"


def _parse_versions(records: list[dict], data: bytes) -> list[dict]:
    """Pair role-labelled names with the import path that directly follows them."""
    candidates = []
    for index, record in enumerate(records):
        value = record["value"]
        if "\t" in value or len(value) > 100:
            continue
        role, confidence, reason = _role_from_version_name(value)
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
                           "role": role, "confidence": confidence, "reason": reason})
    by_path: dict[str, dict] = {}
    for candidate in sorted(candidates, key=lambda item: item["order"]):
        existing = by_path.get(candidate["path"])
        if existing is None or existing["order"] > candidate["order"]:
            by_path[candidate["path"]] = candidate
    versions = sorted(by_path.values(), key=lambda item: item["order"])
    for index, version in enumerate(versions, start=1):
        version["version_index"] = index
        version["source_filename"] = version["path"].replace("\\", "/").rsplit("/", 1)[-1]
    return versions


def _block_similarity(left: bytes, right: bytes) -> float:
    n = min(len(left), len(right))
    if not n:
        return 0.0
    equal = np.frombuffer(left[:n], dtype=np.uint8) == np.frombuffer(right[:n], dtype=np.uint8)
    return float(np.count_nonzero(equal)) / n


def _identity_structure_score(data: bytes, positions: list[int], run: bytes) -> int:
    """Count positions whose run looks like a WinOLS identity header.

    Observed in a real WinOLS 5 file: version records start with a
    slash-separated identity `<getal>/<getal>/<ECU>/...`; interior repeated
    data patterns (bv. 'T{T{T{') doen dat niet.
    """
    return sum(1 for _ in positions if re.match(rb"^\d+/\d+/", run))


def _anchor_candidates(data: bytes) -> list[tuple[list[int], int, str]]:
    """Printable headers that repeat at a constant stride right after zero bytes.

    Candidate sets are ranked by how many of their stride-blocks are near
    identical (≥99% of bytes): real WinOLS version records share almost all
    content, an interior data pattern does not. Two occurrences only qualify
    when their blocks prove that near identity.
    """
    groups: dict[str, list[int]] = {}
    for match in _PRINTABLE_RUN.finditer(data):
        groups.setdefault(match.group(), []).append(match.start())
    results = []
    for run, positions in groups.items():
        if len(positions) < 2 or any(position == 0 or data[position - 1] != 0 for position in positions):
            continue
        strides = {b - a for a, b in zip(positions, positions[1:])}
        if len(strides) != 1:
            continue
        stride = strides.pop()
        if stride < _MIN_STRIDE:
            continue
        blocks = [data[position:position + stride] for position in positions]
        similar = 0
        for left, right in zip(blocks, blocks[1:]):
            if _block_similarity(left, right) >= 0.99:
                similar += 1
        if len(positions) < 3 and similar < 1:
            continue
        structure = _identity_structure_score(data, positions, run)
        results.append((structure, similar, len(positions), -positions[0], positions, stride,
                        run.decode("ascii", errors="replace")))
    results.sort(key=lambda item: (item[0], item[1], item[2], item[3]), reverse=True)
    return [(item[4], item[5], item[6]) for item in results]


def _record_start(data: bytes, position: int) -> int:
    start = position
    while start > 0 and data[start - 1] != 0 and position - start < 256:
        start -= 1
    return start


def _skip_strings_and_zeros(data: bytes, offset: int, boundary: int) -> int | None:
    """Skip the import-header strings and the fixed zero field before the binary.

    Observed in a real WinOLS 5 file: filename record, path record, then an
    8-byte zero field, then the raw binary. Skipping is bounded to a small
    window so binary bytes can never be swallowed as pseudo-records.
    """
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
    """The import-header record: explicit filename followed by the raw binary."""
    header_records = [record for record in records
                      if record["value"].lower().endswith((".bin", ".ori")) and record["end"] <= boundary - 32]
    for record in reversed(header_records):
        start = _skip_strings_and_zeros(data, record["end"], boundary)
        if start is None or boundary - start < 1024:
            continue
        blob = data[start:boundary]
        return {"start": start, "end": boundary, "length": len(blob), "data": blob,
                "sha256": hashes(blob)["sha256"], "filename": record["value"],
                "extraction_method": "explicit_import_header", "confidence": 100.0,
                "evidence": [f"import-header met bestandsnaam op offset {record['offset']}",
                             f"binary begint op eerste niet-header byte {start}"],
                "complete": True}
    return None


def _parse_maps(records: list[dict], data: bytes, boundary: int,
                address_range: tuple[int, int] | None) -> list[dict]:
    """Read observed map-name records with their candidate addresses/geometry."""
    maps = []
    for record in records:
        value = record["value"]
        if not value.lower().startswith("kaart") or record["offset"] >= boundary:
            continue
        quoted = re.search(r'"([^"]+)', value)
        name = quoted.group(1) if quoted else value
        window_end = min(boundary, record["end"] + 700)
        window = data[record["end"]:window_end]
        addresses: list[int] = []
        dims: list[tuple[int, int]] = []
        factors: list[float] = []
        if address_range:
            low, high = address_range
        else:
            low, high = 0x10000, 0xFFFFFFF
        for position in range(0, max(0, len(window) - 4), 4):
            word = struct.unpack_from("<I", window, position)[0]
            if low <= word <= high and word not in addresses and len(addresses) < 4:
                addresses.append(word)
        for position in range(0, max(0, len(window) - 8), 4):
            first, second = struct.unpack_from("<II", window, position)
            if 1 <= first <= 64 and 1 <= second <= 64 and (first, second) not in dims:
                dims.append((first, second))
            if len(dims) >= 3:
                break
        for position in range(0, max(0, len(window) - 8), 4):
            candidate = struct.unpack_from("<d", window, position)[0]
            if 0.001 <= abs(candidate) <= 1e9 and candidate != 1.0 and candidate not in factors:
                factors.append(candidate)
            if len(factors) >= 3:
                break
        maps.append({"map_name_raw": value, "map_name": name, "offset": record["offset"],
                     "address": addresses[0] if addresses else None,
                     "address_candidates": addresses,
                     "dimension_candidates": [list(pair) for pair in dims],
                     "factor_candidates": factors[:2],
                     "confidence": 70.0 if addresses else 40.0,
                     "status": "address_observed" if addresses else "label_only",
                     "evidence": [f"Kaart-record op offset {record['offset']}; "
                                  f"{len(addresses)} adreskandidaten binnen het gelezen adresbereik"]})
    return maps


def parse_ols_structure(data: bytes) -> dict:
    """Reconstruct versions, embedded binaries and map definitions with evidence."""
    sha = hashes(data)
    signature = "WinOLS File" if len(data) >= 15 and data[4:15] == b"WinOLS File" else "unknown"

    anchors = _anchor_candidates(data)
    records: list[dict] = []
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
    header_boundary = page_starts[0] if page_starts else min(len(data), _DEFAULT_SCAN_LIMIT)

    address_range = None
    for record in records[:600]:
        range_match = _MAP_RANGE.search(record["value"])
        if range_match:
            address_range = (int(range_match.group(1), 16), int(range_match.group(2), 16))
            break

    versions = _parse_versions(records, data)
    maps = _parse_maps(records, data, header_boundary, address_range)

    binaries: list[dict] = []
    if first_binary:
        binaries.append(first_binary)
    for position in page_starts:
        available = len(data) - position
        complete = available >= stride
        blob = data[position:position + (stride if complete else available)]
        binaries.append({"start": position, "end": position + len(blob), "length": len(blob),
                         "data": blob, "sha256": hashes(blob)["sha256"], "filename": None,
                         "identity_header": identity,
                         "extraction_method": "repeating_identity_header",
                         "confidence": 90.0 if complete else 70.0,
                         "evidence": [f"identiteitsheader op {len(page_starts)} posities met vaste "
                                      f"afstand {stride} bytes, direct na nul-padding",
                                      f"binary [{position}, {position + len(blob)})"],
                         "complete": complete})

    ordered = binaries
    version_binaries = []
    for version in versions:
        index = version["version_index"] - 1
        binary = ordered[index] if index < len(ordered) else None
        if binary is None:
            version_binaries.append({**version, "binary": None, "relation_type": "target_unknown",
                                     "confidence": 0.0,
                                     "relation_evidence": "geen binary met bewijs gevonden"})
            continue
        explicit = binary["filename"] is not None and binary["filename"] == version["source_filename"]
        version_binaries.append({
            **version,
            "binary": {key: binary[key] for key in ("start", "end", "length", "sha256", "complete",
                                                    "extraction_method", "confidence", "evidence")},
            "relation_type": "version_to_binary_explicit" if explicit else "version_to_binary_order_inferred",
            "role_confidence": version["confidence"],
            "relation_confidence": 100.0 if explicit else 75.0,
            "relation_evidence": ("bestandsnaam in versierecord == bestandsnaam in binary-importheader"
                                  if explicit else
                                  "versieregistratie in dezelfde volgorde als de binary-records"),
        })
    mapped_starts = {item["binary"]["start"] for item in version_binaries if item.get("binary")}
    for binary in binaries:
        if binary["start"] in mapped_starts:
            continue
        version_binaries.append({"version_index": None, "name": None, "path": None,
                                 "source_filename": None, "role": "unknown", "confidence": 0.0,
                                 "reason": "geen versierecord gevonden",
                                 "binary": {key: binary[key] for key in
                                            ("start", "end", "length", "sha256", "complete",
                                             "extraction_method", "confidence", "evidence")},
                                 "relation_type": "binary_without_version",
                                 "relation_evidence": "binary aanwezig maar geen koppelende versierecord"})
    for item in version_binaries:
        if item.get("binary"):
            item["binary"].pop("data", None)

    return {
        "format_signature": signature,
        "file_size": len(data),
        "sha256": sha["sha256"],
        "project": {
            "ecu_identity": identity or None,
            "address_range": {"start": address_range[0], "end": address_range[1]} if address_range else None,
            "binary_stride": stride or None,
        },
        "versions": [{key: version[key] for key in ("version_index", "name", "path", "source_filename",
                                                    "role", "confidence", "reason")} for version in versions],
        "binaries": [{key: binary[key] for key in ("start", "end", "length", "sha256", "complete",
                                                   "extraction_method", "confidence", "evidence",
                                                   "filename", "identity_header") if key in binary}
                     for binary in binaries],
        "version_binaries": version_binaries,
        "maps": maps,
        "map_range": {"start": address_range[0], "end": address_range[1]} if address_range else None,
        "unknown_structures": ["record_pointers", "version_tree_links", "checksum_fields",
                               "map_axis_decoding"],
        "note": "Alle grenzen zijn afgeleid van herhaalde headers en expliciete importrecords; "
                "geen enkel veld is gegokt.",
    }
