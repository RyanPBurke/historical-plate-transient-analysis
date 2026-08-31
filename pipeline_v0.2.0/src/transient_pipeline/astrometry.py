from __future__ import annotations
import math


def propagate_gps1_to_epoch(ra_deg: float, dec_deg: float, pmra_masyr: float, pmde_masyr: float, target_epoch: float, source_epoch: float = 2010.0) -> tuple[float, float]:
    """Propagate GPS1 position using pmRA including cos(dec), matching the frozen audit formula."""
    dt = target_epoch - source_epoch
    cosd = math.cos(math.radians(dec_deg))
    if abs(cosd) < 1e-12:
        raise ValueError("RA proper-motion propagation undefined at pole")
    dec_hist = dec_deg + pmde_masyr * dt / 3.6e6
    ra_hist = ra_deg + (pmra_masyr * dt) / (3.6e6 * cosd)
    return ra_hist % 360.0, dec_hist


def angular_sep_arcsec(ra1_deg: float, dec1_deg: float, ra2_deg: float, dec2_deg: float) -> float:
    r1, d1, r2, d2 = map(math.radians, (ra1_deg, dec1_deg, ra2_deg, dec2_deg))
    dot = math.sin(d1)*math.sin(d2) + math.cos(d1)*math.cos(d2)*math.cos(r1-r2)
    return math.degrees(math.acos(max(-1.0, min(1.0, dot)))) * 3600.0
