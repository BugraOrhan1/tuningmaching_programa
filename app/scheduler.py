"""Disk-aware scheduling (§18): taken per schijf/root serieel, meerdere
schijven parallel tot aan het resourceprofiel. Voorkomt dat één HDD onder
20 gelijktijdige leesstromen gebukt gaat terwijl andere schijven stil staan.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor


class DiskScheduler:
    """Voer {key: [items]}-taken uit: binnen een key strikt serieel (één
    leeskop, geen seek-storm), over keys parallel met maximaal `workers`.
    """

    def __init__(self, workers: int = 1):
        self.workers = max(1, int(workers))

    def run(self, groups: dict, task, should_stop=None, checkpoint=None,
            progress=None) -> dict:
        """task(key, item) wordt per item aangeroepen; should_stop() stopt
        netjes tussen items; checkpoint(key, item) na elk voltooid item."""
        lock = threading.Lock()
        active: set = set()
        stats = {"max_concurrent": 0}

        def run_key(key):
            for item in groups[key]:
                if should_stop and should_stop():
                    return "stopped"
                with lock:
                    active.add(key)
                    stats["max_concurrent"] = max(stats["max_concurrent"],
                                                  len(active))
                try:
                    task(key, item)
                finally:
                    with lock:
                        active.discard(key)
                if checkpoint:
                    checkpoint(key, item)
                if progress:
                    progress(item)
            return "done"

        if self.workers == 1 or len(groups) <= 1:
            states = [run_key(key) for key in sorted(groups)]
        else:
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                futures = {key: pool.submit(run_key, key) for key in groups}
                states = [futures[key].result() for key in sorted(futures)]
        return {"states": states, **stats}
