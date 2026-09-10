"""Half-open byte ranges [start, end); includes appended and removed bytes."""
import hashlib
import numpy as np


def diff_blocks(original: bytes, tuned: bytes, merge_gap: int = 8) -> list[dict]:
    if merge_gap < 0:
        raise ValueError("merge_gap must be nonnegative")
    common = min(len(original), len(tuned))
    mask = np.ones(max(len(original), len(tuned)), dtype=bool)
    mask[:common] = (np.frombuffer(original[:common], dtype=np.uint8) !=
                     np.frombuffer(tuned[:common], dtype=np.uint8))
    indices = np.flatnonzero(mask)
    if not indices.size:
        return []
    boundaries = np.flatnonzero(np.diff(indices) > merge_gap + 1) + 1
    result = []
    for group in np.split(indices, boundaries):
        start, end = int(group[0]), int(group[-1]) + 1
        result.append(dict(start_offset=start, end_offset=end, length=end-start,
                           changed_bytes=len(group), change_percentage=100*len(group)/(end-start),
                           original_hash=hashlib.sha256(original[start:end]).hexdigest(),
                           tuned_hash=hashlib.sha256(tuned[start:end]).hexdigest()))
    return result


def hex_rows(original: bytes, tuned: bytes, start: int, count: int = 256) -> list[dict]:
    rows = []
    for offset in range(start, min(max(len(original), len(tuned)), start + count), 16):
        a, b = original[offset:offset+16], tuned[offset:offset+16]
        rows.append({"offset": offset, "original": a.hex(" "), "tuned": b.hex(" "),
                     "changed": [i for i in range(max(len(a), len(b)))
                                 if a[i:i+1] != b[i:i+1]]})
    return rows
