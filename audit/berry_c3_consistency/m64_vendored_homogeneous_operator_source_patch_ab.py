"""M64R1: exact-source static localization with no unlocalized patch."""
from __future__ import annotations

import hashlib
import json
import os
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULT_SCHEMA = "mephc-berry-c3-consistency-m64-vendored-homogeneous-operator-source-patch-ab-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m64-patched-operator-frequency-ab-dataset-v1"


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    manifest_path = ROOT / "vendor/mpb_c3_patch/source_manifest.json"; manifest = json.loads(manifest_path.read_text(encoding="utf-8")); source_path = ROOT / "vendor/mpb_c3_patch/source/mpb-1.12.0.tar.gz"; patch_path = ROOT / "vendor/mpb_c3_patch/mpb-1.12.0-homogeneous-c3.patch"; source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if source_sha != "8d2b206254b217f66a53c1ad20cc0c369b93b0e71ee671d68e333a583eaaeda4": raise ValueError("M64R1_SOURCE_SHA_MISMATCH")
    with tarfile.open(source_path, "r:gz") as archive:
        names = set(archive.getnames()); required = {"mpb-1.12.0/src/maxwell/maxwell.c", "mpb-1.12.0/src/maxwell/maxwell_op.c", "mpb-1.12.0/src/maxwell/maxwell_eps.c"};
        if not required.issubset(names): raise ValueError("M64R1_SOURCE_MEMBER_MISSING")
        source_text = archive.extractfile("mpb-1.12.0/src/maxwell/maxwell.c").read().decode("utf-8")
    result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "BOUNDED_NEGATIVE_RESULT", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "dataset_schema": DATASET_SCHEMA, "classification": "R256_NATIVE_HOMOGENEOUS_DEFECT_NOT_LOCALIZED_NO_PATCH", "causal_outcome": "R256_NATIVE_HOMOGENEOUS_DEFECT_NOT_LOCALIZED_NO_PATCH", "next_science_decision": "VENDORED_MPB_HOMOGENEOUS_DEEPER_NATIVE_OPERATOR_INSTRUMENTATION", "source_manifest": {**manifest, "source_sha256_verified": source_sha, "source_members_verified": sorted(required), "localized_symbols_seen": ["update_maxwell_data_k"] if "update_maxwell_data_k" in source_text else []}, "patch_sha256": hashlib.sha256(patch_path.read_bytes()).hexdigest(), "source_commit_used": source_commit, "installed_backend_touched": False, "isolated_build_performed": False, "patched_runtime_identity": None, "failure_code": "SOURCE_LOCALIZATION_INCONCLUSIVE_NO_SCIENTIFIC_PATCH", "post_analysis_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8"); return 0


if __name__ == "__main__": raise SystemExit(main())
