"""Read-only calibration region alignment across software revisions."""
from __future__ import annotations

from difflib import SequenceMatcher
import hashlib


def align_regions(source: bytes, target: bytes, block_size: int = 64,
                  min_blocks: int = 2) -> list[dict]:
    """Align equal structural block runs. Results are analysis, never mutations."""
    if block_size <= 0 or min_blocks <= 0:
        raise ValueError("block_size and min_blocks must be positive")
    def blocks(data: bytes) -> list[str]:
        return [hashlib.sha256(data[i:i + block_size]).hexdigest() for i in range(0, len(data), block_size)]
    source_blocks, target_blocks = blocks(source), blocks(target)
    matcher = SequenceMatcher(a=source_blocks, b=target_blocks, autojunk=False)
    results = []
    for source_index, target_index, length in matcher.get_matching_blocks():
        if length < min_blocks:
            continue
        source_start, target_start = source_index * block_size, target_index * block_size
        byte_length = min(length * block_size, len(source) - source_start, len(target) - target_start)
        results.append({"source_start": source_start, "source_end": source_start + byte_length,
                        "target_start": target_start, "target_end": target_start + byte_length,
                        "length": byte_length, "confidence": round(100 * byte_length / max(block_size, min(len(source), len(target))), 4),
                        "method": "exact_structural_block_run"})
    return results
