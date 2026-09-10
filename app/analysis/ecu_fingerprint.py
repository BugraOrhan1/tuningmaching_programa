"""Reproducible structural fingerprints for ECU binaries, without ECU guesses."""
from __future__ import annotations

import hashlib
import math
from collections import Counter

import numpy as np


def _entropy(chunk: bytes) -> float:
    if not chunk:
        return 0.0
    counts = np.bincount(np.frombuffer(chunk, dtype=np.uint8), minlength=256)
    probabilities = counts[counts > 0] / len(chunk)
    return round(float(-np.sum(probabilities * np.log2(probabilities))), 6)


def _runs(data: bytes, value: int, minimum: int = 64) -> list[dict]:
    matching = np.frombuffer(data, dtype=np.uint8) == value
    if not matching.any():
        return []
    edges = np.flatnonzero(np.diff(np.concatenate(([False], matching, [False])).astype(np.int8)))
    return [{"start": int(start), "end": int(end), "length": int(end-start)}
            for start, end in zip(edges[::2], edges[1::2]) if end-start >= minimum]


def ecu_family_fingerprint(data: bytes, segment_size: int = 65536) -> dict:
    """Stable coarse features suitable for filtering, never for tuning output."""
    if segment_size <= 0:
        raise ValueError("segment_size must be positive")
    segments = [data[offset:offset + segment_size] for offset in range(0, len(data), segment_size)]
    entropy = [_entropy(segment) for segment in segments]
    repeated = []
    for offset, segment in enumerate(segments):
        digest = hashlib.sha256(segment).hexdigest()
        repeated.append(digest)
    counts = Counter(repeated)
    return {
        "version": 1,
        "file_size": len(data),
        "segment_size": segment_size,
        "entropy_profile": entropy,
        "zero_regions": _runs(data, 0),
        "ff_regions": _runs(data, 255),
        "segment_hashes": repeated,
        "repeated_segment_hashes": sorted(key for key, count in counts.items() if count > 1),
        "mean_entropy": round(sum(entropy) / len(entropy), 6) if entropy else 0.0,
    }


def structural_similarity(left: dict, right: dict) -> float:
    """Compare stored coarse fingerprints; returns 0–100, only as a filter signal."""
    if left["file_size"] != right["file_size"]:
        return 0.0
    a, b = left["segment_hashes"], right["segment_hashes"]
    identical = sum(x == y for x, y in zip(a, b)) / max(1, max(len(a), len(b)))
    entropy_distance = sum(abs(x-y) for x, y in zip(left["entropy_profile"], right["entropy_profile"])) / max(1, len(a))
    entropy_score = max(0.0, 1 - entropy_distance / 8)
    return round(100 * (0.7 * identical + 0.3 * entropy_score), 4)
