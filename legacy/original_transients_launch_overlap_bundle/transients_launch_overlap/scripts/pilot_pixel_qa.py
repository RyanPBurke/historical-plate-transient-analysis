#!/usr/bin/env python3
"""Frozen, symmetric source-matching QA for retrieved 20-arcmin pilot tiles."""

from pathlib import Path

import numpy as np
import pandas as pd
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
import astropy.units as u
from scipy.ndimage import gaussian_filter, maximum_filter


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

# Fixed before looking at candidate lists. These are screening, not discovery,
# thresholds: local background scale 8 px, 4-sigma peaks, 7-px maximum window,
# 30-px edge exclusion, and 10-arcsec crossmatch radius.
BG_SIGMA_PX = 8.0
PEAK_SIGMA = 4.0
MAX_WINDOW_PX = 7
EDGE_PX = 30
MATCH_ARCSEC = 10.0


def detect(path: Path) -> pd.DataFrame:
    with fits.open(path) as hdul:
        image = np.asarray(hdul[0].data, dtype=float)
        wcs = WCS(hdul[0].header).celestial
    finite = np.isfinite(image)
    fill = np.nanmedian(image)
    work = np.where(finite, image, fill)
    residual = work - gaussian_filter(work, BG_SIGMA_PX)
    med = np.median(residual[finite])
    mad = np.median(np.abs(residual[finite] - med))
    sigma = 1.4826 * mad
    # Emulsions/scans can encode stellar images with either polarity, so apply
    # the same absolute-residual rule to both archives.
    signal = np.abs(residual - med)
    peaks = (signal == maximum_filter(signal, MAX_WINDOW_PX)) & (signal > PEAK_SIGMA * sigma)
    peaks[:EDGE_PX, :] = peaks[-EDGE_PX:, :] = False
    peaks[:, :EDGE_PX] = peaks[:, -EDGE_PX:] = False
    y, x = np.nonzero(peaks & finite)
    sky = wcs.pixel_to_world(x, y)
    return pd.DataFrame({"x": x, "y": y, "ra_deg": sky.ra.deg,
                         "dec_deg": sky.dec.deg, "peak_snr": signal[y, x] / sigma,
                         "polarity": np.sign(residual[y, x] - med).astype(int)})


def main():
    manifest = pd.read_csv(RESULTS / "priority_cutout_manifest.csv")
    summaries, candidates = [], []
    for _, row in manifest[manifest.retrieval_status == "retrieved"].iterrows():
        d = detect(ROOT / row.dasch_file)
        p = detect(ROOT / row.poss_file)
        dc = SkyCoord(d.ra_deg.to_numpy() * u.deg, d.dec_deg.to_numpy() * u.deg)
        pc = SkyCoord(p.ra_deg.to_numpy() * u.deg, p.dec_deg.to_numpy() * u.deg)
        di, dsep, _ = dc.match_to_catalog_sky(pc)
        pi, psep, _ = pc.match_to_catalog_sky(dc)
        dm = dsep.arcsec <= MATCH_ARCSEC
        pm = psep.arcsec <= MATCH_ARCSEC
        summaries.append({
            "priority_rank": int(row.priority_rank), "dasch_plate_id": row.dasch_plate_id,
            "poss_exposure_id": row.poss_exposure_id, "dasch_detections": len(d),
            "poss_detections": len(p), "dasch_matched": int(dm.sum()),
            "poss_matched": int(pm.sum()), "dasch_unmatched": int((~dm).sum()),
            "poss_unmatched": int((~pm).sum()), "match_radius_arcsec": MATCH_ARCSEC,
        })
        for label, frame, matched, sep in [("DASCH", d, dm, dsep.arcsec), ("POSS", p, pm, psep.arcsec)]:
            for idx in np.where(~matched)[0]:
                candidates.append({
                    "priority_rank": int(row.priority_rank), "dasch_plate_id": row.dasch_plate_id,
                    "poss_exposure_id": row.poss_exposure_id, "detected_in": label,
                    "ra_deg": frame.iloc[idx].ra_deg, "dec_deg": frame.iloc[idx].dec_deg,
                    "peak_snr": frame.iloc[idx].peak_snr, "polarity": int(frame.iloc[idx].polarity),
                    "nearest_other_arcsec": float(sep[idx]),
                    "status": "unvetted_single-image_peak",
                })
    pd.DataFrame(summaries).to_csv(RESULTS / "pilot_pixel_summary.csv", index=False)
    cand = pd.DataFrame(candidates).sort_values(["priority_rank", "detected_in", "peak_snr"], ascending=[True, True, False])
    cand.to_csv(RESULTS / "pilot_unmatched_peaks.csv", index=False)
    print(pd.DataFrame(summaries).to_string(index=False))
    print(f"unmatched screening peaks: {len(cand)}")


if __name__ == "__main__":
    main()
