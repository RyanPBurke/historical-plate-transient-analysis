from __future__ import annotations

import inspect

import transient_pipeline.poss1_skyview as skyview


def _source() -> str:
    """Find the callable containing the raw SkyView HHH fallback logic."""
    candidates = []

    for name, obj in vars(skyview).items():
        if not inspect.isfunction(obj):
            continue

        try:
            src = inspect.getsource(obj)
        except (OSError, TypeError):
            continue

        if 'hhh_url = f"{raw_dir}/{wanted}.hhh"' in src:
            candidates.append((name, src))

    assert len(candidates) == 1, (
        "Expected exactly one SkyView raw-HHH implementation; "
        f"found {[name for name, _ in candidates]}"
    )

    return candidates[0][1]


def test_descriptor_hhh_center_separation_is_diagnostic_only():
    src = _source()

    # Measurement must still exist and be recorded.
    assert "descriptor_hhh_center_sep = angular_sep_arcsec(" in src
    assert (
        '"descriptor_hhh_center_sep_arcsec": '
        "descriptor_hhh_center_sep"
    ) in src

    # v0.2.6's empirically-invalid terminal gate must not return.
    assert (
        "if descriptor_hhh_center_sep > "
        "descriptor_hhh_center_tolerance_arcsec:"
    ) not in src

    assert "diagnostic provenance" in src


def test_raw_hhh_404_is_archive_availability_not_identity_failure():
    src = _source()

    assert 'if "HTTP 404" not in msg.upper()' in src
    assert '"archive_failure_kind": "skyview_raw_hhh_http_404"' in src
    assert (
        '"identity_status": '
        '"catalogue_identified_pixels_unavailable"'
    ) in src
    assert (
        '"archive_availability_status": '
        '"digital_pixels_unavailable"'
    ) in src
    assert '"eligible_for_science": False' in src


def test_non_404_hhh_errors_are_still_raised():
    src = _source()

    # The new archive-availability handling must be limited to 404.
    assert 'if "HTTP 404" not in msg.upper()' in src
    assert 'if "HTTP 404" not in msg.upper():\n            raise' in src


def test_raw_hhh_path_is_exact_expected_region():
    src = _source()

    # No +/-1 or neighbouring-region substitution.
    assert 'wanted = expected_region_from_vi25.lower()' in src
    assert 'hhh_url = f"{raw_dir}/{wanted}.hhh"' in src

    # If an HHH exists, its embedded REGION must still agree exactly.
    assert 'if ident["region"] != expected_region_from_vi25:' in src


def test_raw_hhh_404_explicitly_forbids_neighbour_substitution():
    src = _source()

    assert "No neighbouring DSS region is substituted." in src
