from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class FrozenMethod:
    background_sigma_px: float = 8.0
    peak_sigma: float = 4.0
    max_window_px: int = 7
    edge_px: int = 30
    diagnostic_match_arcsec: float = 10.0
    strict_registered_match_arcsec: float = 3.0
    hamburg_recurrence_arcsec: float = 3.2
    gps1_static_veto_arcsec: float = 10.0
    gps1_query_radius_arcsec: float = 120.0
    gps1_epoch: float = 1952.6198

    @classmethod
    def from_json(cls, path: str | Path) -> "FrozenMethod":
        return cls(**json.loads(Path(path).read_text(encoding="utf-8")))
