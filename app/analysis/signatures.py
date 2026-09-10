"""Masked binary signatures and conservative candidate discovery."""
from __future__ import annotations

import hashlib
from collections import Counter


def matches_signature(data: bytes, offset: int, signature: bytes, mask: bytes) -> bool:
    if len(signature) != len(mask) or offset < 0 or offset + len(signature) > len(data):
        return False
    return all((actual & bitmask) == (expected & bitmask)
               for actual, expected, bitmask in zip(data[offset:offset + len(signature)], signature, mask))


def discover_candidate_signatures(samples: list[bytes], min_length: int = 16,
                                  max_candidates: int = 20, max_length: int = 64) -> list[dict]:
    """Find ranges stable across every supplied sample; requires ≥3 samples."""
    if len(samples) < 3:
        return []
    length = min(map(len, samples))
    candidates, start = [], None
    for offset in range(length):
        stable = len({sample[offset] for sample in samples}) == 1
        if stable and start is None:
            start = offset
        elif not stable and start is not None:
            if offset - start >= min_length:
                segment = samples[0][start:min(offset, start + max_length)]
                candidates.append({"offset": start, "length": len(segment), "signature_data": segment.hex(),
                                   "mask_data": (b"\xff" * len(segment)).hex(), "sample_count": len(samples),
                                   "confidence": min(90.0, 50 + len(samples) * 5), "status": "candidate",
                                   "digest": hashlib.sha256(segment).hexdigest()})
            start = None
    if start is not None and length - start >= min_length:
        segment = samples[0][start:min(length, start + max_length)]
        candidates.append({"offset": start, "length": len(segment), "signature_data": segment.hex(),
                           "mask_data": (b"\xff" * len(segment)).hex(), "sample_count": len(samples),
                           "confidence": min(90.0, 50 + len(samples) * 5), "status": "candidate",
                           "digest": hashlib.sha256(segment).hexdigest()})
    return sorted(candidates, key=lambda item: item["length"], reverse=True)[:max_candidates]
