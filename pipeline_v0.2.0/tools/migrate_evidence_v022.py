from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

from transient_pipeline.provenance import EvidenceStore, sha256_file

MUTABLE_KINDS = {
    "poss1_identity_preflight_csv",
    "stage_results_csv",
    "applause_resolved_manifest",
}


def utcstamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main() -> int:
    root = Path("evidence")
    index = root / "index" / "evidence.jsonl"
    marker = Path("research") / "EVIDENCE_INDEX_MIGRATION_v0.2.2_2026-08-20.json"

    if marker.exists():
        print(f"Migration already recorded: {marker}")
        print(marker.read_text(encoding="utf-8"))
        return 0
    if not index.exists():
        raise SystemExit(f"missing evidence index: {index}")

    original = index.read_bytes()
    original_sha = hashlib.sha256(original).hexdigest()
    history = root / "index" / "history"
    history.mkdir(parents=True, exist_ok=True)
    backup = history / f"evidence_pre_v0.2.2_{utcstamp()}_{original_sha[:12]}.jsonl"
    backup.write_bytes(original)

    kept: list[dict] = []
    removed: list[dict] = []
    invalid_lines: list[dict] = []
    for line_no, raw_line in enumerate(original.decode("utf-8").splitlines(), 1):
        if not raw_line.strip():
            continue
        try:
            rec = json.loads(raw_line)
        except Exception as exc:
            invalid_lines.append({"line": line_no, "error": str(exc), "text": raw_line})
            continue
        if rec.get("record_type") == "local_artifact" and rec.get("kind") in MUTABLE_KINDS:
            removed.append({"line": line_no, "record": rec})
        else:
            kept.append(rec)

    if invalid_lines:
        raise SystemExit(
            "Evidence index contains invalid JSON; refusing automatic migration. "
            f"Backup preserved at {backup}. Invalid lines: {invalid_lines[:3]}"
        )

    # Rewrite only after exact backup exists.
    tmp = index.with_suffix(index.suffix + ".migrate.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for rec in kept:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
    tmp.replace(index)

    store = EvidenceStore(root)
    # Preserve exact pre-migration index as an immutable provenance artifact.
    backup_rec = store.record_artifact(
        path=backup,
        kind="evidence_index_pre_v0.2.2_backup",
        stage="evidence-migration:v0.2.2",
        metadata={"original_index_sha256": original_sha, "removed_mutable_record_count": len(removed)},
    )

    # Snapshot the CURRENT reconstructible state of every removed generated product.
    # Historical old bytes may have been overwritten; their old hashes remain in the
    # exact pre-migration index backup above and are explicitly not reconstructed.
    current_snapshots: list[dict] = []
    seen = set()
    for item in removed:
        rec = item["record"]
        source = Path(rec.get("source_path") or rec.get("path") or "")
        kind = str(rec.get("kind") or "generated_output")
        key = (str(source), kind)
        if key in seen or not source.exists() or not source.is_file():
            continue
        seen.add(key)
        snap = store.record_artifact(
            path=source,
            kind=kind,
            stage="evidence-migration:v0.2.2",
            metadata={
                "migration_current_state_snapshot": True,
                "legacy_working_path": str(source),
                "note": "Current bytes snapshotted after correcting legacy mutable-working-path indexing. Prior hashes remain in immutable pre-migration index backup.",
            },
            snapshot=True,
        )
        current_snapshots.append(snap)

    marker.parent.mkdir(parents=True, exist_ok=True)
    migration = {
        "migration": "v0.2.2 mutable-derived-artifact evidence correction",
        "performed_at_utc": datetime.now(timezone.utc).isoformat(),
        "scientific_algorithm_changed": False,
        "scientific_results_changed": False,
        "reason": (
            "v0.2.0/v0.2.1 indexed regenerated CSV/manifests at mutable working paths. "
            "A legitimate checkpoint rerun rewrote results/poss1_identity_preflight.csv, causing hash verification to flag the old path/hash pair."
        ),
        "pre_migration_index": {
            "path": str(backup),
            "sha256": original_sha,
            "bytes": len(original),
            "evidence_record": backup_rec,
        },
        "removed_legacy_mutable_index_records": len(removed),
        "removed_kinds": sorted(MUTABLE_KINDS),
        "removed_record_hashes": [
            {
                "line": item["line"],
                "kind": item["record"].get("kind"),
                "path": item["record"].get("path"),
                "sha256": item["record"].get("sha256"),
            }
            for item in removed
        ],
        "current_content_addressed_snapshots": [
            {
                "kind": rec.get("kind"),
                "source_path": rec.get("source_path"),
                "path": rec.get("path"),
                "sha256": rec.get("sha256"),
                "bytes": rec.get("bytes"),
            }
            for rec in current_snapshots
        ],
        "policy_after_migration": (
            "Regenerated derived tables/manifests are indexed only as content-addressed immutable snapshots; "
            "stable scientific FITS/raw responses continue to be hash-verified directly."
        ),
    }
    marker.write_text(json.dumps(migration, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    store.record_artifact(
        path=marker,
        kind="evidence_index_migration_record",
        stage="evidence-migration:v0.2.2",
    )

    print(json.dumps({
        "backup": str(backup),
        "backup_sha256": original_sha,
        "kept_records": len(kept),
        "removed_mutable_records": len(removed),
        "current_snapshots": len(current_snapshots),
        "migration_record": str(marker),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
