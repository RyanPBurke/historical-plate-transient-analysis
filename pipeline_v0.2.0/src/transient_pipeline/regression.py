from __future__ import annotations
import csv
from pathlib import Path


def compare_results(
    expected_csv: str | Path,
    result_csv: str | Path,
    sep_tol: float = 1e-5,
    sigma_tol: float = 1e-6,
    snr_tol: float = 1e-6,
):
    exp = {r["source_id"]: r for r in csv.DictReader(Path(expected_csv).open(encoding="utf-8"))}
    got = {r.get("source_id", r.get("job_key")): r for r in csv.DictReader(Path(result_csv).open(encoding="utf-8"))}
    report = []
    for sid, e in exp.items():
        g = got.get(sid)
        if not g:
            report.append((sid, False, "missing result"))
            continue
        if g.get("status") != "succeeded":
            report.append((sid, False, f"status={g.get('status')}"))
            continue
        checks = [
            abs(float(g["nearest_peak_sep_arcsec"]) - float(e["expected_sep_arcsec"])) <= sep_tol,
            int(float(g["peak_count"])) == int(e["expected_peak_count"]),
            abs(float(g["sigma"]) - float(e["expected_sigma"])) <= sigma_tol,
            abs(float(g["nearest_peak_snr"]) - float(e["expected_snr"])) <= snr_tol,
            int(float(g["nearest_peak_polarity"])) == int(e["expected_polarity"]),
        ]
        if e.get("expected_cutout_sha256"):
            checks.append(g.get("cutout_sha256", "").strip().lower() == e["expected_cutout_sha256"].strip().lower())
        report.append((sid, all(checks), "numeric + FITS hash regression ok" if all(checks) else "numeric/FITS hash regression mismatch"))
    return report
