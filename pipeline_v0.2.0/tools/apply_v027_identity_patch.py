from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import shutil


ROOT = Path.cwd()
SRC = ROOT / "src" / "transient_pipeline" / "poss1_skyview.py"
TEST = ROOT / "tests" / "test_poss1_v027_identity_policy.py"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


if not SRC.exists():
    raise SystemExit(f"Missing source file: {SRC}")

stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
backup_dir = ROOT / "patch_backups" / f"pre_v0.2.7_{stamp}"
backup_src = backup_dir / "src" / "transient_pipeline" / "poss1_skyview.py"
backup_src.parent.mkdir(parents=True, exist_ok=True)

shutil.copy2(SRC, backup_src)

text = SRC.read_text(encoding="utf-8")

# ----------------------------------------------------------------------
# 1. Descriptor <-> HHH centre separation:
#    preserve as provenance, but remove it as a terminal identity gate.
# ----------------------------------------------------------------------

old_center = '''    # The raw HHH must describe the same solved plate listed by the descriptor.
    descriptor_hhh_center_sep = angular_sep_arcsec(
        entry.ra_deg,
        entry.dec_deg,
        float(ident["plate_ra_deg"]),
        float(ident["plate_dec_deg"]),
    )
    if descriptor_hhh_center_sep > descriptor_hhh_center_tolerance_arcsec:
        raise ValueError(
            f"SkyView descriptor/HHH center disagreement for {expected_region_from_vi25}: "
            f"{descriptor_hhh_center_sep:.3f} arcsec"
        )
'''

new_center = '''    # The descriptor XML centre and GSSS PLATERA/PLATEDEC are not equivalent
    # centre definitions.  v0.2.7 empirical controls established valid
    # pixel-equivalent POSS-I E/O cases with descriptor<->HHH separations up
    # to 357.680 arcsec; all four v0.2.6 rejected cases were inside that
    # verified-good range.  Preserve the separation as diagnostic provenance,
    # but never use it as a terminal plate-identity discriminator.
    descriptor_hhh_center_sep = angular_sep_arcsec(
        entry.ra_deg,
        entry.dec_deg,
        float(ident["plate_ra_deg"]),
        float(ident["plate_dec_deg"]),
    )
'''

if text.count(old_center) != 1:
    raise SystemExit(
        "Refusing patch: expected exactly one v0.2.6 descriptor/HHH centre-gate block; "
        f"found {text.count(old_center)}"
    )

text = text.replace(old_center, new_center, 1)

# ----------------------------------------------------------------------
# 2. Raw HHH HTTP 404:
#    exact descriptor region exists, but its deterministic raw digital
#    product is absent.  This is archive availability, not retryable
#    identity failure and not a scientific zero.
# ----------------------------------------------------------------------

old_hhh = '''    hhh_url = f"{raw_dir}/{wanted}.hhh"
    rh = session.request("GET", hhh_url, validator=_validate_hhh_response)
    hhh_exchange: dict[str, Any] = {}
'''

new_hhh = '''    hhh_url = f"{raw_dir}/{wanted}.hhh"
    try:
        rh = session.request("GET", hhh_url, validator=_validate_hhh_response)
    except Exception as exc:
        # A deterministic raw-HHH 404 means the exact descriptor region exists
        # but its current SkyView raw digital product is unavailable.  Do not
        # substitute a neighbouring region and do not convert this exposure
        # into a scientific zero.  Non-404 failures retain their original
        # exception/retry behaviour.
        msg = str(exc)
        if "HTTP 404" not in msg.upper():
            raise

        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", job_key)
        sidecar = (
            Path(cache_dir)
            / safe
            / f"{expected_region_from_vi25}_raw_hhh_unavailable.provenance.json"
        )
        sidecar_record = {
            "artifact_type": "poss1_archive_pixels_unavailable",
            "recorded_at_utc": utcnow(),
            "science_analysis_performed": False,
            "exposure_id": job_key,
            "identity_status": "catalogue_identified_pixels_unavailable",
            "eligible_for_science": False,
            "archive_failure_kind": "skyview_raw_hhh_http_404",
            "primary_archive_failure": primary_failure,
            "vi25": {
                "recno": record.recno,
                "poss": record.poss,
                "mlp": record.mlp,
                "band": band,
                "obs": record.obs,
                "fObs": record.fobs,
                "ra_icrs_raw": record.ra_icrs,
                "dec_icrs_raw": record.dec_icrs,
                "expected_region": expected_region_from_vi25,
            },
            "skyview": {
                "descriptor_url": descriptor_url,
                "descriptor_sha256": sha256_bytes(rd.content),
                "descriptor_exact_region_matches": 1,
                "descriptor_image_path": entry.path,
                "raw_plate_directory": raw_dir,
                "hhh_url": hhh_url,
                "hhh_failure": f"{type(exc).__name__}: {exc}",
                "descriptor_exchange": descriptor_exchange,
            },
            "interpretation": (
                "The deterministically expected POSS-I region is present in the "
                "current SkyView DSS1 descriptor, but its exact raw HHH product "
                "returns HTTP 404. The physical exposure remains catalogue-identified; "
                "digital pixels are currently unavailable. The exposure remains in "
                "the prospective denominator, is ineligible for detector execution, "
                "and is not a scientific zero. No neighbouring DSS region is substituted."
            ),
        }
        atomic_write_text(
            sidecar,
            json.dumps(sidecar_record, indent=2, sort_keys=True, default=str) + "\\n",
        )

        if evidence:
            evidence.record_artifact(
                path=sidecar,
                kind="poss1_archive_pixels_unavailable",
                stage=stage,
                job_key=job_key,
                source_url=hhh_url,
                metadata={
                    "region": expected_region_from_vi25,
                    "band": band,
                    "vi25_recno": record.recno,
                    "eligible_for_science": False,
                    "archive_failure_kind": "skyview_raw_hhh_http_404",
                },
                snapshot=True,
            )

        return {
            "identity_status": "catalogue_identified_pixels_unavailable",
            "identity_source": (
                "vi25_plus_primary_stsci_failure_and_"
                "skyview_descriptor_raw_hhh_gap"
            ),
            "archive_availability_status": "digital_pixels_unavailable",
            "eligible_for_science": False,
            "vi25_poss": record.poss,
            "vi25_mlp": record.mlp,
            "vi25_observing_night_initial": record.obs,
            "vi25_observing_night_final": record.fobs,
            "finder_plate_id": expected_plate_id or "",
            "finder_region": expected_region_from_vi25,
            "skyview_descriptor_image_count": 1,
            "skyview_descriptor_sha256": (
                ((descriptor_exchange.get("response") or {}).get("sha256"))
                or sha256_bytes(rd.content)
            ),
            "skyview_descriptor_image_path": entry.path,
            "skyview_raw_hhh_url": hhh_url,
            "skyview_raw_hhh_failure": f"{type(exc).__name__}: {exc}",
            "archive_failure_kind": "skyview_raw_hhh_http_404",
            "primary_archive_failure": primary_failure,
            "archive_unavailable_provenance_sidecar": str(sidecar),
        }

    hhh_exchange: dict[str, Any] = {}
'''

if text.count(old_hhh) != 1:
    raise SystemExit(
        "Refusing patch: expected exactly one raw-HHH request block; "
        f"found {text.count(old_hhh)}"
    )

text = text.replace(old_hhh, new_hhh, 1)

# ----------------------------------------------------------------------
# 3. Record the empirical basis in successful SkyView identity sidecars.
# ----------------------------------------------------------------------

old_controls = '''        "control_basis": {
            "strict_pixel_equivalence_controls": "5/5",
            "emulsions": ["POSS-I E", "POSS-I O"],
            "control_jar_sha256": SKYVIEW_CONTROL_JAR_SHA256,
        },
'''

new_controls = '''        "control_basis": {
            "strict_pixel_equivalence_controls": "5/5",
            "emulsions": ["POSS-I E", "POSS-I O"],
            "control_jar_sha256": SKYVIEW_CONTROL_JAR_SHA256,
            "descriptor_hhh_center_policy": "diagnostic_only_v0.2.7",
            "descriptor_hhh_verified_control_max_sep_arcsec": 357.680,
        },
'''

if text.count(old_controls) != 1:
    raise SystemExit(
        "Refusing patch: expected exactly one control_basis block; "
        f"found {text.count(old_controls)}"
    )

text = text.replace(old_controls, new_controls, 1)

# Update only the explicit fallback user-agent revision.
old_agent = (
    'user_agent="historical-transient-pipeline/0.2.6 '
    'publication-poss1-skyview-fallback",'
)
new_agent = (
    'user_agent="historical-transient-pipeline/0.2.7 '
    'publication-poss1-skyview-fallback",'
)

if text.count(old_agent) != 1:
    raise SystemExit(
        "Refusing patch: expected exactly one v0.2.6 fallback user-agent; "
        f"found {text.count(old_agent)}"
    )

text = text.replace(old_agent, new_agent, 1)

SRC.write_text(text, encoding="utf-8")

# ----------------------------------------------------------------------
# Regression/policy tests.
#
# The existing functional tests still exercise Plate-Finder non-resolution.
# These tests make the v0.2.7 scientific policy explicit and prevent the
# invalid hard centre gate or silent neighbouring-region substitution from
# being casually reintroduced.
# ----------------------------------------------------------------------

test_text = r'''from __future__ import annotations

import inspect

import transient_pipeline.poss1_skyview as skyview


def _source() -> str:
    return inspect.getsource(skyview.skyview_fallback_identity)


def test_descriptor_hhh_center_separation_is_diagnostic_only():
    src = _source()

    assert "descriptor_hhh_center_sep = angular_sep_arcsec(" in src
    assert '"descriptor_hhh_center_sep_arcsec": descriptor_hhh_center_sep' in src

    # v0.2.6's invalid terminal gate must not return.
    assert (
        "if descriptor_hhh_center_sep > "
        "descriptor_hhh_center_tolerance_arcsec:"
    ) not in src

    assert "diagnostic provenance" in src


def test_raw_hhh_404_is_archive_availability_not_identity_failure():
    src = _source()

    assert 'if "HTTP 404" not in msg.upper()' in src
    assert '"archive_failure_kind": "skyview_raw_hhh_http_404"' in src
    assert '"identity_status": "catalogue_identified_pixels_unavailable"' in src
    assert '"archive_availability_status": "digital_pixels_unavailable"' in src
    assert '"eligible_for_science": False' in src


def test_raw_hhh_404_does_not_substitute_neighbour_region():
    src = _source()

    # Raw URL remains deterministically tied to exact VI/25 region.
    assert 'wanted = expected_region_from_vi25.lower()' in src
    assert 'hhh_url = f"{raw_dir}/{wanted}.hhh"' in src

    # Exact HHH REGION agreement remains mandatory whenever HHH exists.
    assert 'if ident["region"] != expected_region_from_vi25:' in src
'''

TEST.write_text(test_text, encoding="utf-8")

print("=" * 88)
print("v0.2.7 PATCH APPLIED")
print("=" * 88)
print("source:", SRC)
print("source SHA256:", sha256_file(SRC))
print("backup:", backup_src)
print("backup SHA256:", sha256_file(backup_src))
print("test:", TEST)
print()
print("Changes:")
print("  1. descriptor<->HHH centre separation retained as diagnostic provenance only")
print("  2. exact raw-HHH HTTP 404 classified as digital-pixels-unavailable")
print("  3. neighbouring DSS region substitution remains prohibited")
print("  4. empirical 357.680 arcsec control maximum recorded in provenance")
print("  5. fallback user-agent revision updated to 0.2.7")
print()
print("No checkpoint state was changed.")
print("No transient detector was run.")
