"""Read-only WinOLS project import facade.

The OLS format is treated as opaque until a documented structure is available.
This facade keeps import modes explicit and prevents callers from confusing a
project container with an ECU binary.
"""
from __future__ import annotations

from pathlib import Path

from app.winols.ols_reader import inspect_ols, read_ols


class OlsImporter:
    """Inspect supported observable OLS content without modifying its source."""

    def inspect_project(self, path: str | Path, max_file_mb: int = 64) -> dict:
        return inspect_ols(read_ols(path, max_file_mb))

    def extract_metadata(self, path: str | Path, max_file_mb: int = 64) -> dict:
        details = self.inspect_project(path, max_file_mb)
        return {
            "raw": details.get("tagged_metadata", {}),
            "suggested_type": details.get("suggested_type", "unknown"),
            "suggestion_reason": details.get("suggestion_reason"),
            "status": "available" if details.get("tagged_metadata") else "not_available",
        }

    def extract_files(self, path: str | Path, max_file_mb: int = 64) -> dict:
        """Report binary extraction as unsupported unless a format reader exists."""
        details = self.inspect_project(path, max_file_mb)
        return {"status": "unsupported", "objects": details.get("objects", []),
                "reason": "Opaque OLS-structuur; geen betrouwbare binary-object reader beschikbaar."}

    def extract_project_structure(self, path: str | Path, max_file_mb: int = 64) -> dict:
        details = self.inspect_project(path, max_file_mb)
        forensic = details.get("forensic", {})
        records = details.get("records", [])
        return {"status": "partial", "objects": details.get("objects", []),
            "records": records,
            "versions": [record for record in records if record["record_type"] == "version_or_role_label"],
            "maps": [record for record in records if record["record_type"] == "map_label"],
            "binary_evidence": forensic.get("binary_evidence", []),
            "relationships": "target_unknown",
            "unsupported": ["opaque_binary_objects", "winols_map_definitions", "version_tree", "record_pointers"]}

    def extract_available_calibration_information(self, path: str | Path, max_file_mb: int = 64) -> dict:
        return {"status": "not_available", "maps": [],
                "reason": "Mapinformatie wordt niet gegokt uit opaque projectbytes."}