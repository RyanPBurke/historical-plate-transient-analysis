from pathlib import Path
import csv
import hashlib
import importlib.util
import json

ROOT = Path.cwd()
RESULTS = ROOT / "results"
TOOLS = ROOT / "tools"
RESEARCH = ROOT / "research"

V069_DIR = (
    RESULTS
    / "wide_census_registered_control_coverage_preflight_v069"
)

V069_REPORT = (
    V069_DIR
    / "wide_census_registered_control_coverage_preflight_v069.json"
)

V069_MISSING = (
    V069_DIR
    / "wide_census_registered_control_missing_cells_v069.csv"
)

V069_HPM = (
    V069_DIR
    / "wide_census_registered_control_hpm_requirements_v069.csv"
)

V070_DIR = (
    RESULTS
    / "wide_census_registered_control_gaia_supplement_plan_v070"
)

V070_REPORT = (
    V070_DIR
    / "wide_census_registered_control_gaia_supplement_plan_v070.json"
)

V070_ORD = (
    V070_DIR
    / "wide_census_registered_control_ordinary_query_plan_v070.csv"
)

V070_HPM = (
    V070_DIR
    / "wide_census_registered_control_hpm_query_plan_v070.csv"
)

V071B_DIR = (
    RESULTS
    / "wide_census_registered_control_gaia_supplemental_acquisition_v071b"
)

V071B_REPORT = (
    V071B_DIR
    / "wide_census_registered_control_gaia_supplemental_acquisition_v071b.json"
)

V071B_MANIFEST = (
    V071B_DIR
    / "wide_census_registered_control_gaia_supplemental_manifest_v071b.csv"
)

V071B_SCRIPT = (
    TOOLS
    / "run_wide_census_registered_control_gaia_supplemental_acquisition_v071b.py"
)

V069_SCRIPT = (
    TOOLS
    / "preflight_wide_census_registered_controls_v069.py"
)

V070_SCRIPT = (
    TOOLS
    / "plan_wide_census_registered_control_gaia_supplement_v070.py"
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

OUTDIR = (
    RESULTS
    / "wide_census_registered_control_gaia_closure_v072"
)

REPORT_OUT = (
    OUTDIR
    / "wide_census_registered_control_gaia_closure_v072.json"
)

EXPECTED = {
    V069_SCRIPT:
        "0471c95ae5fd44b7d0c951de18aa2af493a276257747fe0e0850bc9c6288dbe9",

    V070_SCRIPT:
        "ae76b497c7b27f35ed056748347ef7493605bc61b0d91531cf942ff1c3c28277",

    V071B_SCRIPT:
        "d24d5a491d53dc529b4c80887d0c2e5e2b423470db2e80cb0efea15787b4693a",

    CONTROL_CONTRACT:
        "be2febd2696f1798a0a78c2724420f3aaac939a825ebe5b296b126ba9ce47eeb",

    SUPPLEMENT_CONTRACT:
        "91c7fb695ab2e664e93556bfba31acfbb81abf8665a5ac8ef8a7a64671073e6c",
}

EXPECTED_ORDINARY = 3009
EXPECTED_HPM = 16


def sha(path):
    h = hashlib.sha256()

    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)

    return h.hexdigest()


def read_csv(path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        return list(csv.DictReader(f))


def write_json(path, obj):
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    tmp = path.with_suffix(
        path.suffix + ".tmp"
    )

    with tmp.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            obj,
            f,
            indent=2,
            sort_keys=True,
        )

    tmp.replace(path)


def truthy(v):
    return str(v).strip().lower() in (
        "true",
        "1",
        "yes",
    )


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(
        name,
        path,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"Cannot import {path}"
        )

    mod = importlib.util.module_from_spec(
        spec
    )

    spec.loader.exec_module(mod)

    return mod


def main():
    print("=" * 118)
    print(
        "WIDE CENSUS REGISTERED-CONTROL "
        "GAIA COVERAGE CLOSURE AUDIT v072"
    )
    print("=" * 118)
    print("Network access: NO")
    print("Gaia source rows interpreted: NO")
    print("Astrometric registrations: NO")
    print("Candidate dispositions: NONE")
    print()

    required = (
        V069_REPORT,
        V069_MISSING,
        V069_HPM,
        V070_REPORT,
        V070_ORD,
        V070_HPM,
        V071B_REPORT,
        V071B_MANIFEST,
    )

    for p in required:
        if not p.is_file():
            raise RuntimeError(
                f"Missing prerequisite: {p}"
            )

    for path, expected in EXPECTED.items():
        if not path.is_file():
            raise RuntimeError(
                f"Missing frozen prerequisite: {path}"
            )

        actual = sha(path)

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

    v070 = json.loads(
        V070_REPORT.read_text(
            encoding="utf-8-sig"
        )
    )

    v071 = json.loads(
        V071B_REPORT.read_text(
            encoding="utf-8-sig"
        )
    )

    if v069.get("status") != "COMPLETE":
        raise RuntimeError(
            "v069 preflight not COMPLETE"
        )

    if v070.get("status") != "COMPLETE":
        raise RuntimeError(
            "v070 plan not COMPLETE"
        )

    if v071.get("status") != "COMPLETE":
        raise RuntimeError(
            "v071b acquisition not COMPLETE"
        )

    # --------------------------------------------------------------
    # Ordinary-domain closure.
    # --------------------------------------------------------------

    missing = read_csv(
        V069_MISSING
    )

    ord_plan = read_csv(
        V070_ORD
    )

    if len(missing) != EXPECTED_ORDINARY:
        raise RuntimeError(
            f"v069 missing-cell count changed: {len(missing)}"
        )

    if len(ord_plan) != EXPECTED_ORDINARY:
        raise RuntimeError(
            f"v070 ordinary-plan count changed: {len(ord_plan)}"
        )

    missing_cells = {
        (
            int(r["cell_ira"]),
            int(r["cell_idec"]),
        )
        for r in missing
    }

    planned_cells = {
        (
            int(r["base_cell_ira"]),
            int(r["base_cell_idec"]),
        )
        for r in ord_plan
    }

    if len(missing_cells) != EXPECTED_ORDINARY:
        raise RuntimeError(
            "v069 missing-cell inventory contains duplicates"
        )

    if len(planned_cells) != EXPECTED_ORDINARY:
        raise RuntimeError(
            "v070 ordinary plan contains duplicate base cells"
        )

    if planned_cells != missing_cells:
        only_missing = sorted(
            missing_cells - planned_cells
        )

        only_plan = sorted(
            planned_cells - missing_cells
        )

        raise RuntimeError(
            "Ordinary coverage domain mismatch:\n"
            f"  missing but unplanned: {only_missing[:10]}\n"
            f"  planned but not missing: {only_plan[:10]}"
        )

    for r in ord_plan:
        if (
            r["mode"]
            != "FULL_NEW_BASE_CELL_CONTROL"
        ):
            raise RuntimeError(
                "Unexpected v070 ordinary mode: "
                + repr(r["mode"])
            )

    # --------------------------------------------------------------
    # HPM-domain closure.
    # --------------------------------------------------------------

    hpm_req = read_csv(
        V069_HPM
    )

    gaps = [
        r for r in hpm_req
        if not truthy(
            r[
                "existing_query_covers_control_domain"
            ]
        )
    ]

    hpm_plan = read_csv(
        V070_HPM
    )

    if len(gaps) != EXPECTED_HPM:
        raise RuntimeError(
            f"v069 HPM gap count changed: {len(gaps)}"
        )

    if len(hpm_plan) != EXPECTED_HPM:
        raise RuntimeError(
            f"v070 HPM plan count changed: {len(hpm_plan)}"
        )

    gap_by_pair = {
        int(r["pair_index"]): r
        for r in gaps
    }

    plan_by_pair = {
        int(r["pair_index"]): r
        for r in hpm_plan
    }

    if set(gap_by_pair) != set(plan_by_pair):
        raise RuntimeError(
            "HPM gap/pair inventory mismatch"
        )

    tol = 1e-12

    for idx in sorted(gap_by_pair):
        g = gap_by_pair[idx]
        p = plan_by_pair[idx]

        checks = (
            (
                float(
                    g[
                        "required_control_query_ra_deg"
                    ]
                ),
                float(p["query_ra_deg"]),
                "RA",
            ),
            (
                float(
                    g[
                        "required_control_query_dec_deg"
                    ]
                ),
                float(p["query_dec_deg"]),
                "Dec",
            ),
            (
                float(
                    g[
                        "required_control_query_radius_deg"
                    ]
                ),
                float(p["query_radius_deg"]),
                "radius",
            ),
        )

        for expected, actual, label in checks:
            if abs(expected - actual) > tol:
                raise RuntimeError(
                    f"HPM pair {idx} {label} changed: "
                    f"{expected} vs {actual}"
                )

        if abs(
            float(p["pm_min_masyr"])
            - 1700.0
        ) > tol:
            raise RuntimeError(
                f"HPM threshold changed for pair {idx}"
            )

        if abs(
            float(
                p[
                    "j2016_hpm_transport_margin_arcsec"
                ]
            )
            - 915.0
        ) > tol:
            raise RuntimeError(
                f"HPM margin changed for pair {idx}"
            )

    # --------------------------------------------------------------
    # Re-run v071b cache reconciliation.
    #
    # This reads cache metadata and hashes compressed transport files.
    # It does NOT parse Gaia catalogue source rows and does NOT call
    # the network.
    # --------------------------------------------------------------

    worker = load_module(
        V071B_SCRIPT,
        "frozen_v071b",
    )

    worker_plan = worker.read_csv(
        worker.PLAN
    )

    worker_hpm = worker.read_csv(
        worker.HPLAN
    )

    (
        manifest,
        done,
        leaves,
        rows,
        compressed_bytes,
        hdone,
        hrows,
        hcompressed,
    ) = worker.scan_all(
        worker_plan,
        worker_hpm,
    )

    if done != EXPECTED_ORDINARY:
        raise RuntimeError(
            f"Ordinary root closure failed: {done}/{EXPECTED_ORDINARY}"
        )

    if hdone != EXPECTED_HPM:
        raise RuntimeError(
            f"HPM closure failed: {hdone}/{EXPECTED_HPM}"
        )

    if len(manifest) != EXPECTED_ORDINARY:
        raise RuntimeError(
            f"Manifest count changed: {len(manifest)}"
        )

    bad = [
        r for r in manifest
        if r.get("status") != "COMPLETE"
    ]

    if bad:
        raise RuntimeError(
            f"Incomplete ordinary roots remain: {len(bad)}"
        )

    progress = v071.get(
        "progress",
        {}
    )

    if int(
        progress.get(
            "ordinary_root_complete",
            -1,
        )
    ) != EXPECTED_ORDINARY:
        raise RuntimeError(
            "v071b report ordinary completion changed"
        )

    if int(
        progress.get(
            "ordinary_root_total",
            -1,
        )
    ) != EXPECTED_ORDINARY:
        raise RuntimeError(
            "v071b report ordinary total changed"
        )

    if int(
        progress.get(
            "hpm_complete",
            -1,
        )
    ) != EXPECTED_HPM:
        raise RuntimeError(
            "v071b report HPM completion changed"
        )

    if int(
        progress.get(
            "hpm_total",
            -1,
        )
    ) != EXPECTED_HPM:
        raise RuntimeError(
            "v071b report HPM total changed"
        )

    if int(
        v071.get(
            "registered_control_science_outcomes_inspected",
            -1,
        )
    ) != 0:
        raise RuntimeError(
            "Registered-control science outcome guard changed"
        )

    guards = v071.get(
        "guards",
        {}
    )

    if bool(
        guards.get(
            "astrometric_registration_run",
            True,
        )
    ):
        raise RuntimeError(
            "v071b unexpectedly reports registration"
        )

    if bool(
        guards.get(
            "candidate_state_mutation",
            True,
        )
    ):
        raise RuntimeError(
            "v071b unexpectedly reports candidate mutation"
        )

    report = {
        "status":
            "COMPLETE",

        "analysis_kind":
            "wide_census_registered_control_gaia_closure_v072",

        "coverage": {
            "v069_missing_ordinary_cells":
                len(missing_cells),

            "v070_planned_ordinary_cells":
                len(planned_cells),

            "v071b_complete_ordinary_roots":
                done,

            "resolved_ordinary_leaf_queries":
                leaves,

            "ordinary_gaps_remaining":
                0,

            "v069_hpm_gap_pairs":
                len(gap_by_pair),

            "v070_planned_hpm_pairs":
                len(plan_by_pair),

            "v071b_complete_hpm_pairs":
                hdone,

            "hpm_gaps_remaining":
                0,
        },

        "transport_cache": {
            "ordinary_cached_rows_including_overlap":
                rows,

            "hpm_cached_rows":
                hrows,

            "ordinary_compressed_bytes":
                compressed_bytes,

            "hpm_compressed_bytes":
                hcompressed,

            "compressed_sha_reconciliation":
                "PASS",
        },

        "input_sha256": {
            "v069_report":
                sha(V069_REPORT),

            "v069_missing_cells":
                sha(V069_MISSING),

            "v069_hpm_requirements":
                sha(V069_HPM),

            "v070_report":
                sha(V070_REPORT),

            "v070_ordinary_plan":
                sha(V070_ORD),

            "v070_hpm_plan":
                sha(V070_HPM),

            "v071b_report":
                sha(V071B_REPORT),

            "v071b_manifest":
                sha(V071B_MANIFEST),

            "v071b_runner":
                sha(V071B_SCRIPT),
        },

        "guards": {
            "network_access":
                False,

            "gaia_source_rows_interpreted":
                0,

            "astrometric_registrations":
                0,

            "candidate_disposition_changes":
                False,

            "registered_control_science_outcomes_inspected":
                0,
        },

        "interpretation_boundary":
            (
                "Transport/reference coverage closure only. "
                "This audit does not calculate registered "
                "control separations or compare controls "
                "with observed associations."
            ),

        "next_stage":
            (
                "Registered-control astrometric registration "
                "may now be implemented under the frozen "
                "registered-control contract."
            ),
    }

    write_json(
        REPORT_OUT,
        report,
    )

    print()
    print("=" * 118)
    print("v072 COVERAGE CLOSURE PASS")
    print("=" * 118)
    print(
        f"v069 ordinary gaps identified: "
        f"{len(missing_cells):,}"
    )
    print(
        f"v071b ordinary roots complete: "
        f"{done:,}/{EXPECTED_ORDINARY:,}"
    )
    print(
        f"Resolved ordinary leaves:      "
        f"{leaves:,}"
    )
    print(
        "Ordinary gaps remaining:      0"
    )
    print()
    print(
        f"v069 HPM gaps identified:      "
        f"{len(gap_by_pair)}"
    )
    print(
        f"v071b HPM jobs complete:       "
        f"{hdone}/{EXPECTED_HPM}"
    )
    print(
        "HPM gaps remaining:           0"
    )
    print()
    print(
        f"Cached ordinary rows:          "
        f"{rows:,}"
    )
    print(
        f"Cached HPM rows:               "
        f"{hrows:,}"
    )
    print(
        "Compressed-cache integrity:   PASS"
    )
    print()
    print("Network calls:                 0")
    print("Gaia source rows interpreted:  0")
    print("Registrations run:             0")
    print("Candidate dispositions:        NONE")
    print("Control science outcomes seen: 0")
    print()
    print("COVERAGE STATUS: COMPLETE")


if __name__ == "__main__":
    main()
