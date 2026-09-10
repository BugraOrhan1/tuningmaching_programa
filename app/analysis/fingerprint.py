"""Cryptographic identity and offset-sensitive block fingerprints."""
import hashlib
import zlib
import numpy as np
from app.analysis.ecu_fingerprint import ecu_family_fingerprint


def hashes(data: bytes) -> dict:
    return {"sha256": hashlib.sha256(data).hexdigest(),
            "md5": hashlib.md5(data, usedforsecurity=False).hexdigest(),
            "crc32": f"{zlib.crc32(data):08x}"}


def fingerprint(data: bytes, block_size: int = 4096) -> dict:
    histogram = np.bincount(np.frombuffer(data, dtype=np.uint8), minlength=256)
    return {"version": 1, "block_size": block_size,
            "blocks": [hashlib.sha256(data[i:i + block_size]).hexdigest()
                       for i in range(0, len(data), block_size)],
            "histogram": (histogram / max(1, len(data))).tolist(),
            "ecu_family": ecu_family_fingerprint(data)}
