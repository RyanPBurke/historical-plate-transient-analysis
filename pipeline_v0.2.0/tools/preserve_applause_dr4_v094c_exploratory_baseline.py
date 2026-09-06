#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

EXPECTED = {
    "contract": "a1565dcae73c886441c901d99386dcf07d5c29dbd6307c9c7ea98964f5e7bec7",
    "runner": "89bc8b0c4d93a9057a6aaec62495f974ef32762b2556a31a0d65fe79e2520492",
    "report": "73dd190c2185b17b188d8eb3f58fcca9b0b02f68e00f389c82f015a266c9ab18",
    "bank": "aad4a277797be0e5f33e5d48c19cbd4873c14482c18fa6efb08af3fe504f23d4",
}

LABEL = (
    "Exploratory raw-coordinate screening baseline; preserved for reproducibility "
    "and superseded for confirmatory inference."
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def copy_verified(src: Path, dst: Path, expected_sha: str | None = None) -> dict:
    if not src.is_file():
        raise FileNotFoundError(src)
    actual = sha256(src)
    if expected_sha and actual != expected_sha:
        raise RuntimeError(f"SHA256 mismatch for {src}: {actual} != {expected_sha}")
    shutil.copy2(src, dst)
    copied = sha256(dst)
    if copied != actual:
        raise RuntimeError(f"Post-copy SHA256 mismatch for {dst}")
    return {"source": str(src), "name": dst.name, "sha256": copied, "size_bytes": dst.stat().st_size}


def deterministic_gzip(src: Path, dst: Path) -> dict:
    # Opaque byte-for-byte compression only. No CSV parsing is performed.
    with src.open("rb") as fin, dst.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            shutil.copyfileobj(fin, gz, length=8 * 1024 * 1024)
    return {
        "source_sha256": sha256(src),
        "source_size_bytes": src.stat().st_size,
        "gzip_name": dst.name,
        "gzip_sha256": sha256(dst),
        "gzip_size_bytes": dst.stat().st_size,
        "gzip_mtime": 0,
        "gzip_original_filename_field": "",
    }


def gzip_uncompressed_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with gzip.open(path, "rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def split_file(path: Path, max_part_bytes: int) -> list[dict]:
    parts = []
    with path.open("rb") as f:
        idx = 1
        while True:
            chunk = f.read(max_part_bytes)
            if not chunk:
                break
            p = path.with_name(path.name + f".part{idx:03d}")
            p.write_bytes(chunk)
            parts.append({"name": p.name, "sha256": sha256(p), "size_bytes": p.stat().st_size})
            idx += 1
    if parts:
        path.unlink()
    return parts


def main() -> int:
    ap = argparse.ArgumentParser(description="Preserve frozen v094c exploratory baseline without parsing candidates")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="pipeline_v0.2.0 root")
    ap.add_argument("--split-mib", type=int, default=90, help="maximum compressed part size")
    args = ap.parse_args()
    root = args.root.resolve()

    contract = root / "research" / "prospective_freezes" / "applause_dr4_tierA_busko_source_census_zero_source_continuation_contract_v094c.json"
    runner = root / "tools" / "run_applause_dr4_tierA_busko_source_census_v094c.py"
    result = root / "results" / "applause_dr4_tierA_busko_source_census_v094c"
    report = result / "applause_dr4_tierA_busko_source_census_v094c.json"
    bank = result / "applause_dr4_v094c_bank_manifest.json"
    candidate = result / "applause_dr4_tierA_busko_independent_catalogue_candidates_v094c.csv"
    hold = result / "applause_dr4_tierA_zero_source_triplet_holds_v094c.csv"
    audit = root / "work" / "applause_dr4_tierA_busko_source_census_v094c" / "state" / "zero_source_audit_v094c.json"

    for p in (contract, runner, report, bank, candidate, hold, audit):
        if not p.is_file():
            raise FileNotFoundError(f"Required v094c artifact missing: {p}")

    # Verify frozen implementation and locally completed baseline before creating anything.
    for label, p in (("contract", contract), ("runner", runner), ("report", report), ("bank", bank)):
        actual = sha256(p)
        if actual != EXPECTED[label]:
            raise RuntimeError(f"Frozen {label} SHA256 mismatch: {actual} != {EXPECTED[label]}")

    report_obj = json.loads(report.read_text(encoding="utf-8-sig"))
    bank_obj = json.loads(bank.read_text(encoding="utf-8-sig"))

    candidate_sha = sha256(candidate)
    hold_sha = sha256(hold)
    audit_sha = sha256(audit)

    candidate_refs = {
        "report": report_obj.get("candidate_csv_sha256"),
        "bank": bank_obj.get("candidate_csv_sha256"),
    }
    hold_refs = {
        "report": report_obj.get("zero_source_hold_csv_sha256"),
        "bank": bank_obj.get("zero_source_hold_csv_sha256"),
    }
    expected_audit = bank_obj.get("zero_source_audit_sha256")
    bank_report_ref = bank_obj.get("report_sha256")
    if bank_report_ref and bank_report_ref != EXPECTED["report"]:
        raise RuntimeError(f"Frozen bank does not reference the frozen report SHA256: {bank_report_ref} != {EXPECTED['report']}")

    candidate_integrity_basis = "newly_established_at_preservation"
    hold_integrity_basis = "newly_established_at_preservation"
    candidate_verified_by = []
    hold_verified_by = []
    for source_name, expected_candidate in candidate_refs.items():
        if expected_candidate:
            if candidate_sha != expected_candidate:
                raise RuntimeError(
                    f"Candidate CSV disagrees with frozen v094c {source_name}: {candidate_sha} != {expected_candidate}"
                )
            candidate_verified_by.append(source_name)
    for source_name, expected_hold in hold_refs.items():
        if expected_hold:
            if hold_sha != expected_hold:
                raise RuntimeError(
                    f"Hold CSV disagrees with frozen v094c {source_name}: {hold_sha} != {expected_hold}"
                )
            hold_verified_by.append(source_name)
    if candidate_verified_by:
        candidate_integrity_basis = "verified_against_frozen_v094c_" + "_and_".join(candidate_verified_by)
    if hold_verified_by:
        hold_integrity_basis = "verified_against_frozen_v094c_" + "_and_".join(hold_verified_by)
    if expected_audit and audit_sha != expected_audit:
        raise RuntimeError(f"Zero-source audit disagrees with frozen v094c bank: {audit_sha} != {expected_audit}")

    expected_hold = hold_refs.get("report") or hold_refs.get("bank")

    out = root / "research_snapshots" / "applause_dr4_tierA_busko_source_census_v094c_exploratory_preservation"
    if out.exists():
        # Idempotent only if prior preservation manifest says COMPLETE; otherwise do not overwrite evidence.
        prior = out / "preservation_manifest_v094c.json"
        if not prior.is_file():
            raise RuntimeError(f"Preservation directory exists without manifest: {out}")
        old = json.loads(prior.read_text(encoding="utf-8"))
        if old.get("status") != "COMPLETE":
            raise RuntimeError(f"Prior preservation is not COMPLETE: {out}")
        print(f"v094c preservation already COMPLETE: {out}")
        return 0

    out.mkdir(parents=True)
    copied = []
    copied.append(copy_verified(report, out / report.name, EXPECTED["report"]))
    copied.append(copy_verified(bank, out / bank.name, EXPECTED["bank"]))
    copied.append(copy_verified(hold, out / hold.name, expected_hold))
    copied.append(copy_verified(audit, out / audit.name, expected_audit))
    copied.append(copy_verified(contract, out / contract.name, EXPECTED["contract"]))
    copied.append(copy_verified(runner, out / runner.name, EXPECTED["runner"]))

    gz = out / (candidate.name + ".gz")
    compressed = deterministic_gzip(candidate, gz)
    if compressed["source_sha256"] != candidate_sha:
        raise RuntimeError("Candidate source changed during preservation")
    roundtrip_sha = gzip_uncompressed_sha256(gz)
    if roundtrip_sha != candidate_sha:
        raise RuntimeError(f"Deterministic gzip round-trip SHA256 mismatch: {roundtrip_sha} != {candidate_sha}")
    compressed["verified_uncompressed_roundtrip_sha256"] = roundtrip_sha

    max_part_bytes = args.split_mib * 1024 * 1024
    parts = []
    if gz.stat().st_size > max_part_bytes:
        parts = split_file(gz, max_part_bytes)
        compressed["storage"] = "split_deterministic_gzip"
        compressed["parts"] = parts
        compressed["reconstruction"] = (
            "Concatenate parts in lexical order to recreate the deterministic .csv.gz, then gunzip. "
            "PowerShell example: $o=[IO.File]::Create('candidate.csv.gz'); Get-ChildItem '*.part*' | "
            "Sort-Object Name | ForEach-Object { $b=[IO.File]::ReadAllBytes($_.FullName); $o.Write($b,0,$b.Length) }; $o.Close()"
        )
    else:
        compressed["storage"] = "single_deterministic_gzip"

    outcome = {
        "preserved_utc": datetime.now(timezone.utc).isoformat(),
        "blinding_status": "PARTIAL_OUTCOME_KNOWLEDGE",
        "known_at_preservation": {
            "v094c_candidate_catalogue_rows": 327883,
            "primary_le3_rows": 253701,
            "diagnostic_gt3_le5_rows": 74182,
            "aggregate_yield_concentration_was_inspected": True,
            "individual_global_v094c_candidate_coordinates_inspected": False,
            "individual_global_v094c_candidate_identities_inspected": False,
        },
    }
    write_json(out / "outcome_knowledge_at_preservation.json", outcome)

    readme = f"""# v094c exploratory preservation\n\n{LABEL}\n\nThis directory is an **archival preservation**, not scientific validation. It preserves the completed v094c raw-coordinate catalogue-mismatch screen before fragment-aware timing repair.\n\nKnown limitations include: parent exposure envelopes were used without `exposure_sub` fragment timing; the 784 directed triplets are not a universal branch denominator; second-site matching used raw catalogue coordinates; source absence is not a qualified negative; and the v094c survivors are not a valid input population for a parallax-permitting branch.\n\nThe candidate CSV was never parsed by the preservation script. It was hashed and compressed as an opaque byte stream. Its original SHA256 is `{candidate_sha}` and its integrity basis is `{candidate_integrity_basis}`.\n\nThe zero-source hold table SHA256 is `{hold_sha}` and its integrity basis is `{hold_integrity_basis}`.\n\nTo verify this snapshot, check `SHA256SUMS.txt` and `preservation_manifest_v094c.json`. If the candidate gzip is split, concatenate `.partNNN` files in lexical order before decompression.\n"""
    (out / "README.md").write_text(readme, encoding="utf-8")

    manifest = {
        "status": "COMPLETE",
        "analysis_kind": "applause_dr4_v094c_exploratory_preservation",
        "label": LABEL,
        "preservation_is_scientific_validation": False,
        "candidate_csv_parsed": False,
        "candidate_csv_integrity_basis": candidate_integrity_basis,
        "zero_source_hold_integrity_basis": hold_integrity_basis,
        "frozen_expected_hashes": EXPECTED,
        "copied_files": copied,
        "candidate_archive": compressed,
        "outcome_knowledge_file": "outcome_knowledge_at_preservation.json",
        "known_limitations_recorded": True,
    }
    write_json(out / "preservation_manifest_v094c.json", manifest)

    # Hash everything except SHA256SUMS itself, sorted for deterministic output.
    lines = []
    for p in sorted(x for x in out.iterdir() if x.is_file() and x.name != "SHA256SUMS.txt"):
        lines.append(f"{sha256(p)}  {p.name}")
    (out / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="ascii")

    print("v094c exploratory baseline preservation COMPLETE")
    print(f"snapshot={out}")
    print(f"candidate_integrity={candidate_integrity_basis}")
    print(f"candidate_sha256={candidate_sha}")
    print(f"candidate_storage={compressed['storage']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
