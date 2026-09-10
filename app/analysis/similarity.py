"""Exact positional similarity; compatibility is a separate heuristic."""
import numpy as np
from app.analysis.fingerprint import fingerprint


def compare(a: bytes, b: bytes, metadata_a: dict, metadata_b: dict,
            block_size: int = 4096) -> dict:
    n, total = min(len(a), len(b)), max(len(a), len(b))
    equal = np.frombuffer(a[:n], dtype=np.uint8) == np.frombuffer(b[:n], dtype=np.uint8)
    matches = int(np.count_nonzero(equal))
    score = 100 * matches / total if total else 100.0
    padded = np.concatenate(([False], equal, [False])).astype(np.int8)
    edges = np.flatnonzero(np.diff(padded))
    longest = int(np.max(edges[1::2] - edges[::2])) if edges.size else 0
    fa, fb = fingerprint(a, block_size), fingerprint(b, block_size)
    blocks = sum(x == y for x, y in zip(fa["blocks"], fb["blocks"]))
    conflicts, agreements = [], []
    for field in ("software_number", "hardware_number", "calibration_number", "ecu_family"):
        x, y = metadata_a.get(field), metadata_b.get(field)
        if x and y:
            (agreements if x == y else conflicts).append(field)
    confidence = min(70.0, score * .5 + len(agreements) * 5)
    status = "near_identical_unverified"
    if a == b:
        confidence = 100.0
        status = "identical_bytes"
    if len(a) != len(b):
        confidence = min(confidence, 20.0)
        status = "size_mismatch"
    if conflicts:
        confidence = min(confidence, 10.0)
        status = "metadata_conflict"
    # A matching value in a small calibration range cannot outweigh a different
    # software base.  Do not present it as a transferable recipe.
    if score < 60.0:
        confidence = 0.0
        status = "incompatible_base"
    return dict(match_score=round(score, 4), compatibility_confidence=round(confidence, 2),
                compatibility_status=status,
                identical_bytes=matches, longest_identical_range=longest,
                identical_blocks=blocks, metadata_conflicts=conflicts,
                metadata_agreements=agreements,
                reasons=[f"{matches}/{total} bytes gelijk op dezelfde offset",
                         f"{blocks} identieke blokken; langste gelijke reeks {longest} bytes",
                         f"Grootte {'gelijk' if len(a) == len(b) else 'verschillend'}",
                         f"Metadata: {len(agreements)} gelijk, {len(conflicts)} conflicten",
                         ("Basisovereenkomst onder 60%: bekende wijzigingsgebieden worden niet als overdraagbaar getoond."
                          if status == "incompatible_base" else
                          "Compatibiliteit is een heuristiek, geen goedkeuring voor tuning of flashen.")])
