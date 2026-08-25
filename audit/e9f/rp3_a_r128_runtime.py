"""RP3.A fixed-six R128 diagnostic runtime; audit-only orchestration."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from audit.e9f import c3_c5_runtime as c35
from audit.e9f import c3_c2_hardening as c2
from audit.e9f import run_e9f_c1_rp2_c3_c2_impl as c2science

WORK_ORDER = "MEPHC-E9F-C1-RP3-A-20260825-256"
PHASE = "E9F.C1.RP3.A"
BASE_SANDBOX_SHA = "f579c51d3ac51dc431ae296fbe43002b7de4b51e"
SOURCE_EXECUTION_SHA = "02b8fc343b3dd786769c42cfa8e44bd57add482d"
RESOLUTION = 128
STENCILS = ("1/72", "1/144")
CANARY_SOURCE_SAMPLE_ID = "fr=0;grid_i=-4;grid_j=0;estimator=SOURCE_GRID"
CHECKPOINT_SCHEMA = "mephc_e9f_c1_rp3_a_r128_checkpoint_v1"
PAYLOAD_SCHEMA = c35.PAYLOAD_SCHEMA
POLICY_SEMANTIC_SHA = "cfbe71ff9f648048901038823c25ffd358bb8a80394fe05d082a57957acfc84a"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def build_plan(root: Path) -> list[dict[str, Any]]:
    policy = c2science.load_policy(root)
    records = {item["sample_id"]: item for item in policy["immutable_inputs"]["failed_sample_records"]}
    rows = []
    for index, sample_id in enumerate(policy["rp2_diagnostic_matrix"]["fixed_sample_ids"]):
        source = records[sample_id]
        rows.append({"sample_id": f"{sample_id}::resolution=128", "source_sample_id": sample_id, "source_sample_index": int(source["sample_index"]), "sample_index": index, "resolution": RESOLUTION, "authoritative_coordinate": [float(x) for x in source["center"]]})
    if len(rows) != 6 or [row["sample_index"] for row in rows] != list(range(6)) or len({row["source_sample_id"] for row in rows}) != 6:
        raise ValueError("RP3_A_FIXED_SIX_PLAN_FAIL_CLOSED")
    return rows


def identity_for(*, row: Mapping[str, Any], execution_sha: str, contract_sha256: str, policy_sha256: str) -> dict[str, Any]:
    return {"project_id": "MEPHC", "work_order_id": WORK_ORDER, "phase": PHASE, "execution_sha": execution_sha, "source_sample_id": row["source_sample_id"], "source_sample_index": int(row["source_sample_index"]), "logical_sample_index": int(row["sample_index"]), "worker_id": row["sample_id"], "resolution": RESOLUTION, "contract_sha256": contract_sha256, "rp1_policy_file_sha256": policy_sha256, "rp1_policy_canonical_semantic_sha256": POLICY_SEMANTIC_SHA, "payload_transport": "ATOMIC_FILE"}


def body_hash(payload: Mapping[str, Any]) -> str:
    return c35.body_hash(payload)


def validate_payload(payload: Mapping[str, Any], *, row: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    c35.validate_payload(payload, row=row, expected_identity=expected)
    if payload.get("work_order_id") != WORK_ORDER or payload.get("phase") != PHASE or payload.get("resolution") != RESOLUTION or payload.get("provider", {}).get("resolution") != RESOLUTION:
        raise ValueError("RP3_A_PAYLOAD_IDENTITY_FAIL_CLOSED")
    if payload.get("replay_matched_point_count") != 0 or payload.get("replay_unmatched_point_count") != 9:
        raise ValueError("RP3_A_REPLAY_NOT_APPLICABLE_BINDING_FAIL_CLOSED")
    for point in payload.get("all_point_metrics", []):
        replay = point.get("frequency_replay", {})
        if replay.get("matched") is not False or replay.get("reason") != "R128_NOT_APPLICABLE_ORIGINAL_RP2_HAS_NO_R128_KEY":
            raise ValueError("RP3_A_REPLAY_POLICY_FAIL_CLOSED")
    if payload.get("payload_body_sha256") != body_hash(payload):
        raise ValueError("RP3_A_BODY_HASH_FAIL_CLOSED")


def execution_order(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    canary = [row["sample_id"] for row in rows if row["source_sample_id"] == CANARY_SOURCE_SAMPLE_ID]
    rest = [row["sample_id"] for row in rows if row["source_sample_id"] != CANARY_SOURCE_SAMPLE_ID]
    if len(canary) != 1 or len(rest) != 5:
        raise ValueError("RP3_A_EXECUTION_ORDER_FAIL_CLOSED")
    return canary + rest


def construct_checkpoint(*, completed: Sequence[Mapping[str, Any]], rows: Sequence[Mapping[str, Any]], execution_sha: str, contract_sha256: str, policy_sha256: str) -> dict[str, Any]:
    order = execution_order(rows)
    return {"schema": CHECKPOINT_SCHEMA, "work_order_id": WORK_ORDER, "phase": PHASE, "execution_sha": execution_sha, "contract_sha256": contract_sha256, "rp1_policy_file_sha256": policy_sha256, "execution_order_definition": "CANARY_FIRST_THEN_POLICY_ORDER", "execution_order": order, "generation": len(completed), "completed_workers": [dict(x) for x in completed]}


def scan_rp3_orphans(worker_ids: Sequence[str]) -> list[int]:
    from audit.e9f import c4_process
    found = []
    for worker_id in worker_ids:
        found.extend(c4_process.scan_orphans("rp3_a_r128_worker.py", worker_id))
    return sorted(set(found))


def _validate_checkpoint_item(item: Mapping[str, Any], row: Mapping[str, Any], checkpoint: Mapping[str, Any], *, root: Path) -> None:
    required = ("worker_id", "source_sample_id", "logical_sample_index", "resolution", "payload_path", "payload_file_sha256", "payload_body_sha256", "execution_sha", "contract_sha256", "policy_sha256", "item_generation", "terminal_payload_status")
    if any(key not in item for key in required):
        raise ValueError("RP3_A_CHECKPOINT_ITEM_FIELDS_FAIL_CLOSED")
    expected = {"worker_id": row["sample_id"], "source_sample_id": row["source_sample_id"], "logical_sample_index": row["sample_index"], "resolution": RESOLUTION, "execution_sha": checkpoint["execution_sha"], "contract_sha256": checkpoint["contract_sha256"], "policy_sha256": checkpoint["rp1_policy_file_sha256"]}
    if any(item.get(key) != value for key, value in expected.items()) or item.get("item_generation") < 1 or item.get("terminal_payload_status") != "COMPLETE":
        raise ValueError("RP3_A_CHECKPOINT_ITEM_IDENTITY_FAIL_CLOSED")
    path = Path(item["payload_path"])
    if not path.is_file() or sha(path) != item["payload_file_sha256"]:
        raise ValueError("RP3_A_CHECKPOINT_FILE_HASH_FAIL_CLOSED")
    payload = json.loads(path.read_text())
    if payload.get("payload_body_sha256") != item["payload_body_sha256"]:
        raise ValueError("RP3_A_CHECKPOINT_BODY_HASH_FAIL_CLOSED")
    validate_payload(payload, row=row, expected=identity_for(row=row, execution_sha=checkpoint["execution_sha"], contract_sha256=checkpoint["contract_sha256"], policy_sha256=checkpoint["rp1_policy_file_sha256"]))


def validate_checkpoint(checkpoint: Mapping[str, Any], *, root: Path, rows: Sequence[Mapping[str, Any]], orphan_scan: Any = None) -> None:
    if checkpoint.get("schema") != CHECKPOINT_SCHEMA or checkpoint.get("work_order_id") != WORK_ORDER or checkpoint.get("phase") != PHASE:
        raise ValueError("RP3_A_CHECKPOINT_IDENTITY_FAIL_CLOSED")
    order = execution_order(rows)
    if checkpoint.get("execution_order") != order or checkpoint.get("execution_order_definition") != "CANARY_FIRST_THEN_POLICY_ORDER":
        raise ValueError("RP3_A_CHECKPOINT_EXECUTION_ORDER_FAIL_CLOSED")
    scanner = orphan_scan if callable(orphan_scan) else scan_rp3_orphans
    live = list(scanner(order))
    if live:
        raise ValueError("RP3_A_CHECKPOINT_ORPHAN_FAIL_CLOSED")
    completed = checkpoint.get("completed_workers", [])
    if checkpoint.get("generation") != len(completed) or checkpoint["generation"] > len(order):
        raise ValueError("RP3_A_CHECKPOINT_GENERATION_FAIL_CLOSED")
    if [item.get("worker_id") for item in completed] != order[:len(completed)]:
        raise ValueError("RP3_A_CHECKPOINT_EXACT_PREFIX_FAIL_CLOSED")
    by_id = {row["sample_id"]: row for row in rows}
    for item in completed:
        _validate_checkpoint_item(item, by_id[item["worker_id"]], checkpoint, root=root)


def resume_suffix(*, checkpoint: Mapping[str, Any], root: Path, rows: Sequence[Mapping[str, Any]], orphan_scan: Any = None) -> list[dict[str, Any]]:
    validate_checkpoint(checkpoint, root=root, rows=rows, orphan_scan=orphan_scan)
    order = execution_order(rows)
    by_id = {row["sample_id"]: dict(row) for row in rows}
    return [by_id[worker_id] for worker_id in order[checkpoint["generation"]:]]

def convergence_rows(*, root: Path, payloads: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    old = json.loads((root / "audit/e9f/c3_c5_c1_c1_postprocess.json").read_text())["complete_entries"]
    old_map = {(x["source_sample_id"], int(x["resolution"]), x["stencil"]): x for x in old}
    rows = []
    spectral = []
    for payload in payloads:
        sample = payload["source_sample_id"]
        for stencil in STENCILS:
            for branch, key in (("band2", "BAND2"), ("band3", "BAND3")):
                values = [old_map[(sample, resolution, stencil)][key]["OMEGA_RANK1_SHADOW"] for resolution in (64, 96)]
                r128 = payload["stencils"][stencil][("BAND2_PHYSICAL_BRANCH_SHADOW" if branch == "band2" else "BAND3_PHYSICAL_BRANCH_SHADOW")]["OMEGA_RANK1_SHADOW"]
                d_old = values[1] - values[0]; d_new = r128 - values[1]
                rows.append({"source_sample_id": sample, "branch": branch, "stencil": stencil, "omega_R64": values[0], "omega_R96": values[1], "omega_R128": r128, "delta_R64_to_R96_signed": d_old, "delta_R64_to_R96_abs": abs(d_old), "delta_R96_to_R128_signed": d_new, "delta_R96_to_R128_abs": abs(d_new), "contraction_ratio_diagnostic_only": None if d_old == 0 else abs(d_new) / abs(d_old)})
        l0 = payload["center"]["L0"]
        spectral.append({"source_sample_id": sample, "center_L0_R128": l0, "R128_REPLAY_POLICY": "NOT_APPLICABLE_R128"})
    return rows, spectral


RP3_C1_INCIDENT_IDS = tuple(f"REL-{index:03d}" for index in range(21, 55))
RP3_C1_P2_IDS = ("REL-022", "REL-025", "REL-034", "REL-035")
RP3_C1_OPEN_IDS = ("REL-052", "REL-054")


def canonical_rp3_a_c1_process_registry(*, closed: bool = False) -> dict[str, Any]:
    open_ids = set() if closed else set(RP3_C1_OPEN_IDS)
    incidents = [{"incident_id": incident_id, "priority": "P2" if incident_id in RP3_C1_P2_IDS else "P1", "status": "OPEN" if incident_id in open_ids else "CLOSED"} for incident_id in RP3_C1_INCIDENT_IDS]
    return {"schema": "mephc_e9f_c1_rp3_a_c1_process_registry_v1", "work_order_id": "MEPHC-E9F-C1-RP3-A-C1-20260825-258", "pipeline_health": "PIPELINE_HEALTHY_WITH_TECH_DEBT" if closed else "PIPELINE_REQUIRES_CORRECTIVE", "incidents": incidents, "p0_items": [], "p1_items": list(sorted(open_ids)), "p2_items": []}


def validate_rp3_a_c1_process_registry(registry: Mapping[str, Any], *, closed: bool = False) -> None:
    expected = canonical_rp3_a_c1_process_registry(closed=closed)
    if dict(registry) != expected:
        raise ValueError("RP3_A_C1_PROCESS_REGISTRY_CANONICAL_STATE_FAIL_CLOSED")
