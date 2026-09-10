"""V3 extension points. Implementations must remain analysis-only until validated."""
from __future__ import annotations
from abc import ABC, abstractmethod


class MapDetector(ABC):
    @abstractmethod
    def detect(self, data: bytes) -> list[dict]: ...


class CalibrationMapClassifier(ABC):
    @abstractmethod
    def classify(self, region: bytes) -> dict: ...


class AxisDetector(ABC):
    @abstractmethod
    def detect_axes(self, data: bytes) -> list[dict]: ...


class MapSimilarityEngine(ABC):
    @abstractmethod
    def compare_maps(self, left: dict, right: dict) -> dict: ...


class TuningStrategyEngine(ABC):
    @abstractmethod
    def propose(self, context: dict) -> dict: ...
