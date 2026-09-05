"""M64: fail closed when the exact accepted MPB source artifact is unavailable."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULT_SCHEMA = "mephc-berry-c3-consistency-m64-vendored-homogeneous-operator-source-patch-ab-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m64-patched-operator-frequency-ab-dataset-v1"


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    manifest_path = ROOT / "vendor/mpb_c3_patch/source_manifest.json"; manifest = json.loads(manifest_path.read_text(encoding="utf-8")); patch_path = ROOT / "vendor/mpb_c3_patch/mpb-1.12.0-homogeneous-c3.patch"
    result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "BLOCKED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "dataset_schema": DATASET_SCHEMA, "classification": "R256_NATIVE_HOMOGENEOUS_DEFECT_NOT_LOCALIZED_NO_PATCH", "causal_outcome": "R256_NATIVE_HOMOGENEOUS_DEFECT_NOT_LOCALIZED_NO_PATCH", "next_science_decision": "VENDORED_MPB_HOMOGENEOUS_DEEPER_NATIVE_OPERATOR_INSTRUMENTATION", "source_manifest": manifest, "patch_sha256": hashlib.sha256(patch_path.read_bytes()).hexdigest(), "source_commit_used": source_commit, "installed_backend_touched": False, "isolated_build_performed": False, "patched_runtime_identity": None, "failure_code": "EXACT_MPB_1_12_0_SOURCE_ARTIFACT_UNAVAILABLE", "post_analysis_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8"); return 0


if __name__ == "__main__": raise SystemExit(main())
