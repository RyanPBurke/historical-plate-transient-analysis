from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime


def parse_iso(s: str) -> datetime:
    # Accept Z as UTC while preserving offset-aware datetimes when supplied.
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@dataclass(frozen=True)
class ExposureRelation:
    a_start: str
    a_end: str
    b_start: str
    b_end: str
    midpoint_separation_seconds: float
    overlap_seconds: float
    overlaps: bool

    def to_dict(self):
        return asdict(self)


def exposure_relation(a_start: str, a_end: str, b_start: str, b_end: str) -> ExposureRelation:
    a0, a1, b0, b1 = map(parse_iso, (a_start, a_end, b_start, b_end))
    if a1 <= a0 or b1 <= b0:
        raise ValueError("exposure end must be after start")
    amid = a0 + (a1 - a0) / 2
    bmid = b0 + (b1 - b0) / 2
    lo = max(a0, b0); hi = min(a1, b1)
    overlap = max(0.0, (hi - lo).total_seconds())
    return ExposureRelation(
        a_start=a_start, a_end=a_end, b_start=b_start, b_end=b_end,
        midpoint_separation_seconds=abs((amid - bmid).total_seconds()),
        overlap_seconds=overlap, overlaps=overlap > 0,
    )
