"""Portable configuration with an optional environment override."""
import json
import os
from pathlib import Path


def load_config() -> dict:
    path = Path(os.environ.get("TUNING_CONFIG", "config.json")).resolve()
    defaults = dict(data_dir="data", max_file_mb=64, top_matches=10, candidate_pool=250,
                    block_size=4096, diff_merge_gap=8)
    if path.exists():
        defaults.update(json.loads(path.read_text(encoding="utf-8")))
    defaults["data_dir"] = str((path.parent / defaults["data_dir"]).resolve())
    for key in ("max_file_mb", "top_matches", "candidate_pool", "block_size"):
        if not isinstance(defaults[key], int) or defaults[key] <= 0:
            raise ValueError(f"{key} must be a positive integer")
    if not isinstance(defaults["diff_merge_gap"], int) or defaults["diff_merge_gap"] < 0:
        raise ValueError("diff_merge_gap must be a nonnegative integer")
    return defaults
