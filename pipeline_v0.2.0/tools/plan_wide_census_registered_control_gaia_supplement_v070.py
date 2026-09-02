from pathlib import Path
import csv
import hashlib
import importlib.util
import json

ROOT = Path(__file__).resolve().parents[1]

RESULTS = ROOT / "results"
RESEARCH = ROOT / "research"
TOOLS = ROOT / "tools"

V069 = (
    RESULTS
    / "wide_census_registered_control_coverage_preflight_v069"
)

V069_REPORT = (
    V069
    / "wide_census_registered_control_coverage_preflight_v069.json"
)

MISSING = (
    V069
    / "wide_census_registered_control_missing_cells_v069.csv"
)

HPM_REQ = (
    V069
    / "wide_census_registered_control_hpm_requirements_v069.csv"
)

V065_HPM = (
    RESULTS
    / "wide_census_gaia_reference_coverage_audit_v065"
    / "wide_census_gaia_corrected_hpm_pair_queries_v065.csv"
)

V065_SCRIPT = (
    TOOLS
    / "audit_wide_census_gaia_reference_coverage_v065.py"
)

V069_SCRIPT = (
    TOOLS
    / "preflight_wide_census_registered_controls_v069.py"
)

CONTROL_CONTRACT = (
    RESEARCH
    / "prospective_freezes"
    / "wide_census_registered_control_contract_v001.json"
)

SUPPLEMENT_CONTRACT = (
    RESEARCH
    / "prospective_freezes"
    / "wide_census_registered_control_gaia_supplement_contract_v001.json"
)

OUT = (
    RESULTS
    / "wide_census_registered_control_gaia_supplement_plan_v070"
)

ORD_OUT = (
    OUT
    / "wide_census_registered_control_ordinary_query_plan_v070.csv"
)

HPM_OUT = (
    OUT
    / "wide_census_registered_control_hpm_query_plan_v070.csv"
)

REPORT_OUT = (
    OUT
    / "wide_census_registered_control_gaia_supplement_plan_v070.json"
)

EXPECTED = {
    V065_SCRIPT:
        "213416fcb26406a1c14986ebf4d7de7482a5853e3dc7ecce0f5d46c8bf3bc6b2",

    V069_SCRIPT:
        "0471c95ae5fd44b7d0c951de18aa2af493a276257747fe0e0850bc9c6288dbe9",

    CONTROL_CONTRACT:
        "be2febd2696f1798a0a78c2724420f3aaac939a825ebe5b296b126ba9ce47eeb",
}

EXPECTED_ORDINARY = 3009
EXPECTED_HPM_GAPS = 16

MARGIN_ARCSEC = 125.4
HPM_MARGIN_ARCSEC = 915.0
HPM_MIN_MASYR = 1700.0


def sha256(path):
    h = hashlib.sha256()

    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)

    return h.hexdigest()


def read_csv(path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_suffix(path.suffix + ".tmp")

    with tmp.open(
        "w",
        encoding="utf-8",
        newline=""
    ) as f:
        w = csv.DictWriter(
            f,
            fieldnames=fields,
            extrasaction="ignore",
        )
        w.writeheader()
        w.writerows(rows)

    tmp.replace(path)


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_suffix(path.suffix + ".tmp")

    with tmp.open("w", encoding="utf-8") as f:
        json.dump(
            obj,
            f,
            indent=2,
            sort_keys=True,
        )

    tmp.replace(path)


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(
        name,
        path,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"Cannot import {path}"
        )

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    return mod


def main():
    print("=" * 118)
    print(
        "WIDE CENSUS REGISTERED-CONTROL "
        "GAIA SUPPLEMENT PLAN v070"
    )
    print("=" * 118)
    print("Network access: NO")
    print("Gaia source rows read: NO")
    print("Registrations: NO")
    print("Detector rerun: NO")
    print("Candidate dispositions: NONE")
    print()

    for path in (
        V069_REPORT,
        MISSING,
        HPM_REQ,
        V065_HPM,
        SUPPLEMENT_CONTRACT,
    ):
        if not path.is_file():
            raise RuntimeError(
                f"Missing prerequisite: {path}"
            )

    for path, expected in EXPECTED.items():
        if not path.is_file():
            raise RuntimeError(
                f"Missing frozen prerequisite: {path}"
            )

        actual = sha256(path)

        if actual.lower() != expected.lower():
            raise RuntimeError(
                "Frozen SHA mismatch:\n"
                f"  {path}\n"
                f"  expected {expected}\n"
                f"  actual   {actual}"
            )

        print(
            "HASH PASS:",
            path.relative_to(ROOT),
        )

    v069 = json.loads(
        V069_REPORT.read_text(
            encoding="utf-8-sig"
        )
    )

    if v069.get("status") != "COMPLETE":
        raise RuntimeError(
            "v069 is not COMPLETE"
        )

    cd = v069["control_domain"]

    if bool(
        cd.get(
            "existing_cache_fully_sufficient"
        )
    ):
        raise RuntimeError(
            "v069 says cache is already sufficient; "
            "supplemental acquisition is not permitted"
        )

    missing_rows = read_csv(MISSING)

    if len(missing_rows) != EXPECTED_ORDINARY:
        raise RuntimeError(
            f"Expected {EXPECTED_ORDINARY} "
            f"missing cells; found {len(missing_rows)}"
        )

    hpm_req = read_csv(HPM_REQ)

    hpm_gaps = [
        r for r in hpm_req
        if str(
            r[
                "existing_query_covers_control_domain"
            ]
        ).strip().lower()
        not in ("true", "1", "yes")
    ]

    if len(hpm_gaps) != EXPECTED_HPM_GAPS:
        raise RuntimeError(
            f"Expected {EXPECTED_HPM_GAPS} HPM gaps; "
            f"found {len(hpm_gaps)}"
        )

    v65 = load_module(
        V065_SCRIPT,
        "frozen_v065",
    )

    if abs(
        float(v65.BASE_CELL_DEG) - 0.25
    ) > 1e-12:
        raise RuntimeError(
            "v065 BASE_CELL_DEG changed"
        )

    if int(v65.MAXREC) != 50000:
        raise RuntimeError(
            "v065 MAXREC changed"
        )

    if abs(
        float(v65.MIN_CELL_DEG) - 0.03125
    ) > 1e-12:
        raise RuntimeError(
            "v065 MIN_CELL_DEG changed"
        )

    ordinary = []

    for qidx, r in enumerate(
        sorted(
            missing_rows,
            key=lambda x: (
                int(x["cell_ira"]),
                int(x["cell_idec"]),
            ),
        ),
        1,
    ):
        ira = int(r["cell_ira"])
        idec = int(r["cell_idec"])

        bounds = v65.bounds_for_base(
            ira,
            idec,
        )

        ra, dec, radius = v65.query_geom(
            bounds,
            MARGIN_ARCSEC,
        )

        ordinary.append({
            "supplemental_query_index":
                qidx,

            "mode":
                "FULL_NEW_BASE_CELL_CONTROL",

            "base_cell_ira":
                ira,

            "base_cell_idec":
                idec,

            "query_ra_deg":
                ra,

            "query_dec_deg":
                dec,

            "query_radius_deg":
                radius,

            "corrected_margin_arcsec":
                MARGIN_ARCSEC,

            "maxrec":
                int(v65.MAXREC),

            "if_maxrec_hit":
                (
                    "RECURSIVELY_QUARTER_TO_"
                    f"{float(v65.MIN_CELL_DEG)}"
                    "_DEG_TRANSPORT_ONLY"
                ),

            "consumer_pair_count":
                int(
                    r["consumer_pair_count"]
                ),

            "consumer_pair_indices":
                r[
                    "consumer_pair_indices"
                ],
        })

    old_hpm = {
        int(r["pair_index"]): r
        for r in read_csv(V065_HPM)
    }

    hpm = []

    for qidx, r in enumerate(
        sorted(
            hpm_gaps,
            key=lambda x:
                int(x["pair_index"]),
        ),
        1,
    ):
        idx = int(r["pair_index"])

        if idx not in old_hpm:
            raise RuntimeError(
                f"Pair {idx} absent from v065 HPM plan"
            )

        prior = old_hpm[idx]

        hpm.append({
            "supplemental_hpm_query_index":
                qidx,

            "pair_index":
                idx,

            "canonical_pair":
                r["canonical_pair"],

            "query_ra_deg":
                float(
                    r[
                        "required_control_query_ra_deg"
                    ]
                ),

            "query_dec_deg":
                float(
                    r[
                        "required_control_query_dec_deg"
                    ]
                ),

            "query_radius_deg":
                float(
                    r[
                        "required_control_query_radius_deg"
                    ]
                ),

            "pm_min_masyr":
                HPM_MIN_MASYR,

            "j2016_hpm_transport_margin_arcsec":
                HPM_MARGIN_ARCSEC,

            "registration_epoch_utc":
                prior[
                    "registration_epoch_utc"
                ],

            "mode":
                "FULL_CONTROL_DOMAIN_HPM_CONE",

            "downstream_action":
                "DEDUPLICATE_SOURCE_ID",
        })

    if len(ordinary) != 3009:
        raise RuntimeError(
            "Ordinary plan length invariant failed"
        )

    if len(hpm) != 16:
        raise RuntimeError(
            "HPM plan length invariant failed"
        )

    write_csv(
        ORD_OUT,
        ordinary,
        [
            "supplemental_query_index",
            "mode",
            "base_cell_ira",
            "base_cell_idec",
            "query_ra_deg",
            "query_dec_deg",
            "query_radius_deg",
            "corrected_margin_arcsec",
            "maxrec",
            "if_maxrec_hit",
            "consumer_pair_count",
            "consumer_pair_indices",
        ],
    )

    write_csv(
        HPM_OUT,
        hpm,
        [
            "supplemental_hpm_query_index",
            "pair_index",
            "canonical_pair",
            "query_ra_deg",
            "query_dec_deg",
            "query_radius_deg",
            "pm_min_masyr",
            "j2016_hpm_transport_margin_arcsec",
            "registration_epoch_utc",
            "mode",
            "downstream_action",
        ],
    )

    report = {
        "status":
            "COMPLETE",

        "analysis_kind":
            "wide_census_registered_control_gaia_supplement_plan_v070",

        "input_sha256": {
            "v069_report":
                sha256(V069_REPORT),

            "v069_missing_cells":
                sha256(MISSING),

            "v069_hpm_requirements":
                sha256(HPM_REQ),

            "v069_control_contract":
                sha256(CONTROL_CONTRACT),

            "v070_supplement_contract":
                sha256(SUPPLEMENT_CONTRACT),

            "v065_coverage_implementation":
                sha256(V065_SCRIPT),
        },

        "planned": {
            "ordinary_root_queries":
                len(ordinary),

            "hpm_pair_queries":
                len(hpm),

            "ordinary_margin_arcsec":
                MARGIN_ARCSEC,

            "hpm_margin_arcsec":
                HPM_MARGIN_ARCSEC,

            "hpm_min_masyr":
                HPM_MIN_MASYR,

            "maxrec":
                int(v65.MAXREC),

            "minimum_subdivision_cell_deg":
                float(v65.MIN_CELL_DEG),
        },

        "guards": {
            "network_access":
                False,

            "gaia_source_rows_read":
                0,

            "astrometric_registrations":
                0,

            "detector_rerun":
                False,

            "candidate_disposition_changes":
                False,
        },

        "interpretation_boundary":
            (
                "Transport plan only. "
                "No Gaia source outcome or "
                "registered-control outcome "
                "was inspected."
            ),

        "next_stage":
            (
                "Execute checkpointed v071 "
                "supplemental control-domain "
                "Gaia acquisition."
            ),
    }

    write_json(
        REPORT_OUT,
        report,
    )

    print()
    print("=" * 118)
    print("v070 PLAN COMPLETE")
    print("=" * 118)
    print(
        f"Ordinary supplemental roots: "
        f"{len(ordinary):,}"
    )
    print(
        f"HPM supplemental queries: "
        f"{len(hpm):,}"
    )
    print(
        f"Ordinary margin: "
        f"{MARGIN_ARCSEC:.1f}\""
    )
    print(
        f"HPM threshold: "
        f"{HPM_MIN_MASYR:.0f} mas/yr"
    )
    print(
        f"HPM margin: "
        f"{HPM_MARGIN_ARCSEC:.1f}\""
    )
    print()
    print("Network calls: 0")
    print("Gaia source rows read: 0")
    print("Registrations run: 0")
    print("Candidate dispositions changed: NONE")


if __name__ == "__main__":
    main()
