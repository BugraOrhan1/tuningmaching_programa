"""V3 TuningRegion: rijke, evidence-based wijzigingsregio's. Alleen analyse.

Alle signatures zijn bewust onafhankelijk van absolute offsets: structuur
wordt beschreven met relatieve posities binnen de regio en gekwantiseerde
waarden, zodat dezelfde structuur in andere softwarevarianten herkenbaar is
(zie EVIDENCE_MODEL.md). Niets hier gokt mapnamen of -functies.
"""
from __future__ import annotations

import hashlib
import json
import math

import numpy as np

CONTEXT_BYTES = 32
SMALL_PARAMETER_MAX = 8
CLUSTER_MIN = 512
_MAX_DELTA_SAMPLES = 256
_DELTA_CLIP = 32


def entropy(data: bytes) -> float:
    """Shannon-entropie in bits/byte van een bytereeks."""
    if not data:
        return 0.0
    counts = np.bincount(np.frombuffer(data, dtype=np.uint8), minlength=256)
    probabilities = counts[counts > 0] / len(data)
    return float(-(probabilities * np.log2(probabilities)).sum())


def _quantize_delta(difference: int) -> int:
    return max(-_DELTA_CLIP, min(_DELTA_CLIP - 1, difference))


def _padded_pair(original_region: bytes, tuned_region: bytes) -> tuple[np.ndarray, np.ndarray]:
    """Gelijke lengte met nulpadding zodat tail-regio's (toegevoegde bytes)
    vergelijkbaar blijven; verschil met 0 telt als wijziging."""
    size = max(len(original_region), len(tuned_region))
    original = np.frombuffer(original_region, dtype=np.uint8).astype(np.int64)
    tuned = np.frombuffer(tuned_region, dtype=np.uint8).astype(np.int64)
    return (np.pad(original, (0, size - len(original))),
            np.pad(tuned, (0, size - len(tuned))))


def delta_features(original_region: bytes, tuned_region: bytes) -> dict:
    """Deterministische deltasamenvatting van gewijzigde bytes."""
    original, tuned = _padded_pair(original_region, tuned_region)
    mask = original != tuned
    deltas = tuned[mask] - original[mask]
    if not deltas.size:
        return {"changed": 0}
    quantized = [_quantize_delta(int(value)) for value in deltas]
    unique, counts = np.unique(np.asarray(quantized), return_counts=True)
    order = np.argsort(-counts)
    return {
        "changed": int(deltas.size),
        "mean_delta": round(float(deltas.mean()), 3),
        "sign_up": int((deltas > 0).sum()),
        "sign_down": int((deltas < 0).sum()),
        "unique_buckets": int(unique.size),
        "top_buckets": [(int(unique[i]), int(counts[i])) for i in order[:6]],
    }


def delta_signature(original_region: bytes, tuned_region: bytes) -> str:
    """Hash van de gekwantiseerde deltareeks (relatief binnen de regio)."""
    features = delta_features(original_region, tuned_region)
    original, tuned = _padded_pair(original_region, tuned_region)
    mask = original != tuned
    deltas = (tuned[mask] - original[mask])[:_MAX_DELTA_SAMPLES]
    payload = {"features": features,
               "sequence": [_quantize_delta(int(value)) for value in deltas]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def structure_features(block: dict, original_region: bytes, tuned_region: bytes) -> dict:
    """Uitlegbare, offset-onafhankelijke structuurkenmerken van een regio."""
    length = max(1, block["length"])
    density = block.get("changed_percentage", block.get("change_percentage", 0.0))
    original_padded, tuned_padded = _padded_pair(original_region, tuned_region)
    mask = original_padded != tuned_padded
    indices = np.flatnonzero(mask)
    pattern = sorted({int(round(position / length * 32)) for position in indices})
    length_bucket = round(math.log2(length), 1)
    transitions = int((np.diff(mask.astype(np.int8)) != 0).sum())
    return {
        "length_bucket": length_bucket,
        "density_bucket": round(density, -1),
        "change_pattern_32": pattern,
        "transitions": transitions,
        "entropy_before_bucket": round(entropy(original_region), 1),
        "entropy_delta_bucket": round(entropy(tuned_region) - entropy(original_region), 1),
        "delta_summary": {key: value for key, value in delta_features(original_region, tuned_region).items()
                          if key != "top_buckets"},
    }


def structural_signature(features: dict) -> str:
    return hashlib.sha256(json.dumps(features, sort_keys=True).encode()).hexdigest()


def signature_similarity(left: dict, right: dict) -> float:
    """Deterministische gelijkenis tussen twee structure_features-dicten (0..1).

    Componenten (elk even zwaar): lengtebucket, dichtheidsbucket, overlap van
    het veranderingspatroon, transities, entropie vóór, entropie-delta,
    deltasamenvatting (gemiddelde delta + tekenverdeling).
    """
    def closeness(a: float, b: float, tolerance: float) -> float:
        return max(0.0, 1.0 - abs(a - b) / tolerance)

    pattern_overlap = 0.0
    a_pattern, b_pattern = set(left["change_pattern_32"]), set(right["change_pattern_32"])
    if a_pattern or b_pattern:
        pattern_overlap = len(a_pattern & b_pattern) / max(1, len(a_pattern | b_pattern))
    a_delta, b_delta = left["delta_summary"], right["delta_summary"]
    total_a = max(1, a_delta.get("sign_up", 0) + a_delta.get("sign_down", 0))
    total_b = max(1, b_delta.get("sign_up", 0) + b_delta.get("sign_down", 0))
    up_a, up_b = a_delta.get("sign_up", 0) / total_a, b_delta.get("sign_up", 0) / total_b
    parts = [
        closeness(left["length_bucket"], right["length_bucket"], 2.0),
        closeness(left["density_bucket"], right["density_bucket"], 40.0),
        pattern_overlap,
        closeness(left["transitions"], right["transitions"], max(8, left["transitions"] + right["transitions"])),
        closeness(left["entropy_before_bucket"], right["entropy_before_bucket"], 3.0),
        closeness(left["entropy_delta_bucket"], right["entropy_delta_bucket"], 2.0),
        closeness(a_delta.get("mean_delta", 0.0), b_delta.get("mean_delta", 0.0), 48.0),
        closeness(up_a, up_b, 0.6),
    ]
    return round(sum(parts) / len(parts), 6)


def _context(data: bytes, start: int, end: int) -> tuple[str, str, str, str]:
    before = data[max(0, start - CONTEXT_BYTES):start]
    after = data[end:end + CONTEXT_BYTES]
    context = data[max(0, start - CONTEXT_BYTES):min(len(data), end + CONTEXT_BYTES)]
    return (before.hex(), after.hex(), hashlib.sha256(before).hexdigest(),
            hashlib.sha256(context).hexdigest())


def _classify(original_region: bytes, tuned_region: bytes, length: int) -> tuple[str, float]:
    """Regio-klasse op detecteerbare regels; nooit gegokt.

    padding: beide zijden alleen 0x00/0xFF-vulling.
    small_parameter: <= 8 bytes.
    calibration_region / calibration_cluster: lengtegebonden.
    checksum/code: NIET automatisch — blijft 'unknown' (zie EVIDENCE_MODEL.md).
    """
    del tuned_region  # vulling-regel geldt voor beide kanten
    if set(original_region) <= {0x00, 0xFF}:
        return "padding", 10.0
    if length <= SMALL_PARAMETER_MAX:
        return "small_parameter", 0.0
    if length >= CLUSTER_MIN:
        return "calibration_cluster", 0.0
    return "calibration_region", 0.0


def region_confidence(region_class: str, changed_percentage: float, length: int,
                      cross_pair_shared: bool = False) -> float:
    """Gedocumenteerde formule (EVIDENCE_MODEL.md): basis 50, dichtheidsbonus
    tot +30, lengtebonus tot +20, checksum-kandidaat gebonden aan 40,
    padding op 10. Geen verborgen gewichten."""
    if region_class == "padding":
        return 10.0
    confidence = 50.0 + min(30.0, changed_percentage / 10.0) + min(20.0, length / 256.0 * 20.0)
    if region_class == "checksum_candidate":
        confidence = min(confidence, 40.0)
    if cross_pair_shared:
        confidence = min(confidence + 5.0, 99.0)
    return round(min(confidence, 99.0), 2)


def build_regions(original: bytes, tuned: bytes, blocks: list[dict], stage: str | None = None,
                  file_metadata: dict | None = None) -> list[dict]:
    """Verrijk diff-blokken tot TuningRegion-objecten (V3-§3).

    Checksumgebieden worden hier niet als tuninggebied gemarkeerd: zonder
    cross-paar-bewijs blijft de klasse 'unknown' en volgt alleen uit latere
    patroonanalyse (cross_pair_shared). Nooit mapnamen.
    """
    metadata = file_metadata or {}
    regions = []
    for seq, block in enumerate(blocks):
        start, end = block["start_offset"], block["end_offset"]
        density = block.get("changed_percentage", block.get("change_percentage", 0.0))
        original_region, tuned_region = original[start:end], tuned[start:end]
        before_hex, after_hex, before_hash, context_hash = _context(original, start, end)
        _, _, _, tuned_context_hash = _context(tuned, start, end)
        features = structure_features(block, original_region, tuned_region)
        region_class, _ = _classify(original_region, tuned_region, block["length"])
        regions.append({
            "seq": seq,
            "start_offset": start, "end_offset": end, "length": block["length"],
            "changed_byte_count": block["changed_bytes"],
            "changed_percentage": density,
            "original_bytes_hash": block["original_hash"], "tuned_bytes_hash": block["tuned_hash"],
            "before_context": before_hex, "after_context": after_hex,
            "original_context_hash": before_hash,
            "original_region_context_hash": context_hash,
            "tuned_context_hash": tuned_context_hash,
            "relative_start": round(start / max(1, len(original)), 8),
            "relative_end": round(end / max(1, len(original)), 8),
            "structural_signature": structural_signature(features),
            "delta_signature": delta_signature(original_region, tuned_region),
            "structure_features": features,
            "entropy_before": round(entropy(original_region), 4),
            "entropy_after": round(entropy(tuned_region), 4),
            "region_class": region_class,
            "checksum_status": "UNKNOWN",
            "cross_pair_shared": False,
            "alignment_confidence": 100.0,  # binnen het paar is de offset exact
            "map_confidence": 0.0, "map_type": "unknown",
            "stage": stage,
            "ecu_family": metadata.get("ecu_family"), "software_number": metadata.get("software_number"),
            "calibration_number": metadata.get("calibration_number"),
            "hardware_number": metadata.get("hardware_number"),
            "project": metadata.get("project"),
            "evidence": [{"type": "diff_block_v2", "merge_gap": None,
                          "start": start, "end": end,
                          "changed_bytes": block["changed_bytes"],
                          "note": "Regio uit deterministische numpy-diff; "
                                  "offsetconventie [start, end)."}],
            "confidence": region_confidence(region_class, density, block["length"]),
            "status": "candidate",
        })
    return regions


def mark_checksum_candidates(regions: list[dict]) -> list[dict]:
    """Markeer regio's als checksum_candidate op het enige defensible bewijs:
    dezelfde relatieve regio verandert in >= 3 paren uit >= 2 verschillende
    ECU-families met onderling verschillende tuned-inhoud. Andere 'check-
    sum'-conclusies zijn gegokt en worden bewust niet gedaan."""
    groups: dict[tuple[float, int], list[dict]] = {}
    for region in regions:
        groups.setdefault((round(region["relative_start"], 3), region["length"]), []).append(region)
    for members in groups.values():
        families = {region.get("ecu_family") or "unknown" for region in members}
        tuned_hashes = {region["tuned_bytes_hash"] for region in members}
        if len(members) >= 3 and len(families) >= 2 and len(tuned_hashes) >= 3:
            for region in members:
                region["region_class"] = "checksum_candidate"
                region["cross_pair_shared"] = True
                region["confidence"] = min(region["confidence"], 40.0)
                region["evidence"].append({
                    "type": "cross_pair_shared_area",
                    "pairs": len(members), "ecu_families": len(families),
                    "note": "Gedeelde wijzigingsplaats over verschillende ECU-families; "
                            "checksum-kandidaat, geen tuninggebied."})
    return regions
