import csv
from pathlib import Path

from transient_pipeline.regression import compare_results


def test_regression_checks_hash(tmp_path):
    expected = tmp_path / "expected.csv"
    result = tmp_path / "result.csv"
    expected.write_text(
        "source_id,expected_sep_arcsec,expected_peak_count,expected_sigma,expected_snr,expected_polarity,expected_cutout_sha256\n"
        "x,1.0,2,3.0,4.0,1,abc\n",
        encoding="utf-8",
    )
    result.write_text(
        "source_id,status,nearest_peak_sep_arcsec,peak_count,sigma,nearest_peak_snr,nearest_peak_polarity,cutout_sha256\n"
        "x,succeeded,1.0,2,3.0,4.0,1,abc\n",
        encoding="utf-8",
    )
    assert compare_results(expected, result)[0][1] is True
    result.write_text(
        "source_id,status,nearest_peak_sep_arcsec,peak_count,sigma,nearest_peak_snr,nearest_peak_polarity,cutout_sha256\n"
        "x,succeeded,1.0,2,3.0,4.0,1,bad\n",
        encoding="utf-8",
    )
    assert compare_results(expected, result)[0][1] is False
