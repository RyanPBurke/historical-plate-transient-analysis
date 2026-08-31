from __future__ import annotations

from dataclasses import asdict, dataclass
import io
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter, maximum_filter

from .config import FrozenMethod


@dataclass(frozen=True)
class DetectionSummary:
    sigma: float
    median_residual: float
    peak_count: int
    nearest_peak_sep_arcsec: float
    nearest_peak_snr: float
    nearest_peak_polarity: int
    nearest_peak_x: int
    nearest_peak_y: int

    def to_dict(self):
        return asdict(self)


def _imports():
    try:
        from astropy.coordinates import SkyCoord
        from astropy.io import fits
        from astropy.wcs import WCS
        import astropy.units as u
    except ImportError as exc:
        raise RuntimeError("astropy is required for FITS/WCS detector work; run pip install -r requirements.txt") from exc
    return fits, WCS, SkyCoord, u


def detect_array(image: np.ndarray, method: FrozenMethod):
    finite = np.isfinite(image)
    if not finite.any():
        raise ValueError("image contains no finite pixels")
    fill = float(np.nanmedian(image))
    work = np.where(finite, image, fill).astype(float, copy=False)
    residual = work - gaussian_filter(work, method.background_sigma_px)
    med = float(np.median(residual[finite]))
    mad = float(np.median(np.abs(residual[finite] - med)))
    sigma = 1.4826 * mad
    if not np.isfinite(sigma) or sigma <= 0:
        raise ValueError(f"invalid robust sigma {sigma}")
    signal = np.abs(residual - med)
    peaks = (signal == maximum_filter(signal, method.max_window_px)) & (signal > method.peak_sigma * sigma)
    e = method.edge_px
    peaks[:e, :] = False; peaks[-e:, :] = False; peaks[:, :e] = False; peaks[:, -e:] = False
    y, x = np.nonzero(peaks & finite)
    return {"x": x, "y": y, "signal": signal[y, x], "snr": signal[y, x] / sigma,
            "polarity": np.sign(residual[y, x] - med).astype(int), "sigma": sigma, "median_residual": med}


def analyze_fits_bytes(fits_bytes: bytes, target_ra_deg: float, target_dec_deg: float, method: FrozenMethod) -> DetectionSummary:
    fits, WCS, SkyCoord, u = _imports()
    with fits.open(io.BytesIO(fits_bytes), memmap=False) as hdul:
        image = np.asarray(hdul[0].data, dtype=float)
        if image.ndim != 2:
            raise ValueError(f"expected 2-D FITS image, got shape {image.shape}")
        wcs = WCS(hdul[0].header).celestial
        if not wcs.has_celestial:
            raise ValueError("FITS cutout has no celestial WCS")
    d = detect_array(image, method)
    if len(d["x"]) == 0:
        raise ValueError("frozen detector found zero peaks in cutout")
    sky = wcs.pixel_to_world(d["x"], d["y"])
    target = SkyCoord(target_ra_deg * u.deg, target_dec_deg * u.deg)
    sep = target.separation(sky).arcsec
    idx = int(np.argmin(sep))
    return DetectionSummary(
        sigma=float(d["sigma"]), median_residual=float(d["median_residual"]), peak_count=int(len(sep)),
        nearest_peak_sep_arcsec=float(sep[idx]), nearest_peak_snr=float(d["snr"][idx]),
        nearest_peak_polarity=int(d["polarity"][idx]), nearest_peak_x=int(d["x"][idx]), nearest_peak_y=int(d["y"][idx]),
    )


def analyze_fits_path(path: str | Path, target_ra_deg: float, target_dec_deg: float, method: FrozenMethod):
    return analyze_fits_bytes(Path(path).read_bytes(), target_ra_deg, target_dec_deg, method)
